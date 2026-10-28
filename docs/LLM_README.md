# TokenFlow — Distributed LLM Serving Laboratory

**Reviewer entry point:** see the [repository README](../README.md), the [final report](../report/TokenFlow_Final_Report.pdf), and the [evidence guide](../evidence/README.md). Historical references below to `llm-results/` describe original local run locations; the submitted raw evidence is provided in the archives described by the evidence guide.

Topic 14 implementation: a configurable inference-worker pool, a request router, streaming output, an instrumented token scheduler, and reproducible short/long-request experiments. The default deployment has two real model replicas on one host, selected after a measured 1/2/4-replica comparison. The existing Kafka laboratory remains available separately.

## Start

From the repository root on Windows, using Python 3.11 or later:

```powershell
# Real CPU model; initial setup downloads about 1 GB of weights plus dependencies.
.\scripts\start-llm.ps1

# Separate standard-library simulator for controlled scheduling experiments.
.\scripts\start-llm.ps1 -Backend simulator -Port 8790
```

Open http://127.0.0.1:8790 for the simulator or http://127.0.0.1:8800 for real inference. The gateway starts two owned subprocesses on ports 8801–8802 by default. Each real worker loads its own full Qwen2.5-0.5B-Instruct model and uses two PyTorch intra-op threads and one inter-op thread. Model revision and package versions are pinned. Warmup occurs before readiness.

Use `-Workers 1`, `-Workers 2`, or `-Workers 4` to choose the pool size, and `-Threads 2` to set intra-op threads per replica. Counts from 1 to 16 are accepted, subject to available memory and CPU. For example, `.\scripts\start-llm.ps1 -Workers 4 -Threads 2`. The interface derives online counts and worker controls from the actual pool. Four workers have sixteen active slots in total, while per-client admission quotas remain independent of this capacity. Full replicas share host CPU and RAM. More replicas do not add hardware, and the service does not provide cross-host deployment, model sharding or automatic scaling. The default remains two because four brought limited throughput gains and longer tail token gaps in the current shared-host experiment. Earlier two-worker optimization measurements remain separate from the new replica-count comparison.

Cross-platform equivalent:

```text
python -m llm_lab serve --backend simulator --port 8790
python -m pip install -r requirements-llm.txt
python -m llm_lab download-model
python -m llm_lab serve --port 8800 --backend cpu-model --workers 2 --threads 2
```

Windows/Python 3.13 is the validated environment. Other operating systems are supported by the standard-library design but not yet verified. Close services with Ctrl+C; an explicit orderly stop is also available through a local POST to `/api/shutdown` with `{}`. Managed subprocesses are stopped during orderly gateway shutdown. The application has multi-turn chat, browser-local conversation history, incremental output, stop-generation, and a separate service-status page. A maximum of 20 recent non-failed messages is sent as context per turn, and request admission still enforces the worker token budget. The UI's worker-stop action deliberately terminates only the selected owned subprocess.

## What is implemented

The default Demo is an English chat application with multi-turn context, browser-local history, streaming answers, stop-generation and explicit retry after failure. **Service status** provides a compact operational view with request stages and client quotas. The UI's “Traffic surge” and “Multiple clients” scenarios generate real requests against the current backend; on the default CPU service, admitted requests execute Qwen. The maximum demonstration workload is 200 requests, not millions of users. Experimental figures remain separate for the PPT.

| Component | Responsibilities |
| --- | --- |
| Gateway process | Atomic worker selection, bounded outstanding count, four routing policies, heartbeat health observations, SSE relay, terminal accounting, experiment controller, dashboard. |
| Configurable worker processes | Independent full model copies, FIFO queues, bounded active sets, static/continuous admission, token-step execution, KV token reservations, cancellation, bounded output queues. |
| Simulator | Deterministic reference output, explicit prefill/decode costs, chunked prefill, local exact-prefix LRU cost model. |
| CPU inference backend | Real Qwen2 selective batching, shared linear/MLP work, independent Attention/KV state, bounded hybrid prefill, greedy decoding, EOS and incremental text. |
| Evidence tools | Saved workloads/configuration, client/gateway/worker JSONL, pressure samples, independent checker, per-request CSV, repeated comparisons, plot regeneration. |

