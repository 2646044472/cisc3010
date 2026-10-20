from __future__ import annotations

import collections
import concurrent.futures
import csv
import datetime
import json
import platform
import random
import statistics
import threading
import urllib.error
import urllib.request
import uuid

from .check import check_run
from .common import RUNS, ROOT, TERMINAL, Trace, json_http, now, read_events, write_json


def percentile(values, fraction):
    if not values:
        return None
    values = sorted(values)
    position = (len(values) - 1) * fraction
    low = int(position)
    high = min(low + 1, len(values) - 1)
    return values[low] + (values[high] - values[low]) * (position - low)


def workload(count, rate, seed, run_id):
    rng = random.Random(seed)
    prefix = "You are a helpful systems tutor. Explain the following mechanism with a concrete example and describe the assumptions behind its behavior. Use clear language and keep the explanation focused on the student's question."
    items = []
    for i in range(count):
        long = rng.random() < 0.3
        prompt = prefix + " Explain request scheduling." + (" A request can have a long context." * 28 if long else "")
        items.append({"request_id": f"{run_id}-r-{i:04d}", "prompt": prompt,
                      "max_tokens": 120 if long else 16, "class": "long" if long else "short",
                      "arrival_s": i / rate, "run_id": run_id})
    return items


def client_request(url, item, trace=None, origin=None, cancel_after=None):
    start = now()
    row = {"request_id": item["request_id"], "class": item.get("class", "interactive"), "tenant": item.get("tenant", "benchmark"),
           "scheduled_s": item.get("arrival_s", 0), "start": start, "end": None,
           "dispatch_lateness_ms": max(0, (start - origin - item.get("arrival_s", 0)) * 1000) if origin else 0,
           "first": None, "sequences": [], "token_times": [], "text": "", "worker": None,
           "status": "failed", "error": None, "http_status": None,
           "retry_after_s": None, "rejection_code": None}
    request = urllib.request.Request(url + "/api/generate", json.dumps(item).encode(), {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            row["http_status"] = response.status
            for raw in response:
                if not raw.startswith(b"data: "):
                    continue
                event = json.loads(raw[6:])
                received = now()
                if trace:
                    trace.write(item.get("run_id"), {"t": received, **{k: v for k, v in event.items() if k != "t"}})
                if event["event"] == "assigned":
                    row["worker"] = event["worker"]
                elif event["event"] == "token":
                    if row["first"] is None:
                        row["first"] = received
                    row["sequences"].append(event["seq"])
                    row["token_times"].append(received - start)
                    row["text"] = event.get("text") if event.get("text") is not None else row["text"] + event["delta"]
                    if cancel_after and len(row["sequences"]) == cancel_after:
                        json_http(url + "/api/cancel", {"request_id": item["request_id"]})
                elif event["event"] in TERMINAL:
                    row["status"] = event["event"]
                    row["error"] = event.get("reason")
                    break
    except urllib.error.HTTPError as exc:
        row["status"] = "rejected"
        row["error"] = exc.read().decode()
        row["http_status"] = exc.code
        row["retry_after_s"] = exc.headers.get("Retry-After")
        try:
            row["rejection_code"] = json.loads(row["error"]).get("code")
        except ValueError:
            pass
    except Exception as exc:
        row["error"] = str(exc)
    row["end"] = now()
    row["latency_ms"] = (row["end"] - start) * 1000
    row["ttft_ms"] = None if row["first"] is None else (row["first"] - start) * 1000
    row["tokens"] = len(row["sequences"])
    return row


class RunController:
    def __init__(self, gateway, port):
        self.gateway = gateway
        self.url = f"http://127.0.0.1:{port}"
        self.cancel = threading.Event()
        self.thread = None

    def start(self, data):
        count = data.get("count", 40)
        rate = data.get("rate", 10)
        seed = data.get("seed", 3010)
        scenario = data.get("scenario", "routing")
        if isinstance(count, bool) or not isinstance(count, int) or not 4 <= count <= 200:
            raise ValueError("count must be an integer from 4 to 200")
        if isinstance(rate, bool) or not isinstance(rate, (float, int)) or not 1 <= rate <= (200 if scenario == "surge" else 50):
            raise ValueError("invalid arrival rate (1–50, or 1–200 for surge)")
        if type(seed) is not int or not 0 <= seed <= 2**32 - 1:
            raise ValueError("invalid seed")
        if scenario not in {"routing", "batching", "cache", "fault", "cancel", "heterogeneous", "surge", "multi_tenant"}:
            raise ValueError("invalid scenario")
        cfg = {"routing": data.get("routing", "least_outstanding"),
               "scheduling": data.get("scheduling", "continuous"), "execution": data.get("execution", "selective"), "slots": data.get("slots", 4),
               "kv_budget": data.get("kv_budget", 4096), "chunked_prefill": data.get("chunked_prefill", True),
               "prefill_chunk": data.get("prefill_chunk", 128 if self.gateway.pool.backend == "cpu-model" else 32), "prefix_cache": scenario == "cache",
               "cache_budget": 512, "speed": 1.0}
        if cfg["routing"] not in {"round_robin", "least_outstanding", "token_work", "cache_aware"}:
            raise ValueError("invalid routing policy")
        if cfg["scheduling"] not in {"continuous", "static"} or type(cfg["slots"]) is not int or not 1 <= cfg["slots"] <= 16:
            raise ValueError("invalid scheduling/slots")
        if cfg["execution"] not in {"selective", "sequential"}:
            raise ValueError("invalid execution")
        if type(cfg["kv_budget"]) is not int or not 512 <= cfg["kv_budget"] <= 65536:
            raise ValueError("invalid KV budget")
        if type(cfg["chunked_prefill"]) is not bool or type(cfg["prefill_chunk"]) is not int or not 1 <= cfg["prefill_chunk"] <= 4096:
            raise ValueError("invalid prefill configuration")
        if scenario == "cache" and self.gateway.pool.backend != "simulator":
            raise ValueError("cache experiment uses the simulator")
        if scenario == "heterogeneous" and self.gateway.pool.backend != "simulator":
            raise ValueError("the slow-worker timing scenario uses the simulator")
        with self.gateway.lock:
            if self.thread and self.thread.is_alive():
                raise RuntimeError("a run is already active")
            if any(r["status"] not in TERMINAL for r in self.gateway.requests.values()):
                raise RuntimeError("wait for interactive requests to finish before replay")
            stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S")
            run_id = stamp + "-" + uuid.uuid4().hex[:8]
            run = {"run_id": run_id, "status": "running", "phase": "preparing", "count": count,
                   "rate": rate, "scenario": scenario, "routing": cfg["routing"],
                   "scheduling": cfg["scheduling"], "completed": 0, "started": now()}
            self.gateway.active_run = run
        self.cancel.clear()
        self.thread = threading.Thread(target=self.execute, args=(run, cfg, seed), daemon=True)
        self.thread.start()
        return run.copy()

    def execute(self, run, cfg, seed):
        folder = RUNS / run["run_id"]
        fault_timer = None
        sampler_stop = threading.Event()
        sampler = None
        samples = []
        try:
            self.gateway.configure(cfg, run["run_id"])
            if run["scenario"] == "heterogeneous":
                health = json_http(self.gateway.pool.urls["worker-2"] + "/configure", {"speed": 3.0})
                with self.gateway.lock:
                    self.gateway.health["worker-2"] = health
            # Warm both actual processes. Cache and counters are reset below.
            for i, (wid, url) in enumerate(self.gateway.pool.urls.items()):
                req = urllib.request.Request(url + "/generate", json.dumps({"prompt": "Explain a queue.", "max_tokens": 2,
                      "request_id": "warm-" + run["run_id"] + str(i)}).encode(), {"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=120) as response:
                    for _ in response:
                        pass
                worker_cfg = cfg.copy()
                worker_cfg.pop("routing")
                if run["scenario"] == "heterogeneous" and wid == "worker-2":
                    worker_cfg["speed"] = 3.0
                json_http(url + "/configure", worker_cfg)
            manifest = workload(run["count"], run["rate"], seed, run["run_id"])
            if run["scenario"] == "multi_tenant":
                for i, item in enumerate(manifest):
                    item["tenant"] = "client-a" if i % 2 == 0 else "client-b"
            elif run["scenario"] == "surge":
                for item in manifest:
                    item["tenant"] = "demo"
            if self.gateway.pool.backend == "cpu-model":
                for item in manifest:
                    item["max_tokens"] = min(item["max_tokens"], 48)
            config = {"run_id": run["run_id"], "scenario": run["scenario"], "backend": self.gateway.pool.backend,
                      "settings": cfg, "seed": seed, "count": run["count"], "arrival_model": "fixed interval, open loop",
                      "rate": run["rate"], "warmup": "2 tokens per worker; cache cleared before measurement",
                      "service_cost": ({"decode_s": "(0.012 + 0.002 * active_decode_sequences) * speed",
                                       "prefill_s": "(0.003 + 0.00025 * chunk_tokens) * speed",
                                       "cache": "32-word exact prefix; local LRU; simulated prefill saving only"}
                                       if self.gateway.pool.backend == "simulator" else {
                                           "execution": "Measured CPU operations; no simulated sleep",
                                           "batching": cfg["execution"], "prefill": "decode-first shared prefill token allowance"}),
                      "environment": {"python": sys_version(), "platform": platform.platform(), "workers": 2,
                                      "model_threads_per_worker": 2 if self.gateway.pool.backend == "cpu-model" else None},
                      "worker_start": [json_http(url + "/health") for url in self.gateway.pool.urls.values()]}
            config["admission_plans"] = self.gateway.admission.PLANS
            write_json(folder / "config.json", config)
            write_json(folder / "workload.json", manifest)
            run["phase"] = "replaying"
            origin = now()
            run["measurement_start"] = origin
            def sample():
                while not sampler_stop.is_set():
                    snapshot = self.gateway.snapshot()
                    item = {"t": now(), "gateway_cpu_s": snapshot["gateway_cpu_s"], "admission": snapshot["admission"],
                            "outstanding": sum(w["outstanding"] for w in snapshot["workers"]),
                            "workers": [{k: w.get(k) for k in ["id", "pid", "healthy", "queued", "active", "kv_reserved", "kv_payload_bytes", "cpu_process_s"]}
                                        for w in snapshot["workers"]]}
                    samples.append(item)
                    Trace("samples").write(run["run_id"], item)
                    sampler_stop.wait(0.25)
            sampler = threading.Thread(target=sample, daemon=True)
            sampler.start()
            if run["scenario"] == "fault":
                def kill():
                    Trace("control").write(run["run_id"], {"event": "worker_stop", "worker": "worker-1", "t": now()})
                    self.gateway.pool.stop("worker-1")
                fault_timer = threading.Timer(1.0, kill)
                fault_timer.start()
            results = []
            trace = Trace("client")
            with concurrent.futures.ThreadPoolExecutor(max_workers=200) as executor:
                futures = []
                for item in manifest:
                    if self.cancel.wait(max(0, origin + item["arrival_s"] - now())):
                        raise RuntimeError("run cancelled by service shutdown")
                    cancel_after = 3 if run["scenario"] == "cancel" and int(item["request_id"].split("-")[-1]) % 4 == 0 else None
                    futures.append(executor.submit(client_request, self.url, item, trace, origin, cancel_after))
                for future in concurrent.futures.as_completed(futures):
                    results.append(future.result())
                    run["completed"] = len(results)
            elapsed = now() - origin
            sampler_stop.set()
            sampler.join(timeout=2)
            results.sort(key=lambda row: row["request_id"])
            write_json(folder / "requests.json", results)
            run["phase"] = "checking"
            deadline = now() + 5
            while True:
                workers = []
                for wid, url in self.gateway.pool.urls.items():
                    try:
                        workers.append(json_http(url + "/health", timeout=0.5))
                    except Exception:
                        workers.append({"id": wid, "healthy": False})
                outstanding = sum(r["status"] not in TERMINAL for r in self.gateway.requests.values())
                if outstanding == 0 and all(not w.get("active", 0) and not w.get("queued", 0) for w in workers):
                    break
                if now() > deadline:
                    break
                self.cancel.wait(0.05)
            write_json(folder / "cleanup.json", {"outstanding": outstanding, "workers": workers,
                                                  "admission": self.gateway.snapshot()["admission"]})
            check = check_run(folder)
            write_json(folder / "check.json", check)
            success = [r for r in results if r["status"] == "completed"]
            ttft = [r["ttft_ms"] for r in success if r["ttft_ms"] is not None]
            latencies = [r["latency_ms"] for r in success]
            local_waits = []
            events = read_events(folder / "worker-1.jsonl") + read_events(folder / "worker-2.jsonl")
            by_id = collections.defaultdict(dict)
            for e in events:
                if e["event"] in {"queued", "started"}:
                    by_id[e["request_id"]][e["event"]] = e["t"]
            for row in results:
                state = by_id[row["request_id"]]
                row["queue_ms"] = (state["started"] - state["queued"]) * 1000 if "started" in state and "queued" in state else None
                if row["queue_ms"] is not None:
                    local_waits.append(row["queue_ms"])
            write_json(folder / "requests.json", results)
            with (folder / "requests.csv").open("w", newline="", encoding="utf-8") as stream:
                keys = ["request_id", "class", "tenant", "worker", "status", "http_status", "rejection_code", "retry_after_s", "tokens", "ttft_ms", "latency_ms", "queue_ms", "dispatch_lateness_ms"]
                writer = csv.DictWriter(stream, fieldnames=keys, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(results)
            result = {"run_id": run["run_id"], "scenario": run["scenario"], "backend": self.gateway.pool.backend,
                      "routing": cfg["routing"], "scheduling": cfg["scheduling"], "execution": cfg["execution"], "rate": run["rate"],
                      "chunked_prefill": cfg["chunked_prefill"], "prefill_chunk": cfg["prefill_chunk"],
                      "count": len(results), "successes": len(success), "elapsed_s": elapsed,
                      "requests_s": len(success) / elapsed,
                      "tokens_s": sum(r["tokens"] for r in success) / elapsed,
                      "ttft_median_ms": statistics.median(ttft) if ttft else None,
                      "ttft_p95_ms": percentile(ttft, 0.95), "latency_p95_ms": percentile(latencies, 0.95),
                      "inter_token_p95_ms": percentile([(b - a) * 1000 for r in success
                          for a, b in zip(r["token_times"], r["token_times"][1:])], 0.95),
                      "inter_token_p99_ms": percentile([(b - a) * 1000 for r in success
                          for a, b in zip(r["token_times"], r["token_times"][1:])], 0.99),
                      "queue_p95_ms": percentile(local_waits, 0.95),
                      "dispatch_lateness_p95_ms": percentile([r["dispatch_lateness_ms"] for r in results], 0.95),
                      "outcomes": dict(collections.Counter(r["status"] for r in results)),
                      "check": check, "classes": {}}
            pressure = {}
            for wid in self.gateway.pool.urls:
                states = [w for s in samples for w in s["workers"] if w["id"] == wid and w.get("healthy")]
                pressure[wid] = {"max_queue": max((w.get("queued", 0) for w in states), default=0),
                                 "active_slot_saturation_fraction": sum(w.get("active", 0) == cfg["slots"] for w in states) / len(states) if states else None,
                                 "mean_active": statistics.mean(w.get("active", 0) for w in states) if states else None}
            result["pressure"] = pressure
            controls = read_events(folder / "control.jsonl")
            stops = [e["t"] for e in controls if e["event"] == "worker_stop"]
            detections = [e["t"] for e in controls if e["event"] == "health_change" and not e["healthy"]]
            result["fault_detection_s"] = max(0, min(detections) - min(stops)) if stops and detections else None
            result["cache_hit_tokens"] = sum(w.get("counters", {}).get("cache_hit_tokens", 0) for w in workers)
            result["admission"] = self.gateway.snapshot()["admission"]
            expected_cancel = (len(results) + 3) // 4
            if run["scenario"] in {"surge", "multi_tenant"}:
                result["scenario_verified"] = check["passed"] and bool(success) and result["outcomes"].get("rejected", 0) > 0 and result["outcomes"].get("failed", 0) == 0
            elif run["scenario"] == "cancel":
                result["scenario_verified"] = check["passed"] and result["outcomes"].get("cancelled", 0) == expected_cancel and len(success) == len(results) - expected_cancel
            elif run["scenario"] == "fault":
                result["scenario_verified"] = check["passed"] and bool(stops and detections) and result["outcomes"].get("failed", 0) > 0 and any(r["worker"] == "worker-2" and r["status"] == "completed" and r["start"] > min(stops) for r in results)
            elif run["scenario"] == "cache":
                result["scenario_verified"] = check["all_completed"] and result["cache_hit_tokens"] > 0
            else:
                result["scenario_verified"] = check["passed"] and check["all_completed"]
            for cls in ["short", "long"]:
                group = [r for r in success if r["class"] == cls]
                result["classes"][cls] = {"count": len(group), "ttft_p95_ms": percentile([r["ttft_ms"] for r in group if r["ttft_ms"] is not None], 0.95),
                                         "latency_p95_ms": percentile([r["latency_ms"] for r in group], 0.95)}
            write_json(folder / "result.json", result)
            with self.gateway.lock:
                self.gateway.run_history.insert(0, result)
                self.gateway.run_history = self.gateway.run_history[:30]
                run.update({"status": "completed" if check["passed"] else "failed", "phase": "finished", "result": result})
        except Exception as exc:
            run.update({"status": "failed", "phase": "finished", "error": str(exc)})
            write_json(folder / "failure.json", run)
        finally:
            sampler_stop.set()
            if sampler:
                sampler.join(timeout=2)
            if fault_timer:
                fault_timer.cancel()
                fault_timer.join(timeout=5)
            if run["scenario"] == "fault":
                self.gateway.pool.start("worker-1")


def sys_version():
    return platform.python_version()


def run_remote(url, options):
    run = json_http(url + "/api/run", options)
    while True:
        state = json_http(url + "/api/state")
        current = state["run"]
        if current and current["run_id"] == run["run_id"] and current["status"] != "running":
            if "result" not in current:
                raise RuntimeError(current.get("error", "run failed"))
            return current["result"]
        threading.Event().wait(0.2)


def experiment(url, kind, repeats, count, rates):
    experiment_id = "experiment-" + uuid.uuid4().hex[:10]
    configs = ([{"routing": "round_robin"}, {"routing": "least_outstanding"}] if kind == "routing"
               else ([{"execution": "sequential"}, {"execution": "selective"}] if kind == "execution"
                     else ([{"chunked_prefill": False}, {"chunked_prefill": True}] if kind == "prefill"
                           else [{"scheduling": "static"}, {"scheduling": "continuous"}])))
    results = []
    for rate in rates:
        for repeat in range(repeats):
            order = configs if repeat % 2 == 0 else list(reversed(configs))
            for cfg in order:
                result = run_remote(url, {"count": count, "rate": rate, "seed": 3010,
                                          "scenario": "batching" if kind in {"execution", "prefill"} else kind, **cfg})
                if not result["check"]["passed"] or not result["check"]["all_completed"]:
                    raise RuntimeError("required experiment run failed correctness: " + result["run_id"])
                results.append(result | {"repeat": repeat + 1})
                print(json.dumps({k: result[k] for k in ["run_id", "routing", "scheduling", "execution", "rate", "requests_s", "ttft_p95_ms"]}), flush=True)
    folder = RUNS / experiment_id
    write_json(folder / "results.json", results)
    with (folder / "summary.csv").open("w", newline="", encoding="utf-8") as stream:
        keys = ["run_id", "repeat", "routing", "scheduling", "execution", "chunked_prefill", "prefill_chunk", "rate", "count", "successes", "requests_s", "tokens_s", "ttft_p95_ms", "latency_p95_ms", "inter_token_p95_ms"]
        writer = csv.DictWriter(stream, keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)
    print(str(folder), flush=True)
    return folder
