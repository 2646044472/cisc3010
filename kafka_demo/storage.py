"""Durable application effects and audit evidence, separate from Kafka offsets."""
from __future__ import annotations

import csv
import json
import sqlite3
import time
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE expected(event_id TEXT PRIMARY KEY, payload TEXT NOT NULL,
 partition_id INTEGER NOT NULL, kafka_offset INTEGER, delivered INTEGER DEFAULT 0);
CREATE TABLE attempts(id INTEGER PRIMARY KEY, event_id TEXT NOT NULL,
 consumer_id TEXT NOT NULL, partition_id INTEGER NOT NULL, kafka_offset INTEGER NOT NULL,
 received_at REAL NOT NULL, applied_at REAL, committed_at REAL);
CREATE TABLE effects(id INTEGER PRIMARY KEY, event_id TEXT NOT NULL,
 consumer_id TEXT NOT NULL, usage_units INTEGER NOT NULL, created_at REAL NOT NULL);
CREATE TABLE dedup_keys(event_id TEXT PRIMARY KEY);
CREATE TABLE faults(event_id TEXT PRIMARY KEY, consumer_id TEXT, point TEXT, created_at REAL);
CREATE TABLE timeline(id INTEGER PRIMARY KEY, ts REAL NOT NULL,
 kind TEXT NOT NULL, consumer_id TEXT, detail TEXT NOT NULL);
CREATE TABLE workers(consumer_id TEXT PRIMARY KEY, pid INTEGER,
 state TEXT, partitions TEXT, updated_at REAL);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    db = sqlite3.connect(str(path), timeout=20)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=20000")
    db.execute("PRAGMA synchronous=FULL")
    return db


@contextmanager
def open_db(path):
    db = connect(path)
    try:
        with db:
            yield db
    finally:
        db.close()


def initialize(path: Path) -> None:
    with open_db(path) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript(SCHEMA)


def log(db, kind: str, consumer_id: str = "", **detail) -> None:
    with db:
        db.execute("INSERT INTO timeline(ts,kind,consumer_id,detail) VALUES(?,?,?,?)",
                   (time.monotonic(), kind, consumer_id, json.dumps(detail, ensure_ascii=False)))


def worker_state(db, consumer_id: str, pid: int, state: str, partitions: list[int]) -> None:
    with db:
        db.execute("INSERT INTO workers VALUES(?,?,?,?,?) ON CONFLICT(consumer_id) "
                   "DO UPDATE SET pid=excluded.pid,state=excluded.state,"
                   "partitions=excluded.partitions,updated_at=excluded.updated_at",
                   (consumer_id, pid, state, json.dumps(partitions), time.monotonic()))


def begin_attempt(db, event_id, consumer_id, partition, offset) -> int:
    with db:
        cur = db.execute("INSERT INTO attempts(event_id,consumer_id,partition_id,kafka_offset,received_at) "
                         "VALUES(?,?,?,?,?)", (event_id, consumer_id, partition, offset, time.monotonic()))
        return cur.lastrowid


def apply_effect(db, event: dict, consumer_id: str, attempt_id: int, idempotent: bool) -> bool:
    """Dedup marker and effect share one SQLite transaction; no check-then-write race."""
    now = time.monotonic()
    with db:
        apply = True
        if idempotent:
            apply = db.execute("INSERT OR IGNORE INTO dedup_keys VALUES(?)",
                               (event["event_id"],)).rowcount == 1
        if apply:
            db.execute("INSERT INTO effects(event_id,consumer_id,usage_units,created_at) VALUES(?,?,?,?)",
                       (event["event_id"], consumer_id,
                        event["input_tokens"] + event["output_tokens"], now))
        db.execute("UPDATE attempts SET applied_at=? WHERE id=?", (now, attempt_id))
    return apply


def mark_committed(db, attempt_id: int) -> None:
    with db:
        db.execute("UPDATE attempts SET committed_at=? WHERE id=?", (time.monotonic(), attempt_id))


def claim_fault(db, event_id: str, consumer_id: str, point: str) -> bool:
    """One durable fault per run, including across consumer restarts."""
    with db:
        return db.execute("INSERT OR IGNORE INTO faults VALUES(?,?,?,?)",
                          (event_id, consumer_id, point, time.monotonic())).rowcount == 1


