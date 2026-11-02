"""Replay an explicit alternating long/short diagnostic against a dedicated service.

In one terminal: python scripts/run_order_diagnostic.py serve --backend cpu-model
In another:      python scripts/run_order_diagnostic.py run

The service deliberately substitutes only the workload generator. It must be a
dedicated process: this script never stops or reconfigures another service.
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from llm_lab.common import write_json
from llm_lab.experiment import run_remote, workload as random_workload


def diagnostic_workload(count, rate, seed, run_id):
    if seed not in (3010, 3011) or count < 4 or count % 2:
        raise ValueError("Use an even count of at least 4 and seed 3010 or 3011")
    # Build prototypes independently of the requested size; a very small
    # sample need not happen to contain both random classes.
    prototypes = random_workload(64, rate, 3010, run_id)
    template = {kind: next(x for x in prototypes if x["class"] == kind) for kind in ("short", "long")}
    items = random_workload(count, rate, 3010, run_id)
    phase = 0 if seed == 3010 else 1
    for i, item in enumerate(items):
        kind = "long" if i % 2 == phase else "short"
        item.update({key: template[kind][key] for key in ("prompt", "max_tokens", "class")})
        item["diagnostic_pattern"] = "long_first" if phase == 0 else "short_first"
    return items


def serve(args):
    import llm_lab.experiment as experiment
    from llm_lab.gateway import serve_gateway
    experiment.workload = diagnostic_workload
    serve_gateway(args.port, args.backend, str(args.model_path), 2, 2)


def run(args):
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S")
    folder = ROOT / "runs/llm" / ("portable-order-diagnostic-" + timestamp)
    folder.mkdir(parents=True, exist_ok=False)
    protocol = {"kind": "synthetic alternating-order diagnostic", "rate": args.rate,
                "count_per_trial": args.count, "repeats_per_policy_and_phase": args.repeats,
                "phases": ["long_first", "short_first"], "status": "running",
                "interpretation": "Constructed stress case; not representative production traffic."}
    write_json(folder / "protocol.json", protocol)
    results = []
    try:
        for seed, phase in ((3010, "long_first"), (3011, "short_first")):
            for repeat in range(1, args.repeats + 1):
                policies = ["round_robin", "least_outstanding"]
                if repeat % 2 == 0:
                    policies.reverse()
                for policy in policies:
                    result = run_remote(args.url, {"count": args.count, "rate": args.rate, "seed": seed,
                        "scenario": "routing", "routing": policy, "scheduling": "continuous",
                        "execution": "selective", "slots": 4, "kv_budget": 4096,
                        "chunked_prefill": True, "prefill_chunk": 128})
                    if not result["check"]["passed"] or not result["check"]["all_completed"]:
                        raise RuntimeError("Correctness failed for " + result["run_id"])
                    manifest = json.loads((ROOT / "runs/llm" / result["run_id"] / "workload.json").read_text(encoding="utf-8"))
                    expected = ["long" if i % 2 == (0 if seed == 3010 else 1) else "short"
                                for i in range(args.count)]
                    if [x["class"] for x in manifest] != expected:
                        raise RuntimeError("Service does not use the diagnostic generator; start its dedicated serve command")
                    result.update(repeat=repeat, workload_pattern=phase, experiment_family="order_diagnostic")
                    results.append(result)
                    write_json(folder / "results.json", results)
                    print(json.dumps({key: result[key] for key in
                        ("run_id", "workload_pattern", "repeat", "routing", "requests_s", "ttft_p95_ms")}), flush=True)
        protocol["status"] = "complete"
        write_json(folder / "protocol.json", protocol)
        print(folder)
    except Exception as exc:
        protocol.update(status="failed", error=str(exc))
        write_json(folder / "protocol.json", protocol)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    server = modes.add_parser("serve")
    server.add_argument("--port", type=int, default=18980)
    server.add_argument("--backend", choices=("cpu-model", "simulator"), default="cpu-model")
    server.add_argument("--model-path", type=Path, default=ROOT / ".runtime/qwen25-05b")
    client = modes.add_parser("run")
    client.add_argument("--url", default="http://127.0.0.1:18980")
    client.add_argument("--count", type=int, default=64)
    client.add_argument("--rate", type=float, default=3)
    client.add_argument("--repeats", type=int, default=4)
    args = parser.parse_args()
    if args.mode == "serve":
        serve(args)
    else:
        if args.count < 4 or args.count % 2 or args.repeats < 1:
            parser.error("count must be even and at least 4; repeats must be positive")
        run(args)
