# Serving papers and application changes

Reviewed 20 October 2026. These papers guide specific mechanisms; their GPU benchmark numbers are not predictions for this laptop.

| Reading | What matters here | TokenFlow implementation |
| --- | --- | --- |
| [Orca, OSDI 2022](https://www.usenix.org/system/files/osdi22-yu.pdf), Section 3 and Figure 5 | Schedule one iteration at a time. Flatten tokens for shared non-Attention operations, then split and merge around request-local Attention. | `llm_lab/selective.py` shares Q/K/V projections, output projection, normalization and MLP across real Qwen requests. Each request retains its own variable-length KV cache and rotary positions. |
| [PagedAttention/vLLM, SOSP 2023](https://arxiv.org/pdf/2309.06180), memory-management design | KV layout and ownership affect capacity, fragmentation and sharing. | Explicit request ownership and terminal cleanup; live KV tensor payload is observable. PagedAttention, a block allocator and cross-request prefix reuse are **not implemented**. |
| [Sarathi-Serve, OSDI 2024](https://www.usenix.org/system/files/osdi24-agrawal.pdf), Sections 3-4 | Long prefills interfere with decode. Construct bounded hybrid iterations with decodes first. | Running decode tokens join actual prompt chunks in shared layer computation. One prefill allowance is shared across an iteration, so four slots cannot each consume the entire allowance. |
| [DistServe, OSDI 2024](https://www.usenix.org/system/files/osdi24-zhong-yinmin.pdf), Sections 2-5 | Separate TTFT and decode latency objectives; phase disaggregation trades interference for KV-transfer and provisioning costs. | Measure client TTFT and inter-token gaps separately. Keep two complete replicas; CPU phase disaggregation is deferred. |

## Execution path

An iteration can contain A's next decode token, B's next decode token, and a chunk of C's prompt:

```text
A: 1 token  ─┐
B: 1 token  ─┼─ concatenate real token embeddings
C: 96 tokens┘       → shared normalization and Q/K/V projections
                      → split into independent Attention operations and caches
                      → merge → shared output projection and MLP
                      → repeat for every transformer layer
                      → logits only at output-producing positions
```

Requests can have different context lengths. No request attends to another request's tokens. There is no padding of histories into a common sequence length. Cached multi-token chunks use an explicit causal mask that includes earlier cached tokens and prevents looking ahead within the chunk. Each request uses its own logical rotary positions.

Intermediate prefill chunks update KV state without emitting an answer token. The final prompt position produces the first token. Once a request completes or is cancelled, its KV state is released; other requests continue at the next iteration. A stopped client does not trigger replay of previously streamed output.

The output vocabulary projection is evaluated only for positions that produce an output token. The sequential control also uses last-position logits, making the execution comparison about shared computation rather than unnecessarily projecting every prompt position in the baseline.

## Scope and differences

- This is a full-attention Qwen2 CPU implementation using pretrained model weights and installed PyTorch/Transformers primitives. It does not support arbitrary model architectures or sliding-window attention.
- Orca's model-parallel GPU engine, distributed layer partitions and multi-GPU pipeline scheduler are not reproduced. Our gateway distributes complete requests between two independent replicas.
- Decode pieces are selected first and pending prompts share a configurable prefill allowance. This is inspired by Sarathi; there is no calibrated constant-time GPU batch budget or guarantee of stall-free generation.
- `prefill_chunk=128` limits real prefill tokens per iteration, not wall-clock duration. Chunking can increase first-token latency and repeated KV access. Both sides of that tradeoff must be reported.
- Ordinary DynamicCache still grows by concatenation. The implementation does not claim PagedAttention memory efficiency or cross-request prefix caching.
- CPU arithmetic is explicitly FP32 in both comparison policies. An earlier BF16 audit found that changed matrix shapes could round close greedy logits into a tie; its failed strict numerical check is retained separately. The FP32 teacher-forced audit checks full-vocabulary logits and per-layer KV differences, rather than relying only on matching a few generated answers.
- `kv_payload_bytes` counts current KV tensor elements. It excludes model weights, tensor backing-storage/allocator overhead, temporary operations and process memory. It is not resident-set size.

## Evidence and reproduction

`scripts/check_llm_batching.py` compares real pinned Qwen generation with `Transformers.generate`: heterogeneous prompts, multi-turn context, a late-arriving request, and two chunk sizes. Small real-transformer tests additionally check numerical logits, request replacement, shared projection invocation, causal masks, cancellation and cache cleanup.

```powershell
.\.venv\Scripts\python.exe scripts\check_llm_batching.py
.\.venv\Scripts\python.exe scripts\benchmark_llm_optimizations.py
```

The benchmark alternates policy order over three trials per policy and preserves identical prompt content, arrivals and output caps. It separately compares independent forwards vs selective batching and whole-prompt vs bounded prefill. Each has 24 requests per trial at an offered 6 requests/s. This is a congested-load comparison, not a full capacity curve. Plots independently recheck lifecycle, execution-piece accounting, and exact greedy token-ID agreement across compared trials.

The current measurements and their limitations are recorded in `LLM_OPTIMIZATION_RESULTS.md`. The English application remains Chat / Service status; execution choice and prefill allowance sit in the existing collapsed test settings.

## Supporting implementation references

- [Transformers 5.19.0 cache contract](https://huggingface.co/docs/transformers/v5.19.0/en/cache_explanation)
- [vLLM optimization tradeoffs](https://docs.vllm.ai/en/latest/configuration/optimization.html)
- [vLLM CPU platform and thread considerations](https://docs.vllm.ai/en/latest/getting_started/installation/cpu.html)

These references supplement the original papers. They do not establish OpenAI's private serving implementation.
