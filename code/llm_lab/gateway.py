from __future__ import annotations

import collections
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .common import JsonHandlerMixin, ROOT, RUNS, TERMINAL, Trace, json_http, now, safe_id, validate_request
from .admission import Admission, AdmissionError


class WorkerPool:
    def __init__(self, port, backend, model_path, worker_count=2, threads=2):
        if type(worker_count) is not int or not 1 <= worker_count <= 16:
            raise ValueError("worker count must be an integer from 1 to 16")
        if type(threads) is not int or not 1 <= threads <= 16:
            raise ValueError("threads per worker must be an integer from 1 to 16")
        if type(port) is not int or not 1 <= port <= 65535 - worker_count:
            raise ValueError("gateway and worker ports must fit within 1-65535")
        self.port = port
        self.backend = backend
        self.model_path = model_path
        self.threads = threads
        self.processes = {}
        self.lock = threading.Lock()
        self.logs = []
        self.urls = {f"worker-{i+1}": f"http://127.0.0.1:{port+i+1}" for i in range(worker_count)}

    def start(self, worker_id):
        with self.lock:
            old = self.processes.get(worker_id)
            if old and old.poll() is None:
                return
            folder = RUNS / "service"
            folder.mkdir(parents=True, exist_ok=True)
            log = (folder / (str(self.port) + "-" + worker_id + ".log")).open("a", encoding="utf-8")
            self.logs.append(log)
            args = [sys.executable, "-m", "llm_lab", "worker", "--port",
                    self.urls[worker_id].rsplit(":", 1)[1], "--id", worker_id, "--backend", self.backend,
                    "--threads", str(self.threads)]
            if self.model_path:
                args += ["--model-path", self.model_path]
            self.processes[worker_id] = subprocess.Popen(args, cwd=ROOT, stdout=log, stderr=log)

    def stop(self, worker_id):
        with self.lock:
            proc = self.processes.get(worker_id)
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)

    def close(self):
        for worker_id in self.urls:
            self.stop(worker_id)
        for log in self.logs:
            log.close()


