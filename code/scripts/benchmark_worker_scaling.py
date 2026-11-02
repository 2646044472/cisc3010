"""Compare real model replicas on one host, with saved workloads and token checks."""
import argparse
import datetime
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from llm_lab.common import ROOT, RUNS, json_http, read_worker_events, write_json
from llm_lab.experiment import run_remote
from llm_lab.check import check_run


def wait_ready(url, count, proc, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError("gateway exited during startup; inspect benchmark logs")
        try:
            state = json_http(url + "/api/state")
            if len(state["workers"]) == count and all(w.get("healthy") for w in state["workers"]):
                return
        except (OSError, ValueError):
            pass
        time.sleep(.25)
    raise RuntimeError("model workers did not become ready")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8900)
    parser.add_argument("--worker-counts", default="1,2,4")
    parser.add_argument("--threads", type=int, default=2, choices=range(1, 17))
    parser.add_argument("--count", type=int, default=24)
    parser.add_argument("--rate", type=float, default=6)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    counts = [int(v) for v in args.worker_counts.split(",")]
    if not counts or len(set(counts)) != len(counts) or any(not 1 <= n <= 16 for n in counts):
        parser.error("use distinct worker counts from 1 to 16")
    if not 1 <= args.port <= 65535 - max(counts):
        parser.error("gateway and worker ports must fit within 1-65535")
    if not 1 <= args.repeats <= 10 or not 4 <= args.count <= 200 or not 1 <= args.rate <= 50:
        parser.error("use 1-10 repeats, 4-200 requests, and 1-50 arrivals/s")
    url = f"http://127.0.0.1:{args.port}"
    # Never reuse or stop an unrelated service on this port.
    import socket
    for port in range(args.port, args.port + max(counts) + 1):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                parser.error(f"port {port} is already in use")
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S")
    folder = RUNS / ("scaling-" + stamp)
    folder.mkdir(parents=True, exist_ok=False)
    write_json(folder / "contract.json", {
        "backend": "cpu-model", "deployment": "single_host_replicas", "worker_counts": counts,
        "threads_per_worker": args.threads, "active_slots_per_worker": 4, "kv_budget_per_worker": 4096,
        "requests": args.count, "arrival_rate": args.rate, "seed": 3010, "repeats": args.repeats,
        "ordering": "ascending then descending on alternating repeats",
        "startup_included": False, "warmup": "two tokens per worker before each measured run",
        "interpretation": "Fixed offered workload. Replicas share host CPU and memory. Thread and slot totals grow with worker count. Not a multi-host scalability estimate."
    })
    results, reference, shape = [], None, None
    for repeat in range(args.repeats):
        order = counts if repeat % 2 == 0 else list(reversed(counts))
        for count in order:
            label = f"trial-{repeat + 1}-workers-{count}"
            print(f"START {label}", flush=True)
            with (folder / (label + ".log")).open("w", encoding="utf-8") as log:
                proc = subprocess.Popen([sys.executable, "-m", "llm_lab", "serve", "--backend", "cpu-model",
                    "--port", str(args.port), "--workers", str(count), "--threads", str(args.threads)],
                    cwd=ROOT, stdout=log, stderr=log)
                try:
                    wait_ready(url, count, proc)
                    result = run_remote(url, {"scenario": "routing", "routing": "least_outstanding",
                        "count": args.count, "rate": args.rate, "seed": 3010, "execution": "selective",
                        "scheduling": "continuous", "chunked_prefill": True, "prefill_chunk": 128})
                    source = RUNS / result["run_id"]
                    check = check_run(source)
                    if not check["passed"] or not check["all_completed"]:
                        raise RuntimeError("run failed its independent check: " + result["run_id"])
                    manifest = json.loads((source / "workload.json").read_text(encoding="utf-8"))
                    current_shape = [(r["prompt"], r["max_tokens"], r["arrival_s"]) for r in manifest]
                    by_request = {}
                    for event in read_worker_events(source):
                        if event["event"] == "token":
                            by_request.setdefault(event["request_id"], []).append(event)
                    outputs = [[e["token_id"] for e in sorted(by_request[r["request_id"]], key=lambda e: e["seq"])] for r in manifest]
                    if reference is None:
                        reference, shape = outputs, current_shape
                    if reference != outputs or shape != current_shape:
                        raise RuntimeError("workload or greedy token IDs differ between runs")
                    result["repeat"] = repeat + 1
                    results.append(result)
                    write_json(folder / "results.json", results)
                    print(json.dumps({"workers": count, "repeat": repeat + 1, "requests_s": result["requests_s"],
                        "ttft_p95_ms": result["ttft_p95_ms"], "check": check["passed"], "run_id": result["run_id"]}), flush=True)
                finally:
                    if proc.poll() is None:
                        try:
                            json_http(url + "/api/shutdown", {})
                        except OSError:
                            pass
                        # Owned gateway closes every owned model process on orderly shutdown.
                        try:
                            proc.wait(timeout=30)
                        except subprocess.TimeoutExpired:
                            proc.terminate()
                            proc.wait(timeout=10)
    metrics = ["requests_s", "tokens_s", "ttft_p95_ms", "latency_p95_ms", "queue_p95_ms", "inter_token_p99_ms"]
    summary = []
    for count in counts:
        group = [r for r in results if r["worker_count"] == count]
        row = {"workers": count, "trials": len(group)}
        for key in metrics:
            values = [r[key] for r in group if r[key] is not None]
            row[key] = {"mean": statistics.mean(values), "sample_sd": statistics.stdev(values) if len(values) > 1 else None}
        summary.append(row)
    write_json(folder / "summary.json", summary)
    write_json(folder / "output-consistency.json", {"passed": True, "runs": len(results),
        "requests_checked": len(results) * args.count, "criterion": "Identical greedy token IDs per workload position"})
    print(json.dumps({"folder": str(folder), "summary": summary}), flush=True)


if __name__ == "__main__":
    main()