The router offers round-robin and least-outstanding-request routing as required. Outstanding means assigned but not terminal, including queued and running requests. Selection and reservation happen under one lock. Completion, explicit failure, cancellation and downstream disconnect release the reservation.

Two additional policies estimate remaining work from **requested maximum output minus observed token count**, plus a weighted input-length estimate before the first token. The input weight is a documented heuristic (0.08 decode-token equivalents per whitespace token), not a calibrated production predictor. Cache-aware routing discounts the incoming request's matching simulated prefix cost. Actual future output length and reference output are not available to the router.

## Scheduling and cache semantics

Gateway admission uses per-client token buckets, concurrency limits and estimated in-flight token budgets. Demo defaults are 6 requests/s, burst 12 and at most 8 outstanding requests; clients A/B each have 2 requests/s, burst 6 and at most 4 outstanding requests. Rejections return HTTP 429 and Retry-After. Rate tokens are debited only when this simplified controller admits work. Client labels are unauthenticated local teaching identities; these budgets are not OpenAI RPM/TPM or billing semantics. Controlled routing/scheduling comparisons use an isolated benchmark plan so application quota settings do not confound required experiments. The gateway is a single point of failure.

Static scheduling admits a cohort only when the previous cohort has drained. Completed requests can return immediately, but newly queued requests cannot fill their slots until all cohort members finish. Continuous scheduling fills released slots at iteration boundaries. FIFO order is preserved; a large request waiting for KV reservations can block later queued requests. This assumption is deliberate and observable.

In the simulator, ready sequences share one modeled decode delay:

```text
decode seconds = (0.012 + 0.002 × ready sequence count) × worker speed
prefill chunk seconds = (0.003 + 0.00025 × chunk tokens) × worker speed
```

Decode is processed first, then prefill chunks are processed sequentially. Chunk size defaults to 32 whitespace tokens. This is a simplified timing model, not a GPU kernel implementation or faithful reconstruction of vLLM's mixed execution. A prefix-cache hit saves only matching prefill work. Cache entries contain exact 32-word prefix identities and token counts; they do not contain real KV tensors. The LRU cache has its own bounded token budget.

Each active request reserves `input_tokens + max_tokens` against a worker token budget. Reservations prevent overcommit and are released at termination. Actual logical context use is also shown. Neither measure is allocated GPU memory. This conservative admission rule differs from production paged-cache allocation and preemption.

The CPU backend now defaults to **real selective batching**: flatten participating tokens for shared projections, normalization and MLP, with request-local Attention, rotary positions and actual KV tensors. Decode tokens and bounded prompt chunks can share the same layer computations. One shared prefill allowance defaults to 128 tokenizer tokens per iteration. `execution=sequential` preserves independent forwards as the experimental control. This is CPU execution with existing PyTorch primitives, not a custom fused GPU kernel. See [paper mechanisms and implementation boundaries](LLM_PAPER_NOTES.md) and [current optimization measurements](LLM_OPTIMIZATION_RESULTS.md).

Cross-request prefix caching remains simulator-only. Selective execution supports the pinned full-attention Qwen2 architecture; it is not an arbitrary-model adapter. CPU inference is explicitly FP32 for numerical stability across batch shapes. The default model is `Qwen/Qwen2.5-0.5B-Instruct`, revision `7ae557604adf67be50417f59c2c2f167def9a775`. The earlier SmolLM2 smoke evidence retains its original model identity and describes the earlier sequential path. Answer quality is not guaranteed by the serving system.

## Run and check experiments

Keep the selected service running in one terminal, then use another:

