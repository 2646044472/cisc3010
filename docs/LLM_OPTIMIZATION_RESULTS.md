# TokenFlow: real serving optimizations - 20 October 2026

Real Qwen2.5-0.5B-Instruct now uses Orca-style selective batching and bounded hybrid prefill inside each of two independent CPU workers. On the fixed congested workload below, selective batching increased successful request throughput by **46.7%** and reduced P95 first-token latency by **37.6%**. These are local application measurements, not simulator or GPU-paper results.

## Implementation

- Share real Q/K/V projections, output projection, normalization and MLP across flattened request-token pieces. Run Attention separately with request-local KV and rotary positions. No padded cross-request KV packing is needed.
- Admit and retire requests between iterations. Decode tokens and actual prompt chunks can participate in the same shared layer computations.
- Limit prefill to a shared allowance of 128 tokenizer tokens per iteration when chunking is enabled. Decode work runs in each iteration; intermediate prompt chunks update KV without emitting output.
- Calculate vocabulary logits only at output-producing positions. The sequential control also uses last-position logits, so it is not artificially penalized by projecting the entire prompt.
- Keep independent forwards and whole-prompt prefill as explicit comparison options. The English UI keeps these choices in collapsed Test settings.
- Record actual iteration membership, piece sizes, compute duration and live KV tensor payload. An independent checker reconstructs prompt/decode work and validates the shared prefill allowance.

Paper relationships, execution diagrams and boundaries are in [LLM_PAPER_NOTES.md](LLM_PAPER_NOTES.md).

## Correctness before performance

All **27 automated tests** passed, including four new tests using a small real Qwen2 transformer. They check full-vocabulary numerical agreement for ragged cached chunks, mixed prefill/decode, request replacement, shared projection invocation, greedy output, cancellation and cleanup. The original six Kafka tests remain passing.

On the actual pinned Qwen model, **12 cases matched Transformers.generate token IDs exactly**: four prompts, including a long context and multi-turn conversation, with sequential/chunked and selective/chunked execution at two chunk sizes. A request also joins late. Evidence: `llm-results/selective-reference.json`.

A separate teacher-forced numerical audit uses the benchmark's long prompt, heterogeneous request histories and 31 decode steps. Complete vocabulary logits satisfy `atol=2e-4, rtol=2e-5`; the observed maximum absolute logit difference is **0.000020503997802734375**, with no argmax differences. Per-layer KV differences are recorded too. Evidence: `llm-results/selective-numerics.json`.

Both final comparison suites additionally verify **identical output token IDs at every workload position across all six trials**, not only ordered token numbers. All 288 benchmark requests completed and passed output, lifecycle, iteration accounting and cleanup checks.

Python compilation, frontend JavaScript syntax and `pip check` passed. The current Computer Use native connection was unavailable, so this update uses HTTP/SSE application checks and frontend syntax checks; the older browser screenshots and browser tests remain historical evidence from 14 October.

## Experiment contract

- Windows; Intel Core Ultra 5 338H; 12 logical processors; approximately 31.5 GiB RAM; Python 3.13.9.
- Pinned Qwen revision `7ae557604adf67be50417f59c2c2f167def9a775`; PyTorch 2.14.1+cpu; Transformers 5.19.0.
- **Explicit FP32 in both policies**; two workers; two intra-op threads and one inter-op thread per worker; four active slots each; worker reservation budget 4096 tokens.
- 24 fixed requests per trial, seed 3010, identical prompts and arrival offsets; output caps 16/48 tokens; 576 output tokens per trial. No future output length is exposed to the router.
- Offered rate 6 requests/s; least-outstanding routing; continuous admission. Controlled benchmark quota avoids application admission rejections.
- Three trials per policy; alternate policy order; both workers warmed before each trial. All warmup/counter reset rules and raw workloads are saved.
- Values below are mean +/- **sample standard deviation across trials**. They are not confidence intervals. P95/P99 use linear interpolation of the recorded client observations.

## 1. Shared computation

Suite: `llm-results/experiment-a501f3f100`. Both policies use bounded prefill with the same allowance; only execution changes.

| Metric | Independent forwards | Selective batching |
| --- | ---: | ---: |
| Successful requests/s | 0.787 +/- 0.008 | 1.154 +/- 0.006 |
| Delivered output tokens/s, mean | 18.88 | 27.69 |
| First-token latency P95, seconds | 19.179 +/- 0.359 | 11.977 +/- 0.018 |
| Completion latency P95, seconds | 26.537 +/- 0.307 | 17.149 +/- 0.087 |
| Inter-token gap P95, milliseconds | 996.1 +/- 4.0 | 869.9 +/- 2.5 |

The measured throughput improvement is 46.7%; first-token P95 falls 37.6%; completion P95 falls 35.4%. These are ratios of the run means. The experiment does not establish the same improvement at other request rates or on other hardware.

![Shared computation comparison](llm-results/experiment-a501f3f100/comparison.png)

## 2. Bounded prefill: a measured tradeoff

