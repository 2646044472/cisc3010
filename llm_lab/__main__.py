import argparse
import json
from pathlib import Path
from .common import ROOT, json_http, write_json


def main():
    parser = argparse.ArgumentParser(description="TokenFlow distributed serving laboratory")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve")
    serve.add_argument("--port", type=int, default=8800)
    serve.add_argument("--backend", choices=["simulator", "cpu-model"], default="cpu-model")
    serve.add_argument("--model-path", default=str(ROOT / ".runtime" / "qwen25-05b"))
    serve.add_argument("--workers", type=int, choices=range(1, 17), default=2, metavar="1-16")
    serve.add_argument("--threads", type=int, choices=range(1, 17), default=2, metavar="1-16",
                       help="PyTorch intra-op threads per model worker")
    worker = commands.add_parser("worker")
    worker.add_argument("--port", type=int, required=True)
    worker.add_argument("--id", required=True)
    worker.add_argument("--backend", choices=["simulator", "cpu-model"], default="simulator")
    worker.add_argument("--model-path")
    worker.add_argument("--threads", type=int, choices=range(1, 17), default=2, metavar="1-16")
    commands.add_parser("download-model")
    health = commands.add_parser("health")
    health.add_argument("--url", default="http://127.0.0.1:8800")
    demo = commands.add_parser("demo")
    demo.add_argument("--url", default="http://127.0.0.1:8800")
    demo.add_argument("--scenario", choices=["routing", "batching", "cache", "fault", "cancel", "heterogeneous", "surge", "multi_tenant"], default="routing")
    demo.add_argument("--routing", default="least_outstanding")
    demo.add_argument("--scheduling", choices=["static", "continuous"], default="continuous")
    demo.add_argument("--execution", choices=["selective", "sequential"], default="selective")
    demo.add_argument("--count", type=int, default=40)
    demo.add_argument("--rate", type=float, default=10)
    experiment = commands.add_parser("experiment")
    experiment.add_argument("--url", default="http://127.0.0.1:8790")
    experiment.add_argument("--kind", choices=["routing", "batching", "execution", "prefill"], default="routing")
    experiment.add_argument("--repeats", type=int, default=3)
    experiment.add_argument("--count", type=int, default=48)
    experiment.add_argument("--rates", default="6,18")
    check = commands.add_parser("check")
    check.add_argument("folder")
    args = parser.parse_args()
    if args.command == "serve":
        from .gateway import serve_gateway
        serve_gateway(args.port, args.backend, args.model_path, args.workers, args.threads)
    elif args.command == "worker":
        from .worker import serve_worker
        serve_worker(args.port, args.id, args.backend, args.model_path, args.threads)
    elif args.command == "download-model":
        import os
        os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
        from huggingface_hub import snapshot_download
        from .backend import MODEL_ID, MODEL_REVISION
        revision = MODEL_REVISION
        folder = ROOT / ".runtime" / "qwen25-05b"
        snapshot_download(MODEL_ID, revision=revision, local_dir=str(folder),
                          allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model", "README.md"])
        write_json(folder / "tokenflow-model.json", {"id": MODEL_ID, "revision": revision})
        print(json.dumps({"model": MODEL_ID, "revision": revision, "folder": str(folder)}))
    elif args.command == "health":
        state = json_http(args.url + "/api/state")
        print(json.dumps({"backend": state["backend"], "workers": [{k: w.get(k) for k in ["id", "pid", "healthy", "active", "queued"]} for w in state["workers"]]}, indent=2))
    elif args.command == "demo":
        from .experiment import run_remote
        result = run_remote(args.url, {"scenario": args.scenario, "routing": args.routing,
                                       "scheduling": args.scheduling, "execution": args.execution, "count": args.count, "rate": args.rate})
        print(json.dumps(result, indent=2))
        if not result["check"]["passed"]:
            raise SystemExit(1)
    elif args.command == "experiment":
        from .experiment import experiment
        if not 2 <= args.repeats <= 10:
            parser.error("use 2–10 repeated trials")
        experiment(args.url, args.kind, args.repeats, args.count, [float(r) for r in args.rates.split(",")])
    elif args.command == "check":
        from .check import check_run
        result = check_run(Path(args.folder))
        print(json.dumps(result, indent=2))
        if not result["passed"]:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