```powershell
.\.venv\Scripts\python.exe -m llm_lab health
.\.venv\Scripts\python.exe -m llm_lab demo --url http://127.0.0.1:8790 --routing round_robin --count 48 --rate 12
.\.venv\Scripts\python.exe -m llm_lab demo --url http://127.0.0.1:8790 --routing least_outstanding --count 48 --rate 12
.\.venv\Scripts\python.exe -m llm_lab demo --url http://127.0.0.1:8790 --scenario batching --scheduling static
.\.venv\Scripts\python.exe -m llm_lab demo --url http://127.0.0.1:8790 --scenario cache --routing cache_aware
.\.venv\Scripts\python.exe -m llm_lab demo --url http://127.0.0.1:8790 --scenario cancel --count 16 --rate 12
.\.venv\Scripts\python.exe -m llm_lab demo --url http://127.0.0.1:8790 --scenario fault --count 24 --rate 8

# Two arrival rates, three repeats, alternating policy order: 12 runs per suite.
.\.venv\Scripts\python.exe -m llm_lab experiment --kind routing --repeats 3 --count 48 --rates 6,18
.\.venv\Scripts\python.exe -m llm_lab experiment --kind batching --repeats 3 --count 48 --rates 6,18

# Real-model smoke run and independent greedy-reference check.
.\.venv\Scripts\python.exe -m llm_lab demo --url http://127.0.0.1:8800 --count 12 --rate 3
.\.venv\Scripts\python.exe scripts\check_llm_model.py

# Substitute an actual run directory from the commands above.
.\.venv\Scripts\python.exe -m llm_lab check runs\llm\RUN_ID
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_llm_lab.py -v
```

Runs have unique IDs. Inputs and deterministic outputs are identical between configurations after removing run/request identity. Real-model requests cap long output budgets at 48 tokens; simulation uses 16/120-token short/long limits. Arrival times are fixed interval, open loop, with seed 3010 and a 30% probability of selecting a long request. Dispatch lateness is recorded to detect load-generator delay. Model weights and process startup are excluded; two warmup tokens per worker precede measurement, then caches and counters are reset.

The required checker verifies workload/result IDs, ordered non-duplicated tokens, output limits, one assignment and terminal outcome, worker/client completion evidence across every replica, deterministic simulator output, and no gateway/active-slot/KV reservation leaks. Deliberate fault/cancel runs may pass lifecycle checks while `all_completed` is false. `scenario_verified` separately checks the expected observation. A worker killed during generation causes explicit failures; subsequent requests are routed to healthy surviving workers after failure detection. Fault and heterogeneous-worker experiments require at least two configured replicas. No partial-response replay or seamless recovery is claimed.

### Replica-count comparison

See [the measured 1/2/4-replica tradeoff](LLM_SCALING_RESULTS.md) for current results and four-replica regression evidence.

Stop other real-model services before running this local capacity experiment so their model processes do not compete with the measured cluster:

```powershell
.\.venv\Scripts\python.exe scripts\benchmark_worker_scaling.py --worker-counts 1,2,4 --repeats 3 --count 24 --rate 6
```

The script owns a temporary gateway on port 8900 and starts each pool separately, alternating ascending/descending replica counts across repeats. It keeps prompts, output limits, arrival offsets, routing, per-worker threads and scheduling fixed, warms every model, checks all traces and compares exact output token IDs across runs. Startup is excluded from throughput. Each replica adds four active slots and two compute threads, so total slot/thread budgets grow. This measures replication on a shared host, not scalability across separate machines. Saved contracts, summaries and raw run references live under `runs/llm/scaling-TIMESTAMP/`. A single repetition is an exploratory observation, not evidence of a stable capacity gain.

## Measurements and artifacts

Per-run output under `runs/llm/RUN_ID/`:

- `config.json`, `workload.json`: environment, actual worker configuration, model identity, workload and service-cost assumptions.
- `client.jsonl`, `gateway.jsonl`, `worker-N.jsonl`, `worker-N-iterations.jsonl`: request, assignment, prefill, token, terminal and execution traces for every configured replica.
- `samples.jsonl`, `control.jsonl`: queue/active/KV pressure and process CPU time samples, plus fault/health transitions when present.
- `requests.json`, `requests.csv`: client TTFT, completion latency, worker-local queue delay, output and outcome.
- `cleanup.json`, `check.json`, `result.json`: resource-release evidence, correctness, metrics, and scenario observations.

