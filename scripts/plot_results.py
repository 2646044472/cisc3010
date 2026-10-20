"""Traceable experiment figure: all raw runs, mean and sample standard deviation."""
import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("experiment_dir", type=Path)
    args = parser.parse_args()
    directory = args.experiment_dir.resolve()
    rows = list(csv.DictReader((directory / "results.csv").open(encoding="utf-8")))
    values = defaultdict(list)
    for row in rows:
        result = json.loads((directory / row["run_id"] / "result.json").read_text(encoding="utf-8"))
        if not result["data_correct"] or not result["scenario_verified"]:
            raise ValueError(f"Incorrect run: {row['run_id']}")
        value = float(row["unique_effects_per_s"])
        if abs(value - result["unique_effects_per_s"]) > 1e-8:
            raise ValueError("CSV/raw result mismatch")
        values[int(row["consumers"])].append(value)
    if not values:
        raise ValueError("No measurements")
    config = json.loads((directory / "config.json").read_text(encoding="utf-8"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    counts = sorted(values)
    means = [statistics.mean(values[c]) for c in counts]
    deviations = [statistics.stdev(values[c]) if len(values[c]) > 1 else 0 for c in counts]
    fig, ax = plt.subplots(figsize=(8, 4.8), constrained_layout=True)
    ax.errorbar(counts, means, yerr=deviations, fmt="o-", color="#367b64", capsize=5,
                label="Mean ± sample standard deviation")
    for count in counts:
        for i, value in enumerate(values[count]):
            jitter = (i - (len(values[count]) - 1) / 2) * 0.055
            ax.scatter(count + jitter, value, color="#367b64", alpha=.5, s=22)
    ax.set(xticks=counts, xlabel="Consumers in one group", ylabel="Unique durable effects / second",
           title=f"Kafka pipeline: {config['partitions']} partitions, {config['events']} events/run\n"
                 f"Synthetic application delay {config['processing_ms']} ms/event")
    ax.grid(axis="y", alpha=.22)
    ax.legend(fontsize=9)
    fig.savefig(directory / "throughput.png", dpi=180)
    fig.savefig(directory / "throughput.svg")
    with (directory / "summary.csv").open("w", newline="", encoding="utf-8") as out:
        writer = csv.writer(out)
        writer.writerow(["consumers", "repetitions", "mean_effects_per_s", "sample_std", "min", "max"])
        for c, mean, deviation in zip(counts, means, deviations):
            writer.writerow([c, len(values[c]), mean, deviation, min(values[c]), max(values[c])])
    print(directory / "throughput.png")


if __name__ == "__main__":
    main()
