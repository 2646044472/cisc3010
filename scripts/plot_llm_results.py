"""Recheck raw run evidence and plot repeated trials with sample variation."""
import argparse
import csv
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from llm_lab.check import check_run
from llm_lab.experiment import percentile
from llm_lab.common import read_events

parser = argparse.ArgumentParser()
parser.add_argument("folder", type=Path)
args = parser.parse_args()
folder = args.folder
results = json.loads((folder / "results.json").read_text(encoding="utf-8"))
reference = None
reference_outputs = None
for result in results:
    source = folder.parent / result["run_id"]
    check = check_run(source)
    if not check["passed"] or not check["all_completed"]:
        raise RuntimeError("invalid raw evidence: " + result["run_id"])
    rows = json.loads((source / "requests.json").read_text(encoding="utf-8"))
    gaps = [(b - a) * 1000 for row in rows if row["status"] == "completed"
            for a, b in zip(row.get("token_times", []), row.get("token_times", [])[1:])]
    if gaps:
        result["inter_token_p99_ms"] = percentile(gaps, .99)
        result["max_inter_token_gap_ms"] = max(gaps)
    expected = percentile([r["ttft_ms"] for r in rows], .95)
    if abs(expected - result["ttft_p95_ms"]) > 1e-6:
        raise RuntimeError("summary does not match raw TTFT observations")
    workload = json.loads((source / "workload.json").read_text(encoding="utf-8"))
    shape = [(r["prompt"], r["max_tokens"], r["class"]) for r in workload]
    if reference is None:
        reference = shape
    elif reference != shape:
        raise RuntimeError("compared runs have different request content or output limits")
    if result["backend"] == "cpu-model":
        events = read_events(source / "worker-1.jsonl") + read_events(source / "worker-2.jsonl")
        by_request = defaultdict(list)
        for event in events:
            if event["event"] == "token":
                by_request[event["request_id"]].append(event)
        outputs = [[event["token_id"] for event in sorted(by_request[item["request_id"]], key=lambda e: e["seq"])]
                   for item in workload]
        if reference_outputs is None:
            reference_outputs = outputs
        elif outputs != reference_outputs:
            raise RuntimeError("greedy outputs differ across compared runs: " + result["run_id"])
if reference_outputs is not None:
    (folder / "output-consistency.json").write_text(json.dumps({"passed": True, "runs": len(results),
        "requests_per_run": len(reference_outputs), "criterion": "Identical token IDs per workload position across every trial"}, indent=2), encoding="utf-8")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

vary = next(k for k in ["execution", "chunked_prefill", "routing", "scheduling"] if len({r.get(k) for r in results}) > 1)
labels = {"round_robin": "Round robin", "least_outstanding": "Least outstanding",
          "static": "Static admission", "continuous": "Continuous admission",
          "sequential": "Independent forwards", "selective": "Selective batching",
          False: "Whole-prompt prefill", True: "Bounded chunked prefill"}
groups = defaultdict(list)
for r in results:
    groups[(r["rate"], r[vary])].append(r)
rates = sorted({r["rate"] for r in results})
policies = sorted({r[vary] for r in results})
summary = []
metrics = ["requests_s", "ttft_p95_ms", "latency_p95_ms"]
if all(r.get("inter_token_p95_ms") is not None for r in results):
    metrics.append("inter_token_p95_ms")
if all(r.get("inter_token_p99_ms") is not None for r in results):
    metrics.extend(["inter_token_p99_ms", "max_inter_token_gap_ms"])
for (rate, policy), observations in sorted(groups.items()):
    row = {"arrival_rate": rate, "policy": policy, "repeats": len(observations)}
    for key in metrics:
        values = [r[key] for r in observations]
        row[key + "_mean"] = statistics.mean(values)
        row[key + "_sample_sd"] = statistics.stdev(values) if len(values) > 1 else 0
    summary.append(row)
(folder / "aggregates.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
with (folder / "aggregates.csv").open("w", newline="", encoding="utf-8") as stream:
    writer = csv.DictWriter(stream, fieldnames=list(summary[0]))
    writer.writeheader()
    writer.writerows(summary)
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.spines.top": False,
                     "axes.spines.right": False, "axes.titleweight": "normal"})
plot_metrics = metrics[:4]
if vary == "chunked_prefill" and "inter_token_p99_ms" in metrics:
    plot_metrics = ["requests_s", "ttft_p95_ms", "inter_token_p95_ms", "inter_token_p99_ms"]
fig, axes = plt.subplots(1, len(plot_metrics), figsize=(4 * len(plot_metrics), 4.1), constrained_layout=True)
colors = ["#416b5a", "#a18a66"]
titles = {"requests_s": "Successful requests / second", "ttft_p95_ms": "First-token latency P95 (ms)",
          "latency_p95_ms": "Completion latency P95 (ms)", "inter_token_p95_ms": "Inter-token gap P95 (ms)",
          "inter_token_p99_ms": "Inter-token gap P99 (ms)"}
for ax, key in zip(axes, plot_metrics):
    for pi, policy in enumerate(policies):
        x = [i + (pi - .5) * .18 for i in range(len(rates))]
        values = [[r[key] for r in groups[(rate, policy)]] for rate in rates]
        means = [statistics.mean(v) for v in values]
        deviations = [statistics.stdev(v) if len(v) > 1 else 0 for v in values]
        ax.errorbar(x, means, yerr=deviations, color=colors[pi], fmt="o-", markersize=4,
                    capsize=4, linewidth=1.3, label=labels.get(policy, policy))
        for xi, vals in zip(x, values):
            jitter = [(j - (len(vals)-1)/2)*.025 for j in range(len(vals))]
            ax.scatter([xi+j for j in jitter], vals, color=colors[pi], s=15, alpha=.5)
    ax.set_title(titles[key], fontsize=10)
    ax.set_xticks(range(len(rates)), [f"{rate:g}" for rate in rates])
    ax.set_xlabel("Offered arrival rate (requests/s)")
    ax.grid(axis="y", color="#e8e9e2", linewidth=.7)
    ax.set_axisbelow(True)
    ax.set_ylim(bottom=0)
axes[0].legend(frameon=False, fontsize=8)
backend = results[0]["backend"]
count = results[0]["count"]
fig.suptitle(f"TokenFlow — {backend}; {count} fixed requests, 2 workers, 4 slots/worker\nIndividual trials and mean ± sample SD", fontsize=11)
fig.savefig(folder / "comparison.png", dpi=180)
fig.savefig(folder / "comparison.svg")
print(json.dumps(summary, indent=2))
