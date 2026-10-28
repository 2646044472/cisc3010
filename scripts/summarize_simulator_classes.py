"""Check one simulator suite and report short/long waiting times by trial."""
from __future__ import annotations

import argparse
import collections
import csv
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from llm_lab.check import check_run
from llm_lab.experiment import percentile


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def summarize(suite, destination):
    results = read(suite / "results.json")
    if len(results) != 12:
        raise ValueError(f"Expected 12 simulator trials, got {len(results)}")
    groups = collections.defaultdict(list)
    shapes = {}
    contracts = {}
    for result in results:
        folder = suite.parent / result["run_id"]
        checked = check_run(folder)
        if not checked["passed"] or not checked["all_completed"]:
            raise ValueError(f"Invalid run {result['run_id']}: {checked['errors']}")
        config = read(folder / "config.json")
        if config["backend"] != "simulator" or result["count"] != 48:
            raise ValueError(f"Unexpected configuration in {result['run_id']}")
        rate = float(result["rate"])
        settings = {k: v for k, v in config["settings"].items() if k != "scheduling"}
        contract = json.dumps({"settings": settings, "service_cost": config["service_cost"],
                               "workers": config["environment"]["workers"]}, sort_keys=True)
        if rate in contracts and contracts[rate] != contract:
            raise ValueError(f"Service settings differ at {rate}/s")
        contracts[rate] = contract
        workload = read(folder / "workload.json")
        shape = [(x["prompt"], x["max_tokens"], x["class"], x["arrival_s"]) for x in workload]
        if rate in shapes and shapes[rate] != shape:
            raise ValueError(f"Workloads differ at {rate}/s")
        shapes[rate] = shape
        requests = read(folder / "requests.json")
        for kind in ("short", "long"):
            selected = [x for x in requests if x["class"] == kind]
            if not selected or any(x["status"] != "completed" for x in selected):
                raise ValueError(f"Missing {kind} completions in {result['run_id']}")
            groups[(rate, result["scheduling"], kind)].append({
                "count": len(selected),
                "queue_mean_ms": statistics.mean(x["queue_ms"] for x in selected),
                "queue_p95_ms": percentile([x["queue_ms"] for x in selected], .95),
                "ttft_p95_ms": percentile([x["ttft_ms"] for x in selected], .95),
            })
    rows = []
    for (rate, policy, kind), observations in sorted(groups.items()):
        if len(observations) != 3:
            raise ValueError("Expected three repeats per rate, policy and request class")
        row = {"arrival_rate": rate, "scheduling": policy, "class": kind,
               "repeats": len(observations), "requests_per_run": observations[0]["count"]}
        for key in ("queue_mean_ms", "queue_p95_ms", "ttft_p95_ms"):
            values = [x[key] for x in observations]
            row[key + "_mean"] = statistics.mean(values)
            row[key + "_sample_sd"] = statistics.stdev(values)
        rows.append(row)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({"passed": True, "trials": len(results), "requests": 48 * len(results),
                      "summary": str(destination)}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", type=Path, help="Extracted suite folder containing results.json")
    parser.add_argument("--output", type=Path, default=ROOT / "verification-output/simulator/class-summary.csv")
    args = parser.parse_args()
    summarize(args.suite, args.output)