Throughput is successful requests or successful-request output tokens divided by the measured interval from first scheduled dispatch to final client outcome. TTFT and latency use the same client monotonic clock; p95 uses linear interpolation of sorted observations. Successful latency distributions exclude failed, cancelled and rejected requests; their counts remain visible. Worker queue time subtracts two timestamps from the same worker. Pressure samples occur every 250 ms; worker health observations are periodic and therefore approximate, not exact instantaneous telemetry. CPU time is process-level instrumentation, not pure inference-kernel time.

`/metrics` exposes Prometheus-style worker gauges and generated-token counters. Counters reset when an idle worker is reconfigured; they are scoped to its current configuration/run, rather than persistent process-lifetime totals.

Interpret observed queues, slot occupancy, CPU time and dispatch lateness together. An arrival rate above observed completions/s and sustained queueing suggests service pressure; it does not prove a single hardware bottleneck. Shared CPU scheduling, Python/HTTP overhead, trace writing, and simulator sleep granularity all contribute. Simulator conclusions apply to the stated service-cost model.

## Public engineering references

- [OpenAI prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching): publicly described prefix reuse, machine locality, load and capacity considerations. This does not disclose the full OpenAI serving engine.
- [OpenAI rate limits](https://developers.openai.com/api/docs/guides/rate-limits): public quota and retry guidance; its unsuccessful-request accounting differs from this simplified limiter.
- [OpenAI streaming responses](https://developers.openai.com/api/docs/guides/streaming-responses): incremental SSE transport. TokenFlow uses its own event schema, not a drop-in OpenAI API.
- [OpenAI Prompt Caching 201](https://developers.openai.com/cookbook/examples/prompt_caching_201): cache affinity versus distribution; historical details vary with model generation.
- [Orca, OSDI 2022](https://www.usenix.org/conference/osdi22/presentation/yu): iteration-level scheduling and selective batching, the assignment's main reading.
- [vLLM optimization](https://docs.vllm.ai/en/stable/configuration/optimization/): decode priority, chunked prefill, memory and scheduling tradeoffs.
- [vLLM automatic prefix caching](https://docs.vllm.ai/en/stable/features/automatic_prefix_caching/): reuse saves prefill rather than directly accelerating decode.
- [Qwen2.5-0.5B-Instruct model card](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct): default real-model provenance; downloaded model card retained beside weights. Earlier validation also used [SmolLM2](https://huggingface.co/HuggingFaceTB/SmolLM2-135M-Instruct).

This project is inspired by public mechanisms and does not claim to reproduce undisclosed OpenAI implementation details. Own contributions and AI assistance are recorded in `AI_USE.md`. Submission and publication remain separate from local implementation.

## Presentation use

The application exposes Chat, Service status, and Execution. Execution shows actual completed model iterations: request membership, prefill/decode pieces, shared prefill allowance, measured model-step duration, and worker capacity. Each worker retains its latest 32 observations and its most recent mixed step. Selecting a step pins an explicitly labelled captured observation while capacity gauges keep updating. The QKV/Attention/MLP diagram explains the selected execution path; it is not kernel-level tracing. Reconfiguration clears the observations. No prompts or model tensors are included in this telemetry.

The Admission control tab shows actual client budgets and HTTP 429 outcomes. Run mixed workload uses 24 requests at 6/s; Send traffic burst uses 24 at 30/s. Both use continuous admission, selective execution, a shared 128-token prefill allowance, four slots and a 4096-token KV reservation budget per worker. These are functional demonstrations, not the repeated performance comparisons in the slides.

The [submitted 3:30 recording](../demo/TokenFlow_Demo.mp4) shows the product in six sections, with real inference retained at recorded speed. It is functional evidence, distinct from the repeated benchmarks. The public experiment archives include raw worker iteration traces, and `scripts/plot_llm_results.py` regenerates experiment figures and mean/sample-SD tables separately.
