# TokenFlow replica-count measurements — 22 October 2026

The application defaults to two independent Qwen2.5-0.5B-Instruct model processes after comparing 1, 2 and 4 replicas. The launcher accepts 1–16 replicas and configurable threads per replica. Four real replicas have been validated on this laptop. The accepted configuration range is not a claim that sixteen models fit in its memory.

## Controlled comparison

Windows, Intel Core Ultra 5 338H, twelve logical CPUs, approximately 31.55 GiB RAM. Qwen revision `7ae557604adf67be50417f59c2c2f167def9a775`, FP32 CPU, two intra-op threads and one inter-op thread per worker. Each worker has four active slots and a 4096-token reservation budget. Every worker owns a full model copy, request-local KV caches and a scheduler. All replicas share the host's CPU and memory.

Each trial sent the same 24 requests at six arrivals/second, with identical prompts and arrival offsets, 16/48-token output limits and 576 output tokens. Policies used least-outstanding routing, continuous admission, selective execution and a shared 128-token prefill allowance per worker iteration. The benchmark quota avoids interference from interactive-client limits. Models received two warmup tokens before each trial, followed by cache/counter reset. Startup and model loading are excluded from throughput.

Three trials per replica count ran in the order 1/2/4, 4/2/1, 1/2/4. Per-worker resources stay fixed, so total thread and slot budgets grow with replica count. The values below are means of per-trial statistics ± sample standard deviation, not confidence intervals or pooled percentiles.

| Replicas | Successful requests/s | P95 first-token time, s | P95 queue time, s | P99 token gap, ms |
| --- | --- | --- | --- | --- |
| 1 | 0.993 ± 0.013 | 16.80 ± 0.30 | 15.66 ± 0.26 | 525 ± 7 |
| 2 | 1.430 ± 0.073 | 8.24 ± 0.13 | 7.54 ± 0.33 | 642 ± 65 |
| 4 | 1.532 ± 0.110 | 6.15 ± 0.71 | 4.08 ± 0.44 | 1119 ± 26 |

Doubling replicas from two to four increased mean throughput by about 7.2% and reduced mean trial P95 first-token time by about 25.4%. The mean trial P99 token gap increased by about 74.3%. More active work reduced queueing while streams experienced longer tail gaps. These observations establish a tradeoff on this workload. They do not isolate CPU scheduling, memory bandwidth or another cause. Three small trials cannot establish a statistically reliable throughput advantage, and shared-host results do not predict linear scaling across machines. The offered rate exceeds capacity in every configuration.

The final demo default is two replicas, preserving more memory headroom and the lower observed P99 token gaps. Four replicas remain available for an explicit capacity/failure experiment. This choice follows the observed tradeoff rather than claiming that two is universally optimal. The next scale step should add compute resources or improve memory/execution efficiency, then repeat the workload sweep.

## Correctness and functional checks

All nine scaling trials completed 24/24 requests. The independent checker examined every replica's request and iteration logs, including worker 3 and worker 4, and found no token-order, assignment, execution-budget or cleanup errors. Exact greedy token IDs matched across all nine trials: 216 benchmark requests checked.

Separate four-replica regression runs:

| Scenario | Run ID | Observed outcome |
| --- | --- | --- |
| Concurrent generation | `20261022T090903-1692d85b` | 24 completed. Every worker generated output. All reservations released. |
| Stop Worker 1 during 24 requests | `20261022T091733-d3c61569` | 22 completed, 2 failed explicitly. New requests completed on healthy survivors. Observed health detection 0.024 s. |
| Cancel every fourth of 16 requests | `20261022T092233-2d5e8015` | 12 completed, 4 cancelled. No active, queued or KV reservation leaks. |

All three lifecycle checks and their expected-scenario checks passed. A single fault run's detection delay is an observation, not an availability estimate. The failed partial responses are not automatically replayed. The gateway remains a single point of failure, and replicas remain on one host.

The full automated suite passed 31 tests, including simultaneous four-worker routing, exclusion of a failed replica, fourth-worker evidence validation, invalid pool-size/port checks and cleanup when the gateway cannot bind. JavaScript syntax and Python compilation checks also passed.

An initial post-inference Windows process snapshot showed approximately 2.24 GiB working set per model process and roughly 3.78–3.83 GiB private committed memory. These are different memory measures and must not be added together. They are snapshots, not measured peak requirements. Available physical memory was approximately four GiB while all four replicas were resident. Adding model processes can exhaust headroom and induce paging. Exact use varies with the host's other applications and request mix.

## Reproduction and evidence

Stop other model services, then run:

```powershell
.\.venv\Scripts\python.exe scripts\benchmark_worker_scaling.py --worker-counts 1,2,4 --repeats 3 --count 24 --rate 6
.\scripts\start-llm.ps1 -Workers 2 -Threads 2
```

The completed suite is `runs/llm/scaling-20261022T092330/`. Its `contract.json`, `results.json`, `summary.json` and `output-consistency.json` record the setup, raw run references, variation and exact-output check. Each referenced run retains its full workload, configuration, per-request and per-worker traces and resource-cleanup evidence. A copy is archived under `docs/llm-results/`, which is excluded from Git by the existing artifact policy. The earlier 20 October optimization results remain separate two-worker comparisons.
