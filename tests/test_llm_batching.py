"""Numerical, isolation and lifecycle checks on a small real Qwen2 transformer."""
import unittest
from types import SimpleNamespace

try:
    import torch
    from transformers import DynamicCache, Qwen2Config, Qwen2ForCausalLM
except ImportError:
    torch = None

from llm_lab.backend import CpuModel
from llm_lab.selective import forward_pieces
from llm_lab.worker import Engine


@unittest.skipUnless(torch is not None, "optional CPU inference dependencies are not installed")
class SelectiveBatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(2)
        torch.manual_seed(3010)
        cls.model = Qwen2ForCausalLM(Qwen2Config(vocab_size=128, hidden_size=32,
            intermediate_size=64, num_hidden_layers=2, num_attention_heads=4,
            num_key_value_heads=2, max_position_embeddings=512)).eval()
        cls.model.set_attn_implementation("sdpa")

    def cache(self):
        return DynamicCache(config=self.model.config)

    def test_ragged_mixed_chunks_match_independent_full_forwards(self):
        caches = [self.cache(), self.cache()]
        histories = [[], []]
        # Different initial lengths, cached multi-token chunks, mixed decode,
        # a completed request leaving and a fresh request taking its position.
        plans = [([1, 2, 3, 4, 5], [8, 9]), ([6], [10, 11, 12]), ([7], [13]), ([14], [21, 22, 23])]
        with torch.inference_mode():
            for iteration, inputs in enumerate(plans):
                if iteration == 3:
                    caches[1] = self.cache()
                    histories[1] = []
                pieces = [(torch.tensor([ids]), cache) for ids, cache in zip(inputs, caches)]
                actual = forward_pieces(self.model, pieces, [True, True])
                for i, ids in enumerate(inputs):
                    histories[i].extend(ids)
                    expected = self.model(torch.tensor([histories[i]]), logits_to_keep=1).logits[0, -1]
                    torch.testing.assert_close(actual[i], expected, atol=2e-6, rtol=2e-5)
                    self.assertEqual(caches[i].get_seq_length(), len(histories[i]))

    def test_projections_are_shared_and_intermediate_prefill_has_no_logits(self):
        shapes = []
        hook = self.model.model.layers[0].self_attn.q_proj.register_forward_pre_hook(
            lambda module, args: shapes.append(tuple(args[0].shape)))
        try:
            with torch.inference_mode():
                result = forward_pieces(self.model, [(torch.tensor([[1, 2, 3]]), self.cache()),
                                                      (torch.tensor([[8]]), self.cache())], [False, True])
            self.assertEqual(shapes, [(1, 4, 32)])
            self.assertIsNone(result[0])
            self.assertEqual(result[1].shape, (128,))
        finally:
            hook.remove()

    def backend(self):
        backend = CpuModel.__new__(CpuModel)
        backend.torch, backend.model = torch, self.model
        backend.tokenizer = SimpleNamespace(decode=lambda ids, **kwargs: " ".join(map(str, ids)))
        backend.model_id, backend.revision = "tiny-random-qwen2-test", None
        backend.encode = lambda prompt, messages=None: torch.tensor([[1] + [2] * len(prompt.split())])
        return backend

    def test_greedy_output_matches_reference_with_chunking(self):
        backend = self.backend()
        jobs = [SimpleNamespace(prompt="short", messages=None), SimpleNamespace(prompt="long " * 15, messages=None)]
        for j in jobs:
            backend.prepare(j)
        with torch.inference_mode():
            expected = [self.model.generate(backend.encode(j.prompt), max_new_tokens=8, do_sample=False,
                                            eos_token_id=None, pad_token_id=0)[0, backend.count(j.prompt):].tolist()
                        for j in jobs]
        for execution in ("sequential", "selective"):
            for j in jobs:
                backend.prepare(j)
            while any(len(j.model_state["ids"]) < 8 for j in jobs):
                pieces = [(j, min(3, backend.count(j.prompt) - j.model_state["offset"]) if not j.model_state["ids"] else 1)
                          for j in jobs if len(j.model_state["ids"]) < 8]
                backend.iterate(pieces, execution)
            self.assertEqual([j.model_state["ids"] for j in jobs], expected)

    def test_real_scheduler_cancellation_and_bounded_prefill(self):
        engine = Engine("tiny-real", self.backend())
        try:
            engine.configure({"slots": 2, "prefill_chunk": 3})
            with engine.lock:
                first = engine.submit({"request_id": "tiny-long", "prompt": "context " * 35, "max_tokens": 60})
                second = engine.submit({"request_id": "tiny-short", "prompt": "hi", "max_tokens": 2})
            while True:
                ev = first.output.get(timeout=10)
                if ev["event"] == "prefill":
                    self.assertLessEqual(ev["chunk_tokens"], 3)
                    self.assertTrue(engine.cancel_job(first.request_id))
                    break
            events = []
            while not events or events[-1]["event"] not in {"completed", "failed", "cancelled"}:
                events.append(first.output.get(timeout=10))
            self.assertEqual(events[-1]["event"], "cancelled")
            while True:
                ev = second.output.get(timeout=10)
                if ev["event"] in {"completed", "failed", "cancelled"}:
                    self.assertEqual(ev["event"], "completed")
                    break
            self.assertIsNone(first.model_state)
            self.assertIsNone(second.model_state)
            self.assertEqual(engine.snapshot()["kv_reserved"], 0)
        finally:
            engine.stop.set()
            engine.thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
