"""Validate manual KV-cached greedy generation against Transformers.generate."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from llm_lab.backend import CpuModel
from llm_lab.common import ROOT, write_json

backend = CpuModel(str(ROOT / ".runtime" / "qwen25-05b"))
prompt = "Explain a FIFO queue in two short sentences."
job = SimpleNamespace(prompt=prompt, produced=0, model_state=None)
backend.prepare(job)
manual = []
for _ in range(32):
    _, eos, token_id = backend.step(job)
    manual.append(token_id)
    job.produced += 1
    if eos:
        break
inputs = backend.encode(prompt)
with backend.torch.inference_mode():
    reference = backend.model.generate(inputs, max_new_tokens=32, do_sample=False,
                                        pad_token_id=backend.tokenizer.eos_token_id)
expected = reference[0, inputs.shape[-1]:].tolist()
result = {"passed": manual == expected, "model": backend.model_id, "revision": backend.revision,
          "manual_ids": manual, "reference_ids": expected, "text": backend.tokenizer.decode(manual, skip_special_tokens=True),
          "torch": backend.torch.__version__, "threads": backend.threads}
write_json(ROOT / "runs" / "llm" / "model-reference.json", result)
print(json.dumps(result, indent=2))
raise SystemExit(0 if result["passed"] else 1)
