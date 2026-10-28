"""Recheck the archived real-model routing experiment and recreate its figure.

This reads only the supplied archive; it does not rerun model inference. Each
run is checked against its raw request and event traces before aggregation.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import math
import statistics
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from llm_lab.check import check_run
from llm_lab.common import read_worker_events
from llm_lab.experiment import percentile


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def run(archive, output):
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="tokenflow-evidence-") as tmp:
        scratch = Path(tmp)
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                name = PurePosixPath(info.filename)
                if name.is_absolute() or ".." in name.parts or "\\" in info.filename:
                    raise ValueError(f"Unsafe archive path: {info.filename}")
            z.extractall(scratch)

        suites = [("random", scratch / "random-suite"), ("order", scratch / "diagnostic-suite")]
        expected_runs = {"random": 24, "order": 16}
        run_rows, seen_shapes, seen_outputs = [], {}, {}
        token_count = 0
        for family, suite in suites:
            results = read_json(suite / "results.json")
            if len(results) != expected_runs[family]:
                raise ValueError(f"Unexpected {family} trial count: {len(results)}")
            for result in results:
                folder = scratch / "runs" / result["run_id"]
                config = read_json(folder / "config.json")
                workload = read_json(folder / "workload.json")
                requests = read_json(folder / "requests.json")
                checked = check_run(folder)
                if not checked["passed"] or not checked["all_completed"]:
                    raise ValueError(f"Invalid evidence {result['run_id']}: {checked['errors']}")
                expected = 120 if family == "random" else 64
                if len(workload) != expected or result["successes"] != expected:
                    raise ValueError(f"Unexpected request count: {result['run_id']}")
                settings = config["settings"]
                if (config["backend"] != "cpu-model" or settings["execution"] != "selective"
                        or settings["scheduling"] != "continuous" or settings["slots"] != 4
                        or settings["prefill_chunk"] != 128 or settings["kv_budget"] != 4096
                        or config["environment"]["workers"] != 2
                        or config["environment"]["model_threads_per_worker"] != 2):
                    raise ValueError(f"Experiment settings differ: {result['run_id']}")
                phase = "random" if family == "random" else result["workload_pattern"]
                rate = float(result["rate"])
                shape = [(x["prompt"], x["max_tokens"], x["class"], x["arrival_s"]) for x in workload]
                key = (family, phase, rate)
                if key in seen_shapes and seen_shapes[key] != shape:
                    raise ValueError(f"Workloads differ within comparison: {result['run_id']}")
                seen_shapes[key] = shape

                by_id = collections.defaultdict(list)
                for event in read_worker_events(folder):
                    if event["event"] == "token":
                        by_id[event["request_id"]].append(event)
                token_ids = [[e["token_id"] for e in sorted(by_id[item["request_id"]], key=lambda x: x["seq"])]
                             for item in workload]
                output_key = (family, phase)
                if output_key in seen_outputs and seen_outputs[output_key] != token_ids:
                    raise ValueError(f"Greedy token IDs differ: {result['run_id']}")
                seen_outputs[output_key] = token_ids
                token_count += sum(map(len, token_ids))

                for source, metric in [("ttft_ms", "ttft_p95_ms"), ("latency_ms", "latency_p95_ms")]:
                    actual = percentile([x[source] for x in requests], .95)
                    if not math.isclose(actual, result[metric], abs_tol=1e-6):
                        raise ValueError(f"Raw {metric} differs: {result['run_id']}")
                run_rows.append({"family": family, "phase": phase, **result})

        groups = collections.defaultdict(list)
        for row in run_rows:
            groups[(row["family"], row["phase"], float(row["rate"]), row["routing"])].append(row)
        metrics = ["requests_s", "ttft_p95_ms", "latency_p95_ms"]
        summary = []
        for (family, phase, rate, policy), rows in sorted(groups.items()):
            row = {"family": family, "phase": phase, "rate": rate, "policy": policy,
                   "repeats": len(rows), "requests_per_trial": rows[0]["count"]}
            for metric in metrics:
                values = [x[metric] for x in rows]
                row[metric + "_mean"] = statistics.mean(values)
                row[metric + "_sample_sd"] = statistics.stdev(values)
            summary.append(row)

        pairs = []
        conditions = sorted({(a, b, c) for a, b, c, _ in groups})
        for family, phase, rate in conditions:
            rr = sorted(groups[(family, phase, rate, "round_robin")], key=lambda x: x["repeat"])
            lo = sorted(groups[(family, phase, rate, "least_outstanding")], key=lambda x: x["repeat"])
            if [x["repeat"] for x in rr] != [x["repeat"] for x in lo]:
                raise ValueError("Unmatched paired trials")
            n = len(rr)
            critical = {4: 3.1824463053, 6: 2.5705818366}[n]
            for metric in metrics:
                diff = [(b[metric] - a[metric]) if metric == "requests_s" else (a[metric] - b[metric])
                        for a, b in zip(rr, lo)]
                mean = statistics.mean(diff)
                half = critical * statistics.stdev(diff) / math.sqrt(n)
                pairs.append({"family": family, "phase": phase, "rate": rate, "metric": metric,
                              "pairs": n, "mean_favorable_difference": mean,
                              "difference_ci95_low": mean - half, "difference_ci95_high": mean + half})
        with (output / "summary.csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(summary[0]))
            writer.writeheader()
            writer.writerows(summary)
        with (output / "paired-effects.csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(pairs[0]))
            writer.writeheader()
            writer.writerows(pairs)
        report = {"passed": True, "trials": len(run_rows), "requests": sum(x["count"] for x in run_rows),
                  "tokens_checked": token_count, "same_workload_within_comparison": True,
                  "identical_greedy_output_within_workload_family": True,
                  "scope": "2 Qwen CPU workers on one shared host; order diagnostic is synthetic."}
        (output / "verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        colors = {"round_robin": "#3658b4", "least_outstanding": "#b47732"}
        labels = {"requests_s": "Completed requests / s", "ttft_p95_ms": "P95 first token / s",
                  "latency_p95_ms": "P95 completion / s"}
        fig, axes = plt.subplots(1, 3, figsize=(12.5, 4), layout="constrained")
        for ax, metric in zip(axes, metrics):
            for policy, color in colors.items():
                for index, rate in enumerate((1.0, 3.0)):
                    rows = groups[("random", "random", rate, policy)]
                    scale = 1 if metric == "requests_s" else 1000
                    values = [r[metric] / scale for r in rows]
                    x = index + (-.13 if policy == "round_robin" else .13)
                    ax.errorbar(x, statistics.mean(values), yerr=statistics.stdev(values), fmt="o",
                                color=color, capsize=4, label=policy.replace("_", " ") if index == 0 else None)
                    ax.scatter([x + (i - 2.5) * .015 for i in range(6)], values, s=14, alpha=.5, color=color)
            ax.set_xticks([0, 1], ["1 request/s", "3 requests/s"])
            ax.set_title(labels[metric])
            ax.set_ylim(bottom=0)
            ax.grid(axis="y", alpha=.2)
        axes[0].legend(frameon=False)
        fig.suptitle("Real Qwen routing: six paired trials per arrival rate (mean +/- sample SD)")
        fig.savefig(output / "routing-comparison.png", dpi=180)
        fig.savefig(output / "routing-comparison.svg")
        plt.close(fig)
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=ROOT / "evidence/routing/raw-routing.zip")
    parser.add_argument("--output", type=Path, default=ROOT / "verification-output/routing")
    args = parser.parse_args()
    run(args.archive, args.output)
