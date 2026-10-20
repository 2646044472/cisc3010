from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from confluent_kafka import Consumer, KafkaException
from . import storage


def consume(args) -> int:
    directory = Path(args.run_dir)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    db = storage.connect(directory / "audit.sqlite3")
    name = args.consumer_id
    pid = os.getpid()
    assigned = []
    storage.worker_state(db, name, pid, "joining", [])
    storage.log(db, "started", name, pid=pid)
    client = Consumer({
        "bootstrap.servers": manifest["bootstrap"], "broker.address.family": "v4", "group.id": manifest["group"],
        "client.id": name, "group.protocol": "classic", "partition.assignment.strategy": "range",
        "auto.offset.reset": "earliest", "enable.auto.commit": False, "enable.auto.offset.store": False,
        "session.timeout.ms": 6000, "heartbeat.interval.ms": 1500, "max.poll.interval.ms": 300000,
    })

    def on_assign(consumer, partitions):
        assigned[:] = [p.partition for p in partitions]
        storage.log(db, "assigned", name, partitions=assigned.copy())
        storage.worker_state(db, name, pid, "active" if assigned else "idle", assigned)
        consumer.assign(partitions)

    def on_revoke(consumer, partitions):
        storage.log(db, "revoked", name, partitions=[p.partition for p in partitions])
        assigned.clear()
        storage.worker_state(db, name, pid, "rebalancing", [])
        consumer.unassign()

    def crash(event, point):
        if event["event_id"] != manifest["fault_event_id"]:
            return
        if storage.claim_fault(db, event["event_id"], name, point):
            storage.log(db, "crashed", name, event_id=event["event_id"], point=point, pid=pid)
            storage.worker_state(db, name, pid, "crashed", assigned)
            # Intentionally bypass close/finally: this is an abrupt process failure.
            os._exit(86)

    try:
        client.subscribe([manifest["topic"]], on_assign=on_assign, on_revoke=on_revoke)
        while not (directory / "STOP").exists():
            message = client.poll(0.15)
            if message is None:
                continue
            if message.error():
                raise KafkaException(message.error())
            event = json.loads(message.value())
            attempt = storage.begin_attempt(db, event["event_id"], name, message.partition(), message.offset())
            time.sleep(manifest["processing_ms"] / 1000)
            scenario = manifest["scenario"]
            if scenario == "loss":
                client.commit(message=message, asynchronous=False)
                storage.mark_committed(db, attempt)
                crash(event, "after_commit_before_effect")
            applied = storage.apply_effect(db, event, name, attempt, scenario == "idempotent")
            if not applied:
                storage.log(db, "deduplicated", name, event_id=event["event_id"], partition=message.partition(), offset=message.offset())
            if scenario in ("replay", "idempotent"):
                crash(event, "after_effect_before_commit")
            if scenario != "loss":
                client.commit(message=message, asynchronous=False)
                storage.mark_committed(db, attempt)
        return 0
    except Exception as exc:
        storage.log(db, "error", name, error=str(exc))
        print(f"{name}: {exc}", flush=True)
        return 1
    finally:
        client.close()
        storage.worker_state(db, name, pid, "stopped", [])
        storage.log(db, "stopped", name)
        db.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--consumer-id", required=True)
    return consume(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