class Gateway:
    def __init__(self, pool):
        self.pool = pool
        self.lock = threading.RLock()
        self.health = {wid: {"id": wid, "healthy": False, "backend": pool.backend} for wid in pool.urls}
        self.requests = collections.OrderedDict()
        self.seen = set()
        self.policy = "least_outstanding"
        self.rotation = 0
        self.configuring = False
        self.trace = Trace("gateway")
        self.admission = Admission()
        self.stop_event = threading.Event()
        self.active_run = None
        self.run_history = []
        for path in sorted(RUNS.glob("*/result.json"), reverse=True)[:30]:
            try:
                result = json.loads(path.read_text(encoding="utf-8"))
                if result.get("backend") == pool.backend:
                    self.run_history.append(result)
            except (OSError, ValueError):
                pass
        self.monitor = threading.Thread(target=self.monitor_loop, daemon=True)
        self.monitor.start()

    def event(self, record, kind, **fields):
        event = {"t": now(), "request_id": record["request_id"], "event": kind, **fields}
        self.trace.write(record.get("run_id"), event)
        return event

    def monitor_loop(self):
        while not self.stop_event.is_set():
            for wid, url in self.pool.urls.items():
                try:
                    health = json_http(url + "/health", timeout=0.5)
                    health["observed_at"] = now()
                except Exception:
                    with self.lock:
                        health = self.health[wid] | {"healthy": False, "observed_at": now()}
                with self.lock:
                    old_healthy = self.health[wid].get("healthy", False)
                    if old_healthy != health.get("healthy", False) and self.active_run and self.active_run["status"] == "running":
                        Trace("control").write(self.active_run["run_id"], {"t": now(), "event": "health_change", "worker": wid, "healthy": health.get("healthy", False)})
                    self.health[wid] = health
            self.stop_event.wait(0.25)

    def configure(self, data, run_id=None):
        policy = data.get("routing", "least_outstanding")
        if policy not in {"round_robin", "least_outstanding", "token_work", "cache_aware"}:
            raise ValueError("invalid routing policy")
        with self.lock:
            if self.configuring or any(r["status"] not in TERMINAL for r in self.requests.values()):
                raise RuntimeError("configuration requires an idle service")
            if self.active_run and self.active_run["status"] == "running" and self.active_run["run_id"] != run_id:
                raise RuntimeError("an experiment is running")
            self.configuring = True
        try:
            cfg = {k: v for k, v in data.items() if k != "routing"}
            if cfg.get("prefix_cache") and self.pool.backend != "simulator":
                raise ValueError("prefix cache experiment requires simulator")
            health = {}
            for wid, url in self.pool.urls.items():
                self.pool.start(wid)
                deadline = now() + 120
                while True:
                    try:
                        current = json_http(url + "/health", timeout=0.5)
                        if current["active"] == 0 and current["queued"] == 0:
                            break
                    except Exception:
                        pass
                    if self.pool.processes[wid].poll() is not None:
                        raise RuntimeError("worker exited during startup: " + wid + ". Check runs/llm/service logs")
                    if now() > deadline:
                        raise RuntimeError("worker did not become idle: " + wid)
                    self.stop_event.wait(0.1)
                health[wid] = json_http(url + "/configure", cfg)
            with self.lock:
                self.policy = policy
                self.rotation = 0
                self.admission.reset()
                self.health.update(health)
            return self.snapshot()
        finally:
            with self.lock:
                self.configuring = False

    def score(self, wid, prompt, maximum, messages=None):
        records = [r for r in self.requests.values() if r.get("worker") == wid and r["status"] not in TERMINAL]
        outstanding = len(records)
        if self.policy == "least_outstanding":
            return float(outstanding)
        work = sum(max(0, r["max_tokens"] - r["tokens"]) + (r["input_estimate"] * 0.08 if r["tokens"] == 0 else 0) for r in records)
        input_cost = (len(prompt.split()) if not messages else sum(len(m["content"].split()) for m in messages)) * 0.08
        if self.policy == "cache_aware":
            from .common import simulator_input
            prefix = " ".join(simulator_input(prompt, messages).split()[:32])
            if prefix in self.health[wid].get("cache_keys", []):
                input_cost -= 32 * 0.08
        return work + maximum + input_cost

    def trim_records(self):
        while len(self.requests) > 600:
            old = next((key for key, item in self.requests.items() if item["status"] in TERMINAL), None)
            if old is None:
                break
            self.requests.pop(old)

    def assign(self, data):
        with self.lock:
            if self.configuring:
                raise RuntimeError("service configuration in progress")
            if self.active_run and self.active_run["status"] == "running" and data.get("run_id") != self.active_run["run_id"]:
                raise RuntimeError("interactive requests are paused during reproducible experiments")
            if data["request_id"] in self.seen:
                raise ValueError("duplicate request ID")
            data = data.copy()
            if data.get("run_id") and self.active_run and data["run_id"] == self.active_run["run_id"]:
                if self.active_run["scenario"] not in {"surge", "multi_tenant"}:
                    data["tenant"] = "benchmark"
            elif data.get("tenant") == "benchmark":
                raise ValueError("benchmark quota is reserved for controlled runs")
            data.setdefault("tenant", "demo")
            input_estimate = len(data["prompt"].split()) if not data.get("messages") else sum(len(m["content"].split()) for m in data["messages"])
            reservation = input_estimate + data["max_tokens"]
            try:
                self.admission.admit(data["tenant"], reservation, self.requests.values())
            except AdmissionError as exc:
                rejected = data | {"worker": None, "status": "rejected", "stage": "rejected", "tokens": 0,
                                   "text": "", "arrival": now(), "finished": now(), "first_token": None,
                                   "reason": exc.code, "routing": self.policy, "reservation": 0}
                self.requests[data["request_id"]] = rejected
                self.trim_records()
                self.event(rejected, "arrival", tenant=data["tenant"])
                self.event(rejected, "rejected", tenant=data["tenant"], reason=exc.code)
                raise
            if sum(r["status"] not in TERMINAL for r in self.requests.values()) >= 128:
                raise RuntimeError("gateway outstanding-request limit reached")
            candidates = [wid for wid, state in self.health.items() if state.get("healthy")]
            if not candidates:
                raise RuntimeError("no healthy workers")
            if self.policy == "round_robin":
                wid = candidates[self.rotation % len(candidates)]
                self.rotation += 1
                scores = {}
            else:
                scores = {wid: self.score(wid, data["prompt"], data["max_tokens"], data.get("messages")) for wid in candidates}
                best = min(scores.values())
                tied = [wid for wid in candidates if scores[wid] == best]
                wid = tied[self.rotation % len(tied)]
                self.rotation += 1
            record = data | {"worker": wid, "status": "queued", "tokens": 0, "text": "",
                             "input_estimate": input_estimate, "arrival": now(),
                             "first_token": None, "finished": None, "routing": self.policy,
                             "stage": "routed", "reservation": reservation,
                             "model": self.health[wid].get("model"), "revision": self.health[wid].get("revision")}
            self.requests[data["request_id"]] = record
            self.seen.add(data["request_id"])
            self.trim_records()
            self.event(record, "arrival", max_tokens=data["max_tokens"], input_estimate=record["input_estimate"])
            self.event(record, "assigned", worker=wid, tenant=data["tenant"], reservation=reservation, routing=self.policy, scores=scores)
            return record

    def cancel(self, rid):
        with self.lock:
            record = self.requests.get(rid)
            if not record or record["status"] in TERMINAL:
                return False
            wid = record["worker"]
        return json_http(self.pool.urls[wid] + "/cancel", {"request_id": rid})["cancelled"]

    def stream(self, record):
        req = urllib.request.Request(self.pool.urls[record["worker"]] + "/generate",
                                     json.dumps({key: record.get(key) for key in ["request_id", "prompt", "max_tokens", "run_id", "messages", "tenant"]}).encode(),
                                     {"Content-Type": "application/json"})
        ended = False
        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                for line in response:
                    event = json.loads(line)
                    kind = event["event"]
                    with self.lock:
                        if kind in {"queued", "started", "prefill"}:
                            record["stage"] = "queued" if kind == "queued" else "prefill"
                            if kind != "prefill":
                                self.event(record, kind, worker=record["worker"])
                        elif kind == "token":
                            record["status"] = "active"
                            record["stage"] = "streaming"
                            record["tokens"] += 1
                            record["text"] = event.get("text") if event.get("text") is not None else record["text"] + event["delta"]
                            if record["first_token"] is None:
                                record["first_token"] = now()
                            self.event(record, "token", seq=event["seq"], worker=record["worker"])
                        elif kind in TERMINAL:
                            record["status"] = kind
                            record["stage"] = kind
                            record["finished"] = now()
                            self.event(record, kind, worker=record["worker"], tokens=record["tokens"], reason=event.get("reason"))
                            ended = True
                    yield event
                    if ended:
                        return
                raise RuntimeError("worker stream ended without a terminal event")
        except GeneratorExit:
            try:
                self.cancel(record["request_id"])
            except Exception:
                pass
            raise
        except Exception as exc:
            with self.lock:
                record["status"] = "failed"
                record["stage"] = "failed"
                record["finished"] = now()
                record["reason"] = str(exc)
                event = self.event(record, "failed", worker=record["worker"], tokens=record["tokens"], reason=str(exc))
                ended = True
            try:
                self.cancel(record["request_id"])
            except Exception:
                pass
            yield event
        finally:
            if not ended:
                with self.lock:
                    record["status"] = "cancelled"
                    record["stage"] = "cancelled"
                    record["finished"] = now()
                    self.event(record, "cancelled", worker=record["worker"], tokens=record["tokens"], reason="downstream disconnected")

    def snapshot(self):
        with self.lock:
            workers = []
            for wid, health in self.health.items():
                work = [r for r in self.requests.values() if r.get("worker") == wid and r["status"] not in TERMINAL]
                workers.append(health | {"outstanding": len(work),
                                         "estimated_remaining": sum(max(0, r["max_tokens"] - r["tokens"]) for r in work)})
            records = [{k: v for k, v in r.items() if k not in {"prompt", "messages", "input_estimate"}}
                       for r in list(self.requests.values())[-100:]]
            run = None if self.active_run is None else self.active_run.copy()
            if run and run["status"] == "running":
                run["completed"] = sum(r["run_id"] == run["run_id"] and r["status"] in TERMINAL for r in self.requests.values())
            return {"routing": self.policy, "backend": self.pool.backend, "workers": workers,
                    "worker_count": len(workers), "deployment": "single_host_replicas",
                    "gateway_pid": os.getpid(), "gateway_cpu_s": time.process_time(),
                    "admission": self.admission.snapshot(self.requests.values()),
                    "requests": records, "run": run,
                    "history": self.run_history[:24], "configuring": self.configuring,
                    "time": now()}


