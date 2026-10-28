from __future__ import annotations

import collections
import dataclasses
import json
import os
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .backend import CpuModel, Simulator
from .common import JsonHandlerMixin, TERMINAL, Trace, now, validate_request, simulator_input


@dataclasses.dataclass
class Job:
    request_id: str
    prompt: str
    max_tokens: int
    run_id: str | None
    input_tokens: int
    messages: list | None = None
    tenant: str = "demo"
    created: float = dataclasses.field(default_factory=now)
    produced: int = 0
    status: str = "queued"
    remaining_prefill: int = 0
    cache_hit: int = 0
    cancel: bool = False
    output: queue.Queue = dataclasses.field(default_factory=lambda: queue.Queue(128))
    model_state: object = None

    @property
    def reservation(self):
        return self.input_tokens + self.max_tokens


class Engine:
    def __init__(self, worker_id, backend):
        self.worker_id = worker_id
        self.backend = backend
        self.lock = threading.RLock()
        self.pending = collections.deque()
        self.active = []
        self.jobs = {}
        self.seen = set()
        self.cache = collections.OrderedDict()
        self.trace = Trace(worker_id)
        self.iteration_trace = Trace(worker_id + "-iterations")
        self.timeline = collections.deque(maxlen=100)
        # Bounded observations for the execution inspector; no prompts or tensors.
        self.recent_iterations = collections.deque(maxlen=32)
        self.last_mixed_iteration = None
        self.config = {"scheduling": "continuous", "execution": "selective", "slots": 4, "kv_budget": 4096,
                       "chunked_prefill": True, "prefill_chunk": 128 if backend.name != "simulator" else 32,
                       "prefix_cache": False, "cache_budget": 512, "speed": 1.0}
        self.stop = threading.Event()
        self.counters = collections.Counter()
        self.thread = threading.Thread(target=self.loop, name="token-scheduler", daemon=True)
        self.thread.start()

    def event(self, job, kind, **fields):
        event = {"t": now(), "event": kind, "worker": self.worker_id,
                 "request_id": job.request_id, **fields}
        self.trace.write(job.run_id, event)
        if kind != "token":
            self.timeline.append(event)
        if kind in {"queued", "started", "prefill"}:
            try:
                job.output.put_nowait(event)
            except queue.Full:
                job.cancel = True
        return event

    def prefix(self, job):
        words = simulator_input(job.prompt, job.messages).split()
        return tuple(words[:32]) if len(words) >= 32 else ()

    def configure(self, data):
        with self.lock:
            if self.pending or self.active:
                raise RuntimeError("worker must be idle before configuration")
            cfg = self.config | data
            if cfg["scheduling"] not in {"static", "continuous"}:
                raise ValueError("invalid scheduling policy")
            if cfg["execution"] not in {"selective", "sequential"}:
                raise ValueError("invalid execution policy")
            for key, low, high in [("slots", 1, 16), ("kv_budget", 128, 65536),
                                   ("prefill_chunk", 1, 4096), ("cache_budget", 0, 8192)]:
                if isinstance(cfg[key], bool) or not isinstance(cfg[key], int) or not low <= cfg[key] <= high:
                    raise ValueError("invalid " + key)
            if type(cfg["prefix_cache"]) is not bool or type(cfg["chunked_prefill"]) is not bool:
                raise ValueError("cache and chunk settings must be boolean")
            if isinstance(cfg["speed"], bool) or not isinstance(cfg["speed"], (float, int)) or not 0.25 <= cfg["speed"] <= 10:
                raise ValueError("invalid worker speed")
            if self.backend.name != "simulator" and cfg["prefix_cache"]:
                raise ValueError("cross-request prefix cache is implemented only in the simulator")
            if set(data) - set(self.config):
                raise ValueError("unknown configuration field")
            self.config = cfg
            self.cache.clear()
            self.counters.clear()
            self.timeline.clear()
            self.recent_iterations.clear()
            self.last_mixed_iteration = None
            # Idle means every prior stream has a terminal event queued.
            self.jobs.clear()
            self.seen.clear()

    def submit(self, data):
        parsed = validate_request(data)
        count = self.backend.count(parsed["prompt"], parsed["messages"])
        job = Job(**parsed, input_tokens=count)
        with self.lock:
            if job.request_id in self.seen:
                raise ValueError("duplicate request ID")
            if job.reservation > self.config["kv_budget"]:
                raise ValueError("request exceeds worker KV token budget")
            if len(self.pending) >= 128:
                raise RuntimeError("worker queue full")
            self.seen.add(job.request_id)
            self.jobs[job.request_id] = job
            self.pending.append(job)
            self.event(job, "queued", input_tokens=count, max_tokens=job.max_tokens)
            self.counters["submitted"] += 1
        return job

    def cancel_job(self, request_id):
        with self.lock:
            job = self.jobs.get(request_id)
            if job and job.status not in TERMINAL:
                job.cancel = True
                return True
            return False

    def finish(self, job, outcome, reason=None):
        if job.status in TERMINAL:
            return
        job.status = outcome
        self.counters[outcome] += 1
        event = self.event(job, outcome, tokens=job.produced, reason=reason)
        # A slow/disconnected stream cannot hold scheduler resources indefinitely.
        try:
            job.output.put_nowait(event)
        except queue.Full:
            while not job.output.empty():
                job.output.get_nowait()
            job.output.put_nowait(event)
        job.model_state = None
        self.jobs.pop(job.request_id, None)

    def snapshot(self):
        with self.lock:
            requests = [{"request_id": j.request_id, "status": j.status, "tokens": j.produced,
                         "max_tokens": j.max_tokens, "input_tokens": j.input_tokens,
                         "prefill_remaining": j.remaining_prefill, "cache_hit": j.cache_hit,
                         "age_ms": round((now() - j.created) * 1000)}
                        for j in list(self.active) + list(self.pending)[:16]]
            return {"id": self.worker_id, "pid": os.getpid(), "healthy": self.thread.is_alive(),
                    "cpu_process_s": time.process_time(),
                    "backend": self.backend.name, "model": self.backend.model_id,
                    "revision": self.backend.revision, "dtype": getattr(self.backend, "dtype", None), "config": self.config.copy(),
                    "model_threads": getattr(self.backend, "threads", None),
                    "queued": len(self.pending), "active": len(self.active),
                    "kv_reserved": sum(j.reservation for j in self.active),
                    "kv_used": sum(j.input_tokens - j.remaining_prefill + max(0, j.produced - 1)
                                   if self.backend.name != "simulator" else j.input_tokens + j.produced
                                   for j in self.active),
                    "kv_payload_bytes": sum(
                        tensor.numel() * tensor.element_size()
                        for j in self.active if j.model_state and self.backend.name != "simulator"
                        for layer in j.model_state["cache"].layers
                        for tensor in (getattr(layer, "keys", None), getattr(layer, "values", None))
                        if tensor is not None),
                    "cache_tokens": sum(self.cache.values()),
                    "cache_keys": [" ".join(k) for k in self.cache],
                    "execution": self.config["execution"] if self.backend.name != "simulator" else "simulated",
                    "counters": dict(self.counters), "requests": requests,
                    "timeline": list(self.timeline),
                    "recent_iterations": list(self.recent_iterations),
                    "last_mixed_iteration": self.last_mixed_iteration}

    def admit(self):
        if self.config["scheduling"] == "static" and self.active:
            return
        while self.pending and len(self.active) < self.config["slots"]:
            job = self.pending[0]
            if sum(j.reservation for j in self.active) + job.reservation > self.config["kv_budget"]:
                break  # FIFO: intentionally no bypass of a large queued request.
            self.pending.popleft()
            job.status = "active"
            key = self.prefix(job)
            hit = self.cache.get(key, 0) if self.config["prefix_cache"] else 0
            if hit:
                self.cache.move_to_end(key)
            job.cache_hit = hit
            job.remaining_prefill = max(0, job.input_tokens - hit)
            self.backend.prepare(job)
            self.active.append(job)
            self.counters["cache_hit_tokens"] += hit
            self.event(job, "started", cache_hit=hit, reservation=job.reservation)

    def cache_prefix(self, job):
        key = self.prefix(job)
        if not self.config["prefix_cache"] or not key:
            return
        if len(key) > self.config["cache_budget"]:
            return
        self.cache[key] = len(key)
        self.cache.move_to_end(key)
        while sum(self.cache.values()) > self.config["cache_budget"]:
            self.cache.popitem(last=False)

    def deliver(self, job, result):
        """Called under the engine lock after a model iteration returns."""
        if job.cancel:
            return
        delta, eos, token_id = result
        text = None if self.backend.name == "simulator" else job.model_state["text"]
        event = self.event(job, "token", seq=job.produced, delta=delta, token_id=token_id, text=text)
        job.produced += 1
        self.counters["tokens"] += 1
        try:
            job.output.put_nowait(event)
        except queue.Full:
            self.finish(job, "failed", "slow reader exceeded output buffer")
        if job.status not in TERMINAL and (eos or job.produced >= job.max_tokens):
            self.finish(job, "completed", "eos" if eos else "length")
        if job.status in TERMINAL:
            self.active.remove(job)

    def real_iteration(self, batch, cfg):
        # Existing decode tokens always run. New prompts share ONE bounded
        # prefill allowance across the iteration, rather than one per slot.
        pieces = [(j, 1) for j in batch if not j.cancel and not j.remaining_prefill]
        budget = cfg["prefill_chunk"]
        prefills = []
        for job in batch:
            if job.cancel or not job.remaining_prefill:
                continue
            size = min(job.remaining_prefill, budget) if cfg["chunked_prefill"] else job.remaining_prefill
            if not size:
                break
            pieces.append((job, size))
            prefills.append((job, size))
            if cfg["chunked_prefill"]:
                budget -= size
        if not pieces:
            return
        started = now()
        results = self.backend.iterate(pieces, cfg["execution"])
        elapsed = (now() - started) * 1000
        with self.lock:
            self.counters["iterations"] += 1
            self.counters["max_batch_requests"] = max(self.counters["max_batch_requests"], len(pieces))
            self.counters["request_pieces"] += len(pieces)
            self.counters["prefill_tokens"] += sum(size for _, size in prefills)
            self.counters["compute_ms"] += elapsed
            self.counters["shared_iterations"] += int(cfg["execution"] == "selective" and len(pieces) > 1)
            observation = {"t": started, "event": "iteration", "worker": self.worker_id,
                "index": self.counters["iterations"], "execution": cfg["execution"],
                "request_ids": [j.request_id for j, _ in pieces],
                "piece_tokens": [size for _, size in pieces], "duration_ms": elapsed,
                "phases": ["prefill" if j.remaining_prefill else "decode" for j, _ in pieces],
                "prefill_tokens": sum(size for _, size in prefills),
                "prefill_budget": cfg["prefill_chunk"] if cfg["chunked_prefill"] else None}
            self.recent_iterations.append(observation)
            if "prefill" in observation["phases"] and "decode" in observation["phases"]:
                self.last_mixed_iteration = observation
            # The inspector uses the same observation as the saved trace.
            for run_id in {j.run_id for j, _ in pieces}:
                self.iteration_trace.write(run_id, observation)
            for job, size in prefills:
                job.remaining_prefill -= size
                if not job.cancel:
                    self.event(job, "prefill", chunk_tokens=size, remaining=job.remaining_prefill)
            for (job, _), result in zip(pieces, results):
                if result is not None:
                    self.deliver(job, result)

    def loop(self):
        while not self.stop.is_set():
            try:
                with self.lock:
                    for job in list(self.pending):
                        if job.cancel:
                            self.pending.remove(job)
                            self.finish(job, "cancelled")
                    for job in list(self.active):
                        if job.cancel:
                            self.finish(job, "cancelled")
                            self.active.remove(job)
                    self.admit()
                    batch = list(self.active)
                    cfg = self.config.copy()
                if not batch:
                    self.stop.wait(0.003)
                    continue
                if self.backend.name != "simulator":
                    self.real_iteration(batch, cfg)
                    continue
                ready = [j for j in batch if j.remaining_prefill == 0 and not j.cancel]
                if ready and self.backend.name == "simulator":
                    # One simulated batched step: base cost + marginal sequence cost.
                    self.stop.wait((0.012 + 0.002 * len(ready)) * cfg["speed"])
                for job in ready:
                    if job.cancel:
                        continue
                    delta, eos, token_id = self.backend.step(job)
                    with self.lock:
                        self.deliver(job, (delta, eos, token_id))
                # Decode has priority. Prefill chunks consume time and delay the next decode.
                for job in batch:
                    if job.remaining_prefill and not job.cancel:
                        amount = min(job.remaining_prefill, cfg["prefill_chunk"]) if cfg["chunked_prefill"] else job.remaining_prefill
                        self.stop.wait((0.003 + amount * 0.00025) * cfg["speed"])
                        with self.lock:
                            job.remaining_prefill -= amount
                            self.event(job, "prefill", chunk_tokens=amount, remaining=job.remaining_prefill)
                            if job.remaining_prefill == 0:
                                self.cache_prefix(job)
            except Exception as exc:
                with self.lock:
                    for job in list(self.active):
                        self.finish(job, "failed", str(exc))
                    self.active.clear()
        with self.lock:
            for job in list(self.active) + list(self.pending):
                self.finish(job, "cancelled", "worker shutdown")
            self.active.clear()
            self.pending.clear()