def counts(db) -> dict:
    return {
        "expected": db.execute("SELECT COUNT(*) FROM expected").fetchone()[0],
        "produced": db.execute("SELECT COUNT(*) FROM expected WHERE delivered=1").fetchone()[0],
        "attempts": db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0],
        "committed": db.execute("SELECT COUNT(DISTINCT event_id) FROM attempts WHERE committed_at IS NOT NULL").fetchone()[0],
        "effects": db.execute("SELECT COUNT(*) FROM effects").fetchone()[0],
        "unique_effects": db.execute("SELECT COUNT(DISTINCT event_id) FROM effects").fetchone()[0],
    }


def check(db) -> dict:
    expected = {r["event_id"]: json.loads(r["payload"]) for r in db.execute("SELECT * FROM expected")}
    effect_rows = list(db.execute("SELECT * FROM effects"))
    effect_counts = Counter(r["event_id"] for r in effect_rows)
    attempt_counts = Counter(r["event_id"] for r in db.execute("SELECT event_id FROM attempts"))
    missing = sorted(set(expected) - set(effect_counts))
    unexpected = sorted(set(effect_counts) - set(expected))
    duplicates = {k: n for k, n in effect_counts.items() if n > 1}
    replays = {k: n for k, n in attempt_counts.items() if n > 1}
    invalid = [r["id"] for r in effect_rows if r["event_id"] in expected and
               r["usage_units"] != expected[r["event_id"]]["input_tokens"] + expected[r["event_id"]]["output_tokens"]]
    delivered = counts(db)["produced"]
    return {
        "expected": len(expected), "produced": delivered,
        "missing_ids": missing, "unexpected_ids": unexpected,
        "duplicate_effects": duplicates, "replayed_ids": replays,
        "invalid_effect_rows": invalid,
        "expected_usage_units": sum(e["input_tokens"] + e["output_tokens"] for e in expected.values()),
        "actual_usage_units": sum(r["usage_units"] for r in effect_rows),
        "data_correct": not (missing or unexpected or duplicates or invalid) and delivered == len(expected),
    }


def verify_scenario(report: dict, scenario: str, fault_count: int) -> bool:
    clean = not report["unexpected_ids"] and not report["invalid_effect_rows"]
    complete_publish = report["produced"] == report["expected"]
    if scenario == "baseline":
        return report["data_correct"] and fault_count == 0
    if scenario == "loss":
        return clean and complete_publish and fault_count == 1 and bool(report["missing_ids"]) and not report["duplicate_effects"]
    if scenario == "replay":
        return clean and complete_publish and fault_count == 1 and not report["missing_ids"] and bool(report["duplicate_effects"]) and bool(report["replayed_ids"])
    if scenario == "idempotent":
        return report["data_correct"] and fault_count == 1 and bool(report["replayed_ids"])
    raise ValueError(f"Unknown scenario: {scenario}")


def snapshot(path: Path, limit: int = 36) -> dict:
    with open_db(path) as db:
        result = counts(db)
        result["workers"] = [{**dict(r), "partitions": json.loads(r["partitions"])}
                             for r in db.execute("SELECT * FROM workers ORDER BY consumer_id")]
        rows = list(db.execute("SELECT * FROM timeline ORDER BY id DESC LIMIT ?", (limit,)))
        result["timeline"] = [{**dict(r), "detail": json.loads(r["detail"])} for r in reversed(rows)]
        result["recent_attempts"] = [dict(r) for r in db.execute("SELECT * FROM attempts ORDER BY id DESC LIMIT 16")]
        result["checker"] = check(db)
        return result


def export(path: Path, directory: Path) -> None:
    with open_db(path) as db:
        for table in ("attempts", "effects", "expected", "workers", "faults"):
            cur = db.execute(f"SELECT * FROM {table} ORDER BY rowid")
            with (directory / f"{table}.csv").open("w", newline="", encoding="utf-8") as out:
                writer = csv.writer(out)
                writer.writerow([column[0] for column in cur.description])
                writer.writerows(cur)
        with (directory / "timeline.jsonl").open("w", encoding="utf-8") as out:
            for row in db.execute("SELECT * FROM timeline ORDER BY id"):
                item = dict(row)
                item["detail"] = json.loads(item["detail"])
                out.write(json.dumps(item, ensure_ascii=False) + "\n")
