"""Official-Hub HTTP fallback with a verified LFS SHA256 for the pinned model."""
import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from huggingface_hub import HfApi, hf_hub_url
from llm_lab.backend import MODEL_ID, MODEL_REVISION
from llm_lab.common import ROOT, write_json

folder = ROOT / ".runtime" / "qwen25-05b"
folder.mkdir(parents=True, exist_ok=True)
info = HfApi().model_info(MODEL_ID, revision=MODEL_REVISION, files_metadata=True)
file = next(f for f in info.siblings if f.rfilename == "model.safetensors")
expected = file.lfs.sha256
temporary = folder / "model.safetensors.download"
started = time.perf_counter()
digest = hashlib.sha256()
total = 0
last_report = 0
url = hf_hub_url(MODEL_ID, "model.safetensors", revision=MODEL_REVISION)
with urllib.request.urlopen(url, timeout=30) as response, temporary.open("wb") as stream:
    while True:
        chunk = response.read(1024 * 1024)
        if not chunk:
            break
        stream.write(chunk)
        digest.update(chunk)
        total += len(chunk)
        if total - last_report >= 64 * 1024 * 1024:
            print(f"Downloaded {total / 1e6:.0f} / {file.size / 1e6:.0f} MB", flush=True)
            last_report = total
if total != file.size or digest.hexdigest() != expected:
    raise RuntimeError("model size or SHA256 verification failed")
temporary.replace(folder / "model.safetensors")
write_json(folder / "tokenflow-model.json", {"id": MODEL_ID, "revision": MODEL_REVISION,
                                            "weight_sha256": expected})
print(json.dumps({"verified": True, "bytes": total, "elapsed_s": time.perf_counter() - started, "sha256": expected}), flush=True)
