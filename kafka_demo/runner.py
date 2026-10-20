from __future__ import annotations

import csv
import json
import os
import platform
import random
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from confluent_kafka import Producer, libversion, version
from confluent_kafka.admin import AdminClient, NewTopic
from . import storage

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ("baseline", "loss", "replay", "idempotent")


@dataclass
class Config:
    scenario: str = "idempotent"
    events: int = 120
    consumers: int = 2
    partitions: int = 4
    processing_ms: int = 15
    seed: int = 3010
    bootstrap: str = "localhost:19092"
    timeout: int = 90

    def validate(self):
        if self.scenario not in SCENARIOS:
            raise ValueError("Unknown scenario")
        for name, low, high in (("events", 8, 5000), ("consumers", 1, 8),
                                ("partitions", 1, 16), ("processing_ms", 0, 1000), ("timeout", 10, 600)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise ValueError(f"{name} must be an integer in [{low}, {high}]")


def make_events(count: int, seed: int, run_id: str) -> list[dict]:
    rng = random.Random(seed)
    # Synthetic inference telemetry, not a claim of actual model inference.
    return [{"event_id": f"{run_id}-{i:05d}", "sequence": i,
             "model": ("small-chat", "text-classifier", "embedding")[i % 3],
             "input_tokens": rng.randint(20, 160), "output_tokens": rng.randint(5, 100),
             "latency_ms": rng.randint(80, 900), "synthetic": True}
            for i in range(count)]


def broker_ready(bootstrap: str, timeout: float = 8) -> dict:
    admin = AdminClient({"bootstrap.servers": bootstrap, "broker.address.family": "v4", "socket.timeout.ms": int(timeout * 1000),
                         "log_level": 0})
    meta = admin.list_topics(timeout=timeout)
    if not meta.brokers:
        raise RuntimeError("Kafka returned no brokers")
    return {"cluster_id": meta.cluster_id, "brokers": [str(b) for b in meta.brokers.values()]}


def write_json(path: Path, obj: dict) -> None:
    # Replace atomically so dashboard readers never observe half a JSON document.
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


class Run:
    def __init__(self, config: Config, output_root: Path | None = None):
        config.validate()
        self.config = config
        self.run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
        self.directory = (output_root or ROOT / "runs") / self.run_id
        self.directory.mkdir(parents=True, exist_ok=False)
        self.db_path = self.directory / "audit.sqlite3"
        self.state = "preparing"
        self.error = ""
        self.result = None
        self.cancel = threading.Event()
        self.children = []
        self.logs = []
        self.manifest = {**asdict(config), "run_id": self.run_id,
                         "topic": f"cisc3010-{self.run_id}".lower(),
                         "group": f"cisc3010-{self.run_id}".lower(),
                         "fault_event_id": f"{self.run_id}-00000",
                         "started_at": datetime.now(timezone.utc).isoformat(),
                         "start_monotonic": time.monotonic(), "python": platform.python_version(),
                         "platform": platform.platform(), "logical_cpus": os.cpu_count(),
                         "client_version": version()[0], "librdkafka_version": libversion()[0],
                         "event_source": "synthetic inference telemetry",
                         "resource_note": "One local broker; consumers share host CPU and one SQLite sink",
                         "arrival_model": "pre-generated finite burst; producer delivery included in workload elapsed time"}
        storage.initialize(self.db_path)
        events = make_events(config.events, config.seed, self.run_id)
        with storage.open_db(self.db_path) as db:
            db.executemany("INSERT INTO expected(event_id,payload,partition_id) VALUES(?,?,?)",
                           [(e["event_id"], json.dumps(e), e["sequence"] % config.partitions) for e in events])
        with (self.directory / "input.jsonl").open("w", encoding="utf-8") as out:
            for event in events:
                out.write(json.dumps(event) + "\n")
        write_json(self.directory / "manifest.json", self.manifest)

    def spawn(self, name: str):
        if self.cancel.is_set():
            raise InterruptedError("Run cancelled")
        out = (self.directory / f"{name}.log").open("w", encoding="utf-8")
        child = subprocess.Popen([sys.executable, "-m", "kafka_demo.consumer", "--run-dir", str(self.directory),
                                  "--consumer-id", name], cwd=ROOT, stdout=out, stderr=subprocess.STDOUT)
        self.logs.append(out)
        self.children.append({"name": name, "process": child, "handled": False})

    def start(self):
        thread = threading.Thread(target=self.execute, name=f"run-{self.run_id}", daemon=True)
        thread.start()
        return thread

    def execute(self):
        workload_start = None
        try:
            self.manifest["broker"] = broker_ready(self.config.bootstrap)
            admin = AdminClient({"bootstrap.servers": self.config.bootstrap, "broker.address.family": "v4"})
            topic = NewTopic(self.manifest["topic"], num_partitions=self.config.partitions, replication_factor=1,
                             config={"retention.ms": "86400000"})
            for future in admin.create_topics([topic]).values():
                future.result(timeout=15)
            meta = admin.list_topics(self.manifest["topic"], timeout=10)
            if meta.topics[self.manifest["topic"]].error:
                raise RuntimeError(str(meta.topics[self.manifest["topic"]].error))
            write_json(self.directory / "manifest.json", self.manifest)
            for i in range(self.config.consumers):
                self.spawn(f"consumer-{i + 1}")
            self.state = "joining"
            deadline = time.monotonic() + min(30, self.config.timeout)
            # Empty assignment is valid when consumers outnumber partitions.
            while time.monotonic() < deadline:
                if self.cancel.is_set():
                    raise InterruptedError("Run cancelled")
                if any(c["process"].poll() is not None for c in self.children):
                    raise RuntimeError("A consumer failed while joining; see its log")
                with storage.open_db(self.db_path) as db:
                    states = list(db.execute("SELECT * FROM workers"))
                owners = [p for r in states for p in json.loads(r["partitions"])]
                stable = states and time.monotonic() - max(r["updated_at"] for r in states) >= 0.4
                if (len(states) == self.config.consumers and all(r["state"] in ("active", "idle") for r in states)
                        and sorted(owners) == list(range(self.config.partitions)) and stable):
                    break
                time.sleep(0.1)
            else:
                raise TimeoutError("Consumers did not join within 30 seconds")
            self.state = "running"
            workload_start = time.monotonic()
            with storage.open_db(self.db_path) as db:
                storage.log(db, "workload_started", events=self.config.events)
            self.produce()
            deadline = workload_start + self.config.timeout
            while time.monotonic() < deadline:
                if self.cancel.is_set():
                    raise InterruptedError("Run cancelled")
                for child in list(self.children):
                    code = child["process"].poll()
                    if code is None or child["handled"]:
                        continue
                    child["handled"] = True
                    if code == 86:
                        # Restore the configured number of peers; membership ID/PID changes.
                        with storage.open_db(self.db_path) as db:
                            storage.log(db, "restarting", child["name"], exit_code=code)
                        self.spawn(child["name"] + "-restart")
                    else:
                        raise RuntimeError(f"{child['name']} exited unexpectedly ({code}); inspect its log")
                with storage.open_db(self.db_path) as db:
                    current = storage.counts(db)
                if current["committed"] == self.config.events:
                    break
                time.sleep(0.1)
            else:
                raise TimeoutError(f"Workload did not finish in {self.config.timeout}s")
            elapsed = time.monotonic() - workload_start
            with storage.open_db(self.db_path) as db:
                report = storage.check(db)
                fault_count = db.execute("SELECT COUNT(*) FROM faults").fetchone()[0]
                recovery = None
                fault = db.execute("SELECT * FROM faults ORDER BY created_at LIMIT 1").fetchone()
                if fault:
                    partition = db.execute("SELECT partition_id FROM expected WHERE event_id=?", (fault["event_id"],)).fetchone()[0]
                    received = db.execute("SELECT MIN(received_at) FROM attempts WHERE partition_id=? AND received_at>?",
                                          (partition, fault["created_at"])).fetchone()[0]
                    recovery = received - fault["created_at"] if received else None
                self.result = {**report, "run_id": self.run_id, "scenario": self.config.scenario,
                               "consumers": self.config.consumers, "partitions": self.config.partitions,
                               "events": self.config.events, "seed": self.config.seed,
                               "processing_ms": self.config.processing_ms, "elapsed_s": elapsed,
                               "unique_effects_per_s": current["unique_effects"] / elapsed,
                               "committed_events_per_s": current["committed"] / elapsed,
                               "recovery_to_processing_s": recovery, "fault_count": fault_count,
                               "scenario_verified": storage.verify_scenario(report, self.config.scenario, fault_count)}
                storage.log(db, "finished", scenario_verified=self.result["scenario_verified"])
            write_json(self.directory / "result.json", self.result)
            self.state = "finished" if self.result["scenario_verified"] else "failed"
            if self.state == "failed":
                self.error = "Observed result did not match this scenario's expected behavior"
        except Exception as exc:
            self.state = "cancelled" if isinstance(exc, InterruptedError) else "failed"
            self.error = str(exc)
            write_json(self.directory / "error.json", {"error": self.error, "state": self.state})
            with storage.open_db(self.db_path) as db:
                storage.log(db, "run_error", error=self.error)
        finally:
            self.stop_children()
            storage.export(self.db_path, self.directory)

    def produce(self):
        producer = Producer({"bootstrap.servers": self.config.bootstrap, "broker.address.family": "v4", "enable.idempotence": True,
                             "client.id": "demo-producer", "message.timeout.ms": 15000})
        errors = []
        db = storage.connect(self.db_path)
        try:
            def delivered(err, message):
                if err:
                    errors.append(str(err))
                else:
                    with db:
                        db.execute("UPDATE expected SET delivered=1,kafka_offset=? WHERE event_id=?",
                                   (message.offset(), message.key().decode()))
            for line in (self.directory / "input.jsonl").read_text(encoding="utf-8").splitlines():
                if self.cancel.is_set():
                    raise InterruptedError("Run cancelled")
                event = json.loads(line)
                producer.produce(self.manifest["topic"], key=event["event_id"], value=line,
                                 partition=event["sequence"] % self.config.partitions, on_delivery=delivered)
                producer.poll(0)
            remaining = producer.flush(20)
            if remaining or errors:
                raise RuntimeError(f"Producer failed: remaining={remaining}, errors={errors[:3]}")
        finally:
            db.close()

    def stop_children(self):
        (self.directory / "STOP").touch()
        deadline = time.monotonic() + 10
        for child in self.children:
            proc = child["process"]
            try:
                proc.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=3)
        for out in self.logs:
            out.close()

    def snapshot(self):
        return {"run_id": self.run_id, "state": self.state, "error": self.error,
                "manifest": self.manifest, "result": self.result,
                "elapsed_s": time.monotonic() - self.manifest["start_monotonic"],
                **storage.snapshot(self.db_path)}