def serve_gateway(port=8790, backend="simulator", model_path=None, worker_count=2, threads=2):
    from .experiment import RunController
    pool = WorkerPool(port, backend, model_path, worker_count, threads)
    gateway = Gateway(pool)
    controller = RunController(gateway, port)

    class Handler(JsonHandlerMixin, BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/api/state":
                return self.reply(gateway.snapshot())
            if self.path == "/metrics":
                snapshot = gateway.snapshot()
                lines = ["# TYPE tokenflow_worker_up gauge", "# TYPE tokenflow_worker_active gauge",
                         "# TYPE tokenflow_worker_queued gauge", "# TYPE tokenflow_worker_kv_reserved gauge",
                         "# TYPE tokenflow_worker_generated_tokens counter"]
                for w in snapshot["workers"]:
                    label = '{worker="' + w["id"] + '"}'
                    for metric, value in [("up", int(w.get("healthy", False))), ("active", w.get("active", 0)),
                                          ("queued", w.get("queued", 0)), ("kv_reserved", w.get("kv_reserved", 0)),
                                          ("generated_tokens", w.get("counters", {}).get("tokens", 0))]:
                        lines.append("tokenflow_worker_" + metric + label + " " + str(value))
                content = ("\n".join(lines) + "\n").encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; version=0.0.4")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                return self.wfile.write(content)
            if self.path.startswith("/api/results/"):
                try:
                    rid = safe_id(self.path.rsplit("/", 1)[1])
                    result = json.loads((RUNS / rid / "result.json").read_text(encoding="utf-8"))
                    return self.reply(result)
                except (OSError, ValueError):
                    return self.reply({"error": "result not found"}, 404)
            assets = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
                      "/chat.js": ("chat.js", "text/javascript"),
                      "/execution.js": ("execution.js", "text/javascript"),
                      "/execution.css": ("execution.css", "text/css"),
                      "/style.css": ("style.css", "text/css")}
            if self.path not in assets:
                return self.reply({"error": "not found"}, 404)
            name, mime = assets[self.path]
            content = (ROOT / "ui" / "tokenflow" / name).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mime + "; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def do_POST(self):
            try:
                data = self.body()
                if self.path == "/api/shutdown":
                    self.reply({"stopping": True})
                    threading.Thread(target=server.shutdown, daemon=True).start()
                    return
                if self.path == "/api/configure":
                    return self.reply(gateway.configure(data))
                if self.path == "/api/run":
                    return self.reply(controller.start(data), 202)
                if self.path == "/api/cancel":
                    return self.reply({"cancelled": gateway.cancel(safe_id(data["request_id"]))})
                if self.path == "/api/worker":
                    wid = data["worker"]
                    if wid not in pool.urls or data["action"] not in {"start", "stop"}:
                        raise ValueError("invalid worker action")
                    with gateway.lock:
                        if gateway.active_run and gateway.active_run["status"] == "running":
                            raise RuntimeError("use the fault experiment while a run is active")
                    getattr(pool, data["action"])(wid)
                    return self.reply({"worker": wid, "action": data["action"]})
                if self.path != "/api/generate":
                    return self.reply({"error": "not found"}, 404)
                data.setdefault("request_id", "req-" + uuid.uuid4().hex[:12])
                parsed = validate_request(data)
                record = gateway.assign(parsed)
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                return self.reply({"error": str(exc)}, 400)
            except AdmissionError as exc:
                return self.reply({"error": exc.code, "code": exc.code, "client": exc.tenant,
                                   "retry_after_s": exc.retry_after}, 429, {"Retry-After": exc.retry_after})
            except RuntimeError as exc:
                return self.reply({"error": str(exc)}, 409)
            except urllib.error.HTTPError as exc:
                return self.reply({"error": exc.read().decode()}, 400 if exc.code == 400 else 503)
            except OSError as exc:
                return self.reply({"error": str(exc)}, 503)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            generator = gateway.stream(record)
            try:
                self.wfile.write(("data: " + json.dumps({"event": "assigned", "request_id": record["request_id"], "worker": record["worker"], "model": record["model"]}) + "\n\n").encode())
                self.wfile.flush()
                for event in generator:
                    self.wfile.write(("data: " + json.dumps(event, ensure_ascii=False) + "\n\n").encode())
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            finally:
                generator.close()
                # Closing a generator before its first next() does not run its finally.
                with gateway.lock:
                    if record["status"] not in TERMINAL:
                        record["status"] = "cancelled"
                        record["finished"] = now()
                        gateway.event(record, "cancelled", worker=record["worker"], tokens=record["tokens"], reason="downstream disconnected before worker stream")

    server = None
    try:
        # Bind before loading replicas. A bind or subprocess-launch failure
        # must pass through the same cleanup as an orderly service shutdown.
        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        for wid in pool.urls:
            pool.start(wid)
        print(f"TokenFlow: http://127.0.0.1:{port} | backend={backend} | workers={worker_count}", flush=True)
        server.serve_forever(poll_interval=0.2)
    finally:
        controller.cancel.set()
        gateway.stop_event.set()
        if server is not None:
            server.server_close()
        pool.close()