Suite: `llm-results/experiment-bee76f24b0`. Both policies use selective batching; only prefill chunking changes.

| Metric | Whole-prompt prefill | 128-token shared prefill allowance |
| --- | ---: | ---: |
| Successful requests/s | 1.167 +/- 0.025 | 1.147 +/- 0.031 |
| First-token latency P95, seconds | 11.983 +/- 0.335 | 11.986 +/- 0.363 |
| Inter-token gap P95, milliseconds | 544.6 +/- 6.9 | 854.6 +/- 34.2 |
| Inter-token gap P99, milliseconds | 1962.9 +/- 27.8 | 913.7 +/- 21.0 |
| Maximum inter-token gap per trial, milliseconds | 2632.6 +/- 821.5 | 926.4 +/- 17.9 |

Chunking reduced P99 gaps by **53.5%** and the mean trial maximum by **64.8%**, but made P95 gaps **56.9% worse**. It spreads prefill interference over more iterations rather than eliminating it. The mean throughput is slightly lower; variation does not establish a clear throughput advantage for either setting. First-token P95 is essentially unchanged in this workload.

The application retains bounded prefill by default to reduce rare multi-second freezes while streaming. Whole-prompt processing remains available for comparison. This is an application choice based on the measured tail-gap tradeoff, not a claim that chunking improves every percentile or is optimal for every prompt.

Inter-token observations are pooled **within each trial**; the table then summarizes the three trial percentiles. Tokens are correlated within requests, so these are descriptive metrics, not independent statistical samples. P99 and maximum-gap diagnostics were added after the initial P95 analysis exposed the tradeoff; they should be validated on a larger preregistered workload before making general claims.

![Prefill tradeoff](llm-results/experiment-bee76f24b0/comparison.png)

## Functional regression checks

| Scenario | Saved run | Outcome |
| --- | --- | --- |
| Cancel every fourth request, 12 at 6/s | `20261020T031416-488794af` | 9 completed, 3 cancelled; no active/queued/KV or gateway reservation leaks. |
| Stop Worker 1 during 16 requests at 6/s | `20261020T033250-67cc56c5` | 9 completed, 7 explicitly failed; detection 0.554 seconds; new requests completed through Worker 2. |

Both runs passed the independent checker and verified their intended scenarios. `all_completed=false` is expected for cancellation/failure. Interrupted partial streams are not silently replayed. Workers were restarted after regression testing.

A final HTTP/SSE application smoke check completed six real responses: an English question, a follow-up with explicit conversation context, and four concurrent requests. Both workers reported shared execution iterations, then returned to zero active requests, queued requests, reserved KV tokens and live KV payload. Evidence: `llm-results/application-optimization-smoke.json`. Health is sampled asynchronously, so cleanup verification waits for the next idle health observation.

## Numerical issue discovered and corrected

The checkpoint originally loaded in native BF16. On a long workload prompt, batching caused a greedy divergence at output index 14. A teacher-forced audit found a reference top-two margin of 0.125 rounded into a tie in the selective path; full-vocabulary strict numerical agreement failed. The failed audit is retained as `selective-numerics-bfloat16.json`.

CPU loading is now explicitly FP32. The strict numerical audit, generation checks and both comparative suites were rerun. Earlier BF16 suites `experiment-95d22689ad` and `experiment-a30563c666` are labelled **DEVELOPMENT_ONLY** and excluded from the final comparison. BF16 development speed numbers are not mixed into the FP32 tables above.

## Reproduce

```powershell
.\scripts\start-llm.ps1
# In a second terminal:
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts\check_llm_batching.py
.\.venv\Scripts\python.exe scripts\check_llm_numerics.py
.\.venv\Scripts\python.exe scripts\benchmark_llm_optimizations.py
.\.venv\Scripts\python.exe scripts\plot_llm_results.py docs\llm-results\experiment-a501f3f100
.\.venv\Scripts\python.exe scripts\plot_llm_results.py docs\llm-results\experiment-bee76f24b0
```

Run numerical/unit checks before benchmarking, and keep other compute idle during comparative trials. The benchmark produces new unique suite IDs; use those when plotting new trials. `llm-results/optimization-suites.json` identifies the most recently archived suites. Raw per-request observations, worker iteration traces, configs, cleanup states, consistency checks, sample-SD tables and PNG/SVG figures are retained.

## Limits

The offered rate exceeds completion throughput in both settings: these are congestion experiments, not a light-load capacity sweep. Each trial has only 24 requests, making request P95 coarse. Two workers share CPU and memory resources, and ordinary DynamicCache still reallocates as it grows. Live KV payload excludes backing-storage/allocator overhead and process/model memory.

The implementation is limited to full-attention Qwen2 and FP32 CPU inference. It does not implement PagedAttention, shared-prefix KV reuse, model/tensor parallelism, dedicated prefill/decode machines, GPU kernels, or OpenAI's private serving stack. No million-user capacity conclusion follows from this local experiment.
