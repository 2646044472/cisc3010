"""Teacher-forced logits/cache audit for the real benchmark's long prompt."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from transformers import DynamicCache
from llm_lab.backend import CpuModel
from llm_lab.common import ROOT, write_json
from llm_lab.experiment import workload
from llm_lab.selective import forward_pieces


def main():
    b = CpuModel(str(ROOT / ".runtime/qwen25-05b"))
    t = b.torch
    item = next(x for x in workload(24, 6, 3010, "numeric-check") if x["class"] == "long")
    prompt = b.encode(item["prompt"])
    a, c, partner = (DynamicCache(config=b.model.config) for _ in range(3))
    measurements = []
    def compare(ids, other, label):
        with t.inference_mode():
            ref = b.model(input_ids=ids, past_key_values=a, use_cache=True, logits_to_keep=1).logits[0, -1]
            actual = forward_pieces(b.model, [(ids, c), (other, partner)], [True, True])[0]
        maximum = float((ref - actual).abs().max())
        # Full-vocabulary logit tolerance, rather than an argmax-only test.
        close = t.allclose(ref, actual, atol=2e-4, rtol=2e-5)
        top = ref.topk(2)
        measurements.append({"stage": label, "max_abs_logit_error": maximum,
            "logits_close": close, "reference_argmax": int(ref.argmax()),
            "selective_argmax": int(actual.argmax()), "reference_top2_ids": top.indices.tolist(),
            "reference_top2_logits": top.values.tolist(),
            "reference_margin": float(top.values[0] - top.values[1]),
            "selective_top2_logits": actual[top.indices].tolist(),
            "max_key_error": max(float((x.keys-y.keys).abs().max()) for x,y in zip(a.layers,c.layers)),
            "max_value_error": max(float((x.values-y.values).abs().max()) for x,y in zip(a.layers,c.layers))})
        return int(ref.argmax())
    for offset in range(0, prompt.shape[-1], 128):
        token = compare(prompt[:, offset:offset+128], t.tensor([[45, 12, 21]]), "prefill-" + str(offset))
    # Feed the SAME reference token to both paths, preventing branch divergence
    # from disguising an actual numerical error.
    for index in range(1, 32):
        token = compare(t.tensor([[token]]), t.tensor([[45]]), "decode-" + str(index))
    result = {"passed": all(m["logits_close"] for m in measurements), "model": b.model_id, "dtype": b.dtype,
        "revision": b.revision, "prompt_tokens": prompt.shape[-1],
        "criterion": "same teacher-forced history; full-vocabulary allclose atol=2e-4 rtol=2e-5",
        "measurements": measurements}
    write_json(ROOT / "docs/llm-results/selective-numerics.json", result)
    print(json.dumps({"passed": result["passed"], "dtype": b.dtype,
        "max_logit_error": max(m["max_abs_logit_error"] for m in measurements),
        "argmax_differences": sum(m["reference_argmax"] != m["selective_argmax"] for m in measurements)}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
