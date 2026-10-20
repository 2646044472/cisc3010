from __future__ import annotations

import collections
import json
from pathlib import Path
from .common import TERMINAL, read_events, token_for


def check_run(folder):
    folder = Path(folder)
    manifest = json.loads((folder / "workload.json").read_text(encoding="utf-8"))
    config = json.loads((folder / "config.json").read_text(encoding="utf-8"))
    rows = json.loads((folder / "requests.json").read_text(encoding="utf-8"))
    gateway = read_events(folder / "gateway.jsonl")
    workers = read_events(folder / "worker-1.jsonl") + read_events(folder / "worker-2.jsonl")
    errors = []
    ids = [item["request_id"] for item in rows]
    expected_ids = {item["request_id"] for item in manifest}
    if len(ids) != len(set(ids)) or set(ids) != expected_ids:
        errors.append("client results do not match workload IDs exactly")
    by_gateway = collections.defaultdict(list)
    by_worker = collections.defaultdict(list)
    for e in gateway:
        by_gateway[e["request_id"]].append(e)
    for e in workers:
        by_worker[e["request_id"]].append(e)
    settings = config.get("settings", {})
    if config.get("backend") == "cpu-model" and "execution" in settings:
        iterations = read_events(folder / "worker-1-iterations.jsonl") + read_events(folder / "worker-2-iterations.jsonl")
        processed = collections.Counter()
        real_inputs = {e["request_id"]: e["input_tokens"] for e in workers if e["event"] == "queued"}
        for event in sorted(iterations, key=lambda e: e["t"]):
            members, sizes = event.get("request_ids", []), event.get("piece_tokens", [])
            if not members or len(members) != len(set(members)) or len(sizes) != len(members):
                errors.append("invalid execution batch membership")
                continue
            prefill = 0
            for rid, size in zip(members, sizes):
                if rid not in real_inputs or type(size) is not int or size <= 0:
                    errors.append("invalid execution piece")
                    continue
                remaining = max(0, real_inputs[rid] - processed[rid])
                if remaining:
                    prefill += size
                    if size > remaining:
                        errors.append(rid + ": prefill piece crosses prompt boundary")
                elif size != 1:
                    errors.append(rid + ": decode must process one token")
                processed[rid] += size
            if prefill != event.get("prefill_tokens"):
                errors.append("execution prefill accounting differs from pieces")
            if settings.get("chunked_prefill") and prefill > settings["prefill_chunk"]:
                errors.append("iteration exceeds shared prefill allowance")
            if event.get("execution") != settings["execution"]:
                errors.append("execution policy differs from experiment contract")
        for row in rows:
            rid = row["request_id"]
            if row["status"] == "completed" and processed[rid] != real_inputs.get(rid, 0) + row["tokens"] - 1:
                errors.append(rid + ": execution token accounting differs from output trace")
    inputs = {item["request_id"]: item for item in manifest}
    for row in rows:
        rid = row["request_id"]
        if rid not in inputs:
            continue
        request = inputs[rid]
        seqs = row["sequences"]
        if seqs != list(range(len(seqs))):
            errors.append(rid + ": streamed tokens are missing, duplicated, or unordered")
        if len(seqs) > request["max_tokens"]:
            errors.append(rid + ": output exceeds requested limit")
        ge = by_gateway[rid]
        assignments = [e for e in ge if e["event"] == "assigned"]
        terminal = [e for e in ge if e["event"] in TERMINAL]
        if row["status"] == "rejected":
            if assignments:
                errors.append(rid + ": rejected client has a worker assignment")
            if by_worker[rid]:
                errors.append(rid + ": rejected request reached a worker")
            continue
        if len(assignments) != 1 or len(terminal) != 1:
            errors.append(rid + ": expected one assignment and one gateway terminal event")
        elif terminal[0]["event"] != row["status"]:
            errors.append(rid + ": client/gateway outcome mismatch")
        we = by_worker[rid]
        if len({e["worker"] for e in we}) > 1:
            errors.append(rid + ": executed on multiple workers")
        if row["status"] == "completed":
            wt = [e for e in we if e["event"] in TERMINAL]
            tokens = [e for e in we if e["event"] == "token"]
            if len(wt) != 1 or wt[0]["event"] != "completed":
                errors.append(rid + ": missing worker completion evidence")
            if [e["seq"] for e in tokens] != seqs:
                errors.append(rid + ": worker/client token mismatch")
            if config["backend"] == "simulator":
                reference = "".join(token_for(request["prompt"], i) for i in range(request["max_tokens"]))
                if row["text"] != reference or len(seqs) != request["max_tokens"]:
                    errors.append(rid + ": simulator output differs from independent reference")
            elif not tokens or tokens[-1]["seq"] != len(seqs) - 1:
                errors.append(rid + ": invalid model token trace")
        # Worker-local timings do not require cross-process clock subtraction.
        queued = [e for e in we if e["event"] == "queued"]
        started = [e for e in we if e["event"] == "started"]
        if queued and started and started[0]["t"] < queued[0]["t"]:
            errors.append(rid + ": worker started before queue admission")
    plans = config.get("admission_plans", {})
    active = {}
    for e in sorted(gateway, key=lambda item: item.get("t", 0)):
        rid = e["request_id"]
        if e["event"] == "assigned" and e.get("tenant") in plans and "reservation" in e:
            active[rid] = (e["tenant"], e["reservation"])
            tenant = e["tenant"]
            held = [reservation for client, reservation in active.values() if client == tenant]
            if len(held) > plans[tenant]["inflight"] or sum(held) > plans[tenant]["token_budget"]:
                errors.append(rid + ": client admission contract exceeded")
        elif e["event"] in TERMINAL:
            active.pop(rid, None)
    if active:
        errors.append("admission trace still contains outstanding reservations")
    cleanup = json.loads((folder / "cleanup.json").read_text(encoding="utf-8"))
    if cleanup["outstanding"] != 0:
        errors.append("gateway outstanding requests leaked")
    for client in cleanup.get("admission", {}).get("clients", []):
        if client["active"] or client["reserved_tokens"]:
            errors.append(client["client"] + ": client admission reservations leaked")
    for worker in cleanup["workers"]:
        if worker.get("healthy") and (worker.get("active", 0) or worker.get("queued", 0) or worker.get("kv_reserved", 0)):
            errors.append(worker["id"] + ": worker request/KV reservations leaked")
    counts = collections.Counter(row["status"] for row in rows)
    return {"passed": not errors, "errors": errors, "request_count": len(rows),
            "outcomes": dict(counts), "all_completed": counts.get("completed", 0) == len(manifest)}
