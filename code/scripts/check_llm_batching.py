"""Verify pinned Qwen greedy outputs under ragged selective execution."""
import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from llm_lab.backend import CpuModel
from llm_lab.common import ROOT, write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "runs/llm/selective-reference.json")
    args = parser.parse_args()
    backend = CpuModel(str(ROOT / ".runtime/qwen25-05b"))
    prompts = [
        ("Explain a FIFO queue in two short sentences.", None),
        ("Describe three benefits of batching requests.", None),
        ("Context: " + "A distributed worker independently processes queued requests. " * 22 +
         "\nSummarize the context in one sentence.", None),
        ("Give an example.", [{"role": "user", "content": "What is a queue?"},
           {"role": "assistant", "content": "A queue processes items in arrival order."},
           {"role": "user", "content": "Give an everyday example in English."}]),
    ]
    references = []
    for prompt, messages in prompts:
        ids = backend.encode(prompt, messages)
        with backend.torch.inference_mode():
            expected = backend.model.generate(ids, max_new_tokens=24, do_sample=False,
                repetition_penalty=1.0, pad_token_id=backend.tokenizer.eos_token_id)
        references.append(expected[0, ids.shape[-1]:].tolist())
    cases = []
    for execution, chunk in [("sequential", 64), ("selective", 64), ("selective", 128)]:
        jobs = [SimpleNamespace(prompt=p, messages=m) for p, m in prompts]
        for j in jobs:
            backend.prepare(j)
        complete = set()
        iteration_sizes = []
        iteration = 0
        while len(complete) < len(jobs):
            # The fourth request arrives late, after the first token iteration.
            selected = [(i, j) for i, j in enumerate(jobs) if i not in complete and (i != 3 or iteration >= 3)]
            pieces = [(j, min(chunk, backend.count(j.prompt, j.messages) - j.model_state["offset"])
                       if not j.model_state["ids"] else 1) for _, j in selected]
            results = backend.iterate(pieces, execution)
            iteration_sizes.append(len(pieces))
            for (i, j), result in zip(selected, results):
                if result is not None and (result[1] or len(j.model_state["ids"]) == 24):
                    complete.add(i)
            iteration += 1
        for i, j in enumerate(jobs):
            actual = j.model_state["ids"]
            cases.append({"execution": execution, "prefill_chunk": chunk, "case": i,
                "input_tokens": backend.count(j.prompt, j.messages), "actual_ids": actual,
                "reference_ids": references[i], "passed": actual == references[i],
                "text": j.model_state["text"], "max_batch_requests": max(iteration_sizes)})
    result = {"passed": all(c["passed"] for c in cases), "model": backend.model_id,
              "revision": backend.revision, "dtype": backend.dtype, "torch": backend.torch.__version__,
              "threads": backend.threads, "reference": "Transformers.generate greedy, no repetition penalty",
              "cases": cases}
    write_json(args.output, result)
    print(json.dumps({"passed": result["passed"], "cases": len(cases), "output": str(args.output)}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
