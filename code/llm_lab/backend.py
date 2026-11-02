from __future__ import annotations

import os
import json
from pathlib import Path
from .common import token_for, simulator_input

MODEL_ID = "Qwen/Qwen2.5-0.5B-Instruct"
MODEL_REVISION = "7ae557604adf67be50417f59c2c2f167def9a775"


class Simulator:
    name = "simulator"
    model_id = "deterministic-token-model"
    revision = None

    def count(self, prompt, messages=None):
        return len(simulator_input(prompt, messages).split())

    def prepare(self, job):
        return None

    def step(self, job):
        return token_for(job.prompt, job.produced), False, None


class CpuModel:
    """Reference sequence execution and real Qwen2 selective batch execution."""
    name = "cpu-model"

    def __init__(self, model_path, threads=2):
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        self.torch = torch
        torch.set_num_threads(threads)
        torch.set_num_interop_threads(1)
        self.tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
        # Pin CPU arithmetic explicitly: the checkpoint's BF16 default can make
        # batched vs single-row GEMMs round tied greedy logits differently.
        self.model = AutoModelForCausalLM.from_pretrained(model_path, local_files_only=True,
                                                        dtype=torch.float32).eval()
        self.dtype = str(self.model.dtype)
        # The teaching engine uses raw-logit greedy decoding, without a repetition processor.
        self.model.generation_config.repetition_penalty = 1.0
        self.model.generation_config.do_sample = False
        metadata = Path(model_path) / "tokenflow-model.json"
        provenance = json.loads(metadata.read_text(encoding="utf-8")) if metadata.exists() else {}
        self.model_id = provenance.get("id", str(model_path))
        self.revision = provenance.get("revision")
        self.threads = threads
        # Warm the actual forward path in each process before reporting ready.
        with torch.inference_mode():
            self.model(**self.tokenizer("Hello", return_tensors="pt"), use_cache=True)

    def encode(self, prompt, messages=None):
        text = self.tokenizer.apply_chat_template(
            messages or [{"role": "user", "content": prompt}], tokenize=False, add_generation_prompt=True
        )
        return self.tokenizer(text, return_tensors="pt")["input_ids"]

    def count(self, prompt, messages=None):
        return self.encode(prompt, messages).shape[-1]

    def prepare(self, job):
        from transformers import DynamicCache
        job.model_state = {"input": self.encode(job.prompt, getattr(job, "messages", None)),
                           "cache": DynamicCache(config=self.model.config), "offset": 0,
                           "ids": [], "text": ""}

    def step(self, job):
        t = self.torch
        state = job.model_state
        with t.inference_mode():
            result = self.model(input_ids=state["input"], past_key_values=state["cache"],
                                use_cache=True, logits_to_keep=1)
        state["cache"] = result.past_key_values
        return self.record(job, int(result.logits[0, -1].argmax()))

    def iterate(self, jobs_and_sizes, execution="selective"):
        """Advance real prefill chunks and decode tokens in one scheduler iteration.

        Return None for intermediate prefill chunks; only the final prompt
        position produces the first output token. Every cache is request-local.
        """
        from .selective import forward_pieces
        pieces = []
        emits = []
        for job, size in jobs_and_sizes:
            state = job.model_state
            prefill = not state["ids"]
            ids = state["input"][:, state["offset"]:state["offset"] + size] if prefill else state["input"]
            pieces.append((ids, state["cache"]))
            emits.append(not prefill or state["offset"] + size == state["input"].shape[-1])
        with self.torch.inference_mode():
            if execution == "selective":
                logits = forward_pieces(self.model, pieces, emits)
            elif execution == "sequential":
                logits = [self.model(input_ids=ids, past_key_values=cache, use_cache=True,
                                     logits_to_keep=1).logits[0, -1] if emit else
                          self.model.model(input_ids=ids, past_key_values=cache, use_cache=True)
                          for (ids, cache), emit in zip(pieces, emits)]
            else:
                raise ValueError("unknown execution policy")
        results = []
        for (job, size), emit, values in zip(jobs_and_sizes, emits, logits):
            state = job.model_state
            if not state["ids"]:
                state["offset"] += size
            results.append(self.record(job, int(values.argmax())) if emit else None)
        return results

    def record(self, job, token):
        t = self.torch
        state = job.model_state
        state["input"] = t.tensor([[token]], dtype=t.long)
        state["ids"].append(token)
        text = self.tokenizer.decode(state["ids"], skip_special_tokens=True)
        # Full text accompanies the delta because tokenization may revise a suffix.
        delta = text[len(state["text"]):] if text.startswith(state["text"]) else ""
        state["text"] = text
        eos = self.model.generation_config.eos_token_id
        return delta, token in (eos if isinstance(eos, list) else [eos]), token
