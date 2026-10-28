"""Send the checked-in sample prompts to a running TokenFlow service."""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from llm_lab.experiment import client_request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8790")
    parser.add_argument("--samples", type=Path, default=ROOT / "samples/requests.json")
    args = parser.parse_args()
    samples = json.loads(args.samples.read_text(encoding="utf-8"))
    for sample in samples:
        request = {"prompt": sample["prompt"], "max_tokens": sample["max_tokens"],
                   "request_id": "sample-" + uuid.uuid4().hex, "class": sample["name"]}
        response = client_request(args.url, request)
        print(json.dumps({"sample": sample["name"], "status": response["status"],
                          "worker": response["worker"], "tokens": response["tokens"],
                          "ttft_ms": response["ttft_ms"], "text": response["text"]}, indent=2))
        if response["status"] != "completed":
            raise SystemExit("Sample failed: " + str(response["error"]))


if __name__ == "__main__":
    main()