def serve_worker(port, worker_id, backend_name="simulator", model_path=None, threads=2):
    backend = Simulator() if backend_name == "simulator" else CpuModel(model_path, threads=threads)
    engine = Engine(worker_id, backend)

    class Handler(JsonHandlerMixin, BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/health":
                self.reply(engine.snapshot())
            else:
                self.reply({"error": "not found"}, 404)

        def do_POST(self):
            try:
                data = self.body()
                if self.path == "/configure":
                    engine.configure(data)
                    return self.reply(engine.snapshot())
                if self.path == "/cancel":
                    return self.reply({"cancelled": engine.cancel_job(data["request_id"])})
                if self.path != "/generate":
                    return self.reply({"error": "not found"}, 404)
                job = engine.submit(data)
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                return self.reply({"error": str(exc)}, 400)
            except RuntimeError as exc:
                return self.reply({"error": str(exc)}, 429)
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            try:
                while True:
                    event = job.output.get(timeout=120)
                    self.wfile.write((json.dumps(event) + "\n").encode())
                    self.wfile.flush()
                    if event["event"] in TERMINAL:
                        break
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, queue.Empty):
                engine.cancel_job(job.request_id)
            finally:
                with engine.lock:
                    if job.status in TERMINAL:
                        engine.jobs.pop(job.request_id, None)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        engine.stop.set()
        engine.thread.join(timeout=10)
        server.server_close()