def experiment(counts: list[int], repeats: int, events: int, processing_ms: int, bootstrap: str):
    directory = ROOT / "runs" / ("experiment-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6])
    directory.mkdir(parents=True)
    write_json(directory / "config.json", {"consumer_counts": counts, "repeats": repeats, "events": events,
               "processing_ms": processing_ms, "partitions": 4, "seed": 3010,
               "measurement": "finite burst through final commit; startup excluded; same host and SQLite sink",
               "note": "Synthetic per-event sleep models application work; these are not Kafka capacity results"})
    warmup = Run(Config(scenario="baseline", consumers=2, events=8, processing_ms=0, bootstrap=bootstrap), directory)
    warmup.execute()
    if warmup.state != "finished":
        raise RuntimeError(f"Warmup failed: {warmup.error}")
    write_json(directory / "warmup.json", {"run_id": warmup.run_id, "excluded_from_results": True})
    rows = []
    # Counterbalance order to reduce systematic warm-machine/time drift.
    for repeat in range(repeats):
        order = counts if repeat % 2 == 0 else list(reversed(counts))
        for count in order:
            run = Run(Config(scenario="baseline", consumers=count, events=events,
                             processing_ms=processing_ms, bootstrap=bootstrap), directory)
            run.execute()
            if run.state != "finished":
                raise RuntimeError(f"Experiment failed in {run.directory}: {run.error}")
            row = {"repeat": repeat + 1, "consumers": count, "run_id": run.run_id,
                   "elapsed_s": run.result["elapsed_s"], "unique_effects_per_s": run.result["unique_effects_per_s"],
                   "data_correct": run.result["data_correct"]}
            rows.append(row)
            with (directory / "results.csv").open("w", newline="", encoding="utf-8") as out:
                writer = csv.DictWriter(out, fieldnames=list(row))
                writer.writeheader()
                writer.writerows(rows)
            print(json.dumps(row), flush=True)
    return directory
