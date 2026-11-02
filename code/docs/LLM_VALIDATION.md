# TokenFlow validation — 14 October 2026

The final expanded real-Qwen routing comparison is documented in the [submission README](../README.md#required-experiment-routing) and [evidence guide](../evidence/README.md). Historical `llm-results/` paths correspond to material in the evidence archives where listed.

Four real model replicas were tested on 22 October, and the final demo default remains two. See [replica-count results and current regression checks](LLM_SCALING_RESULTS.md) for the completed 1/2/4-worker comparison. The evidence below retains its original two-worker setup.

**Historical baseline.** The original evidence below records the 14 October implementation. Real selective batching and bounded real prefill were added on 20 October; the current checks, comparative results and limitations are in [LLM_OPTIMIZATION_RESULTS.md](LLM_OPTIMIZATION_RESULTS.md). Statements below about independent CPU forwards describe the earlier version.

This records completed checks, not target performance. Default Demo: English UI, local Qwen2.5-0.5B-Instruct, two independent CPU worker processes, http://127.0.0.1:8800/. A separate simulator runs on port 8790 for controlled batching experiments.

## Environment and model

- Windows, Python 3.13.9; Intel Core Ultra 5 338H, 12 logical processors, approximately 31.5 GiB RAM. Hardware JSON and the installed package list are retained beside this document.
- PyTorch 2.14.1+cpu, Transformers 5.19.0; two intra-op threads and one inter-op thread per worker.
- Model: `Qwen/Qwen2.5-0.5B-Instruct`, pinned revision `7ae557604adf67be50417f59c2c2f167def9a775`.
- Weight file: 988,097,824 bytes, SHA256 `fdf756fa7fcbe7404d5c60e26bff1a0c8b8aa1f72ced49e7dd0210fe288fb7fe`, checked against the official Hub's LFS metadata. A normal Hub download stalled; the official HTTPS fallback completed with size and SHA256 verification. No API inference service is used.
- Manual KV-cached greedy generation produced exactly the same 32 token IDs as `Transformers.generate` for the saved reference prompt. Greedy decoding disables sampling and uses repetition penalty 1.0. This verifies this generation path; it does not establish semantic accuracy for arbitrary answers.

## Automated and operational checks

Seventeen LLM-specific tests passed: token ordering/reference output, static and continuous admission behavior, active/queued cancellation, resource-budget admission, exact-prefix cache bounds, duplicate IDs, concurrent router selection, health exclusion, remaining-work estimation, conversation validation, token-bucket refill/client isolation, budget release, and checker corruption detection. The complete workspace suite passed all 23 tests, including the six existing Kafka tests. Python compilation and `pip check` passed.

The HTTP admission smoke test sent 12 simultaneous client-A requests: four completed and eight were rejected with actual HTTP 429 plus Retry-After. A fresh retry after capacity was released completed successfully. See `llm-results/admission-http-smoke.json`.

The final application was exercised in the browser for English streaming chat, multi-turn context and Stop generating. After Worker 1 was stopped through the UI, a new real-model request completed on Worker 2; Worker 1 was then restarted and both became healthy. Cancellation, routing, worker failure, quota handling and cleanup also have independently checked process-run evidence below. Browser console inspection found no application errors. Application screenshots are `tokenflow-chat.jpg` and `tokenflow-service.jpg`; responsive layout was inspected during browser validation.

## Real-model functional scenarios

| Scenario | Run | Observed outcome |
| --- | --- | --- |
| Traffic surge, 100 requests at 100/s | `20261014T082056-99a1875a` | 8 completed; 92 explicitly rejected by client concurrency limits; no model execution for rejected requests. |
| Two clients, 24 requests at 12/s | `20261014T082203-b1ffb2e5` | 8 completed; 16 explicitly rejected; independent client admission budgets. |
| Kill worker 1 during 16 requests | `20261014T082216-021608ab` | 10 completed; 6 explicitly failed; health detection 0.574 s after the stop request; later work completed on worker 2. |
| Cancel every fourth request, 12 requests | `20261014T082250-6a348e4e` | 9 completed; 3 cancelled; no remaining active/queued/KV or gateway reservations. |

All four runs passed lifecycle/output checks and verified the intended scenario. `all_completed` is deliberately false for rejection/failure/cancellation scenarios. The latency of eight successful requests in a surge is not evidence of capacity to serve all 100.

## Required routing comparison on real inference

Experiment `experiment-7f5bdda5f5` used identical request content, arrival offsets, model, output limits and resources: 16 requests, 3 requests/s, two workers, four active slots per worker. Both policies ran three times, alternating order. All six runs completed all requests and passed independent checks. Values are mean ± sample standard deviation **across runs**, not confidence intervals.

| Policy | Successful requests/s | TTFT P95 (ms) | Completion P95 (ms) |
| --- | --- | --- | --- |
| Round robin | 0.734 ± 0.057 | 8,575 ± 519 | 17,353 ± 1,771 |
| Least outstanding | 0.752 ± 0.103 | 8,271 ± 1,607 | 17,020 ± 3,178 |

The mean differences are small compared with run variation. These measurements do not establish a reliable winner. The offered load exceeded measured completion throughput and queues formed; shared CPU resources, per-sequence forward execution and request lengths all affect results. Each per-run p95 is based on only 16 successful requests, so the tail estimate is coarse. No linear-scaling claim is made.

## Controlled simulator comparisons

Each suite has 12 valid runs: 48 fixed requests, arrival rates 6 and 18 requests/s, two policies, three repeats, alternating policy order. Both use two workers and four active slots per worker. All 1,152 requests across the two suites completed and passed output/lifecycle checks.

| Experiment | Rate | Configuration | Successful requests/s, mean ± SD | TTFT P95, mean ± SD (ms) |
| --- | --- | --- | --- | --- |
| Routing | 6 | Round robin | 3.989 ± 0.184 | 1,521 ± 386 |
| Routing | 6 | Least outstanding | 4.027 ± 0.142 | 1,299 ± 106 |
| Routing | 18 | Round robin | 4.549 ± 0.062 | 4,788 ± 43 |
| Routing | 18 | Least outstanding | 4.631 ± 0.087 | 4,903 ± 102 |
| Scheduling | 6 | Static cohort | 2.945 ± 0.029 | 6,392 ± 301 |
| Scheduling | 6 | Continuous admission | 3.625 ± 0.191 | 1,893 ± 461 |
| Scheduling | 18 | Static cohort | 2.985 ± 0.088 | 10,941 ± 297 |
| Scheduling | 18 | Continuous admission | 3.963 ± 0.110 | 5,433 ± 121 |

Routing is not uniformly better on all metrics. Continuous admission reduces the static-cohort waiting penalty under the selected simulation cost model. These are measured application runs of a documented timing model; they do not show fused batching speedups on the actual CPU model. Both offered rates create service pressure and should not be described as a complete light-load-to-saturation sweep. Absolute values from separate suites should not be compared as if collected simultaneously.

The simulator also demonstrated prefix-cost reuse (704 reused tokens), explicit cancellation and worker failure, with independent checks. Prefix caching reduces prefill cost only; it does not cache generated answers.

## Reproduce and inspect

Saved raw runs, workload/configuration JSON, request CSV, traces, pressure samples, checks, aggregated statistics and PNG/SVG figures are under `docs/llm-results/`. The large model weights remain in the ignored `.runtime/` directory and are fetched by a pinned download command.

```powershell
.\.venv\Scripts\python.exe -m llm_lab check docs\llm-results\20261014T082216-021608ab
.\.venv\Scripts\python.exe scripts\plot_llm_results.py docs\llm-results\experiment-7f5bdda5f5
.\.venv\Scripts\python.exe scripts\plot_llm_results.py docs\llm-results\experiment-99c6d832b6
.\.venv\Scripts\python.exe scripts\plot_llm_results.py docs\llm-results\experiment-0abffed824
```

The plotting command rechecks raw evidence and request content before regenerating statistics. Throughput includes queueing/drain time and trace/HTTP overhead. Queue delays are worker-local; TTFT/completion use one client clock. Process pressure is sampled and approximate. Model quality, real fused continuous batching, tensor parallelism, production authentication, GPU memory accounting, multi-region failover and million-user capacity are outside the verified scope.

Initial development exposed cross-run request-ID reuse and a changed Transformers configuration attribute. Both were corrected, and subsequent evidence was collected after the relevant fixes. Earlier development runs with rejected requests are retained in ignored runtime output rather than included as valid comparison trials. Presentation-feedback changes and the final 3–4 page report remain later course deliverables.
