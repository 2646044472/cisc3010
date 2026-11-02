import argparse
import json
from pathlib import Path

from . import storage
from .runner import Config, ROOT, Run, SCENARIOS, broker_ready, experiment


def main():
    parser = argparse.ArgumentParser(description="Kafka consumer recovery lab")
    parser.add_argument("--bootstrap", default="localhost:19092")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("health")
    demo = sub.add_parser("demo")
    demo.add_argument("--scenario", choices=(*SCENARIOS, "all"), default="all")
    demo.add_argument("--events", type=int, default=120)
    demo.add_argument("--consumers", type=int, default=2)
    demo.add_argument("--processing-ms", type=int, default=15)
    serve = sub.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8787)
    check = sub.add_parser("check")
    check.add_argument("run_dir", type=Path)
    exp = sub.add_parser("experiment")
    exp.add_argument("--counts", default="1,2,4,6")
    exp.add_argument("--repeats", type=int, default=3)
    exp.add_argument("--events", type=int, default=240)
    exp.add_argument("--processing-ms", type=int, default=15)
    args = parser.parse_args()
    if args.command == "health":
        print(json.dumps(broker_ready(args.bootstrap), indent=2))
    elif args.command == "serve":
        from .web import serve
        serve(args.host, args.port, args.bootstrap)
    elif args.command == "check":
        directory = args.run_dir.resolve()
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        with storage.open_db(directory / "audit.sqlite3") as db:
            report = storage.check(db)
            report["scenario_verified"] = storage.verify_scenario(report, manifest["scenario"], db.execute("SELECT COUNT(*) FROM faults").fetchone()[0])
        print(json.dumps(report, indent=2))
        return 0 if report["scenario_verified"] else 1
    elif args.command == "demo":
        for scenario in SCENARIOS if args.scenario == "all" else [args.scenario]:
            run = Run(Config(scenario=scenario, events=args.events, consumers=args.consumers,
                             processing_ms=args.processing_ms, bootstrap=args.bootstrap))
            print(f"Starting {scenario}: {run.directory}", flush=True)
            run.execute()
            print(json.dumps(run.result or {"error": run.error}, indent=2), flush=True)
            if run.state != "finished":
                return 1
    elif args.command == "experiment":
        counts = [int(x) for x in args.counts.split(",")]
        if not counts or len(set(counts)) != len(counts) or not 1 <= args.repeats <= 20:
            parser.error("Unique consumer counts and repeats in [1,20] required")
        print(experiment(counts, args.repeats, args.events, args.processing_ms, args.bootstrap))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
