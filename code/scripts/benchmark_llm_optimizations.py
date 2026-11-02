"""Run and archive real execution/prefill comparisons with independent checks."""
import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from llm_lab.common import ROOT, json_http, write_json
from llm_lab.experiment import experiment
from llm_lab.check import check_run


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8800")
    parser.add_argument("--count", type=int, default=24)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--rates", default="6")
    parser.add_argument("--kinds", default="execution,prefill")
    args = parser.parse_args()
    if json_http(args.url + "/api/state")["backend"] != "cpu-model":
        raise RuntimeError("This benchmark requires the actual CPU model backend")
    if not 2 <= args.repeats <= 10 or not 4 <= args.count <= 200:
        parser.error("use 2-10 repeats and 4-200 requests")
    kinds = args.kinds.split(",")
    if any(k not in {"execution", "prefill", "batching", "routing"} for k in kinds):
        parser.error("unknown comparison kind")
    target = ROOT / "docs/llm-results"
    suites = []
    for kind in kinds:
        folder = experiment(args.url, kind, args.repeats, args.count, [float(v) for v in args.rates.split(",")])
        results = json.loads((folder / "results.json").read_text(encoding="utf-8"))
        for result in results:
            source = folder.parent / result["run_id"]
            checked = check_run(source)
            if not checked["passed"] or not checked["all_completed"]:
                raise RuntimeError("Independent recheck failed: " + str(source))
            shutil.copytree(source, target / source.name)
        shutil.copytree(folder, target / folder.name)
        suites.append({"kind": kind, "folder": folder.name, "runs": len(results)})
        write_json(target / "optimization-suites.json", suites)
    # Leave the application ready for ordinary chat using the optimized path.
    json_http(args.url + "/api/configure", {"routing": "least_outstanding", "scheduling": "continuous",
        "execution": "selective", "chunked_prefill": True, "prefill_chunk": 128, "slots": 4,
        "prefix_cache": False, "kv_budget": 4096})
    print(json.dumps({"archived": suites}), flush=True)


if __name__ == "__main__":
    main()
