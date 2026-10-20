# Project Proposal — Topic 14

**Course:** CISC3010 Distributed Computer Systems  
**Student:** CHEONG KIN NGAI (Bankey), U-C3-2544-8  
**Selected topic:** 14 — Distributed LLM Serving and Load Balancing  
**Title:** TokenFlow: Distributed LLM Serving with Load-Aware Routing and Token-Level Scheduling  
**Proposal date:** 14 October 2026

## Objective

Build a local, multi-process inference service that makes request routing, queueing, and incremental generation observable. The central question is: **How do routing policy and worker scheduling affect throughput, time to first token, and tail latency when short and long generation requests share a service?**

The project will satisfy Topic 14's required comparison of round-robin and least-outstanding-request routing, then examine worker scheduling through a controlled static-versus-continuous batching experiment. The contribution will be the implemented scheduler, lifecycle handling, trace-based correctness checker, and reproducible experiments around existing model libraries.

## Architecture and implementation

```text
Workload generator / interactive client
                 |
                 v
Router process: admission, routing, streaming, request tracking
                 |
          +------+------+
          v             v
     Worker A       Worker B       Separate processes
     waiting queue  waiting queue
     active set     active set
     token scheduler and inference backend
          \             /
           v           v
      Event traces → metrics, checker, dashboard, plots
```

The deployment will use Python, HTTP communication, and two independent worker processes on one laptop. Each worker will maintain its own queue and generation state. An English chat application will provide multi-turn context, incremental answers, stop-generation and browser-local chat history. A separate service page will expose worker health, admission decisions and request lifecycle stages. Architecture and experimental figures will be presented in the slide deck rather than crowding the application Demo.

**Router.** Implement round-robin and least-outstanding-request policies. Outstanding means assigned requests that are queued or running, and counts are released only on completion, cancellation, or failure. Assignment and accounting will be atomic within the router. A token-bucket limiter and per-demo-client concurrency and estimated token budgets will reject excess traffic with HTTP 429 and Retry-After. Client labels are a local teaching mechanism; production authentication and billing are outside scope.

**Worker.** Implement request states (queued, active, completed, cancelled, failed), a token-step execution loop, and incremental responses. For a small CPU model, use existing tokenizer/model code while managing per-request generation state and KV-cache lifecycle. Token-level interleaving of independent sequences will be distinguished from a batched model forward pass.

**Backends.** Provide a clearly labelled deterministic generation simulator for controlled routing and batching experiments, plus a small real CPU language-model backend for an end-to-end demonstration. Simulator configuration will expose input-dependent prefill cost and decode-step cost as a function of active batch size; all assumptions and timing parameters will be recorded. Simulated output length will remain hidden from routing policies; policies may use only input length, requested output budget, and observable worker state. The real Demo will use pinned Qwen2.5-0.5B-Instruct on CPU. Its greedy token loop will be checked against a library reference.

## Scope and extensions

The required core is two workers, visible queues, streaming responses, both required routing policies, complete request traces, a correctness checker, and the same-workload performance comparison.

The principal extension will implement **static and continuous batching in the simulator's worker scheduler**. Static batches will admit requests together and wait for the batch to finish before admitting the next batch. Continuous scheduling will release completed slots and admit waiting requests at token-step boundaries, subject to an active-request limit. This will expose how long requests affect waiting short requests. The simulator will model prefill explicitly rather than treating newly admitted requests as having no cost.

Further extensions, after the core is validated, are a routing policy based on estimated remaining token work, per-worker cache/token budgets, cancellation cleanup, and a worker-failure demonstration. Real-model continuous batching is a stretch goal dependent on correct padding, attention masks, cache handling, and measured CPU feasibility. The project will not claim real-model batching speedups from simulator results.

## Correctness and observability

Each request will have a unique ID and trace events for arrival, admission, assignment, worker start, first token, token sequence numbers, and terminal outcome. Timing will use monotonic clocks; client-observed first-token and completion latency will use one client clock. Cross-process trace alignment will document the shared-host timing assumptions.

An independent checker will verify that every admitted request reaches one terminal outcome, has one worker assignment, produces ordered non-duplicated streamed tokens, and leaves no outstanding-count or active-slot leak. Deterministic simulation output will be checked against a reference sequence. Real-model checks will verify output limits and termination, and compare a fixed greedy-generation case against a sequential reference using numerical tolerance where appropriate. Operational failures and admission rejections will be reported separately from successful latency measurements.

## Experimental plan

1. **Required routing experiment:** Replay one saved trace of short and long requests under round-robin and least-outstanding routing. Sweep configured arrival rates from light load toward saturation. Hold worker count, backend, scheduling policy, request trace, output limits, and resource limits constant within each comparison.
2. **Scheduling experiment:** Fix the routing policy and compare static with continuous batching using the same simulator trace, active-slot limit, and service-cost model. Report per-length-class waiting time and first-token latency as well as aggregate results.
3. **Application extensions:** Demonstrate independent client quotas and rejection under a controlled traffic surge. Stop one worker during a replay. Measure detection time, failed/incomplete requests, and routing changes. Already streamed requests will receive an explicit failure outcome rather than an unsupported seamless-recovery claim.

Measurements will include successful requests/s, delivered output tokens/s, client-observed time to first token, p95 completion latency, queue waiting time, admission rejection rate, and error rate. Runs will include warmup, repeated trials with alternating policy order, and enough observations to interpret p95. Raw per-request data and run-level variation will be retained. Instrumentation will distinguish router queueing and worker queueing, record CPU/thread limits, and identify observed saturation. No speedup is assumed in advance, especially for multiple processes sharing one CPU.

## Milestones and deliverables

| Date | Planned result |
| --- | --- |
| 15 October | Submit topic preference and proposal through the course's confirmed submission channel. |
| 16–18 October | Establish two-process workers, simulator, streaming, required routing policies, and trace checker; evaluate a small CPU model. |
| 19–22 October | Complete the required routing experiment and a working demo; implement and validate simulator scheduling comparison as time permits. |
| 23–25 October | Stabilize the presentation demo, repeat measurements, prepare plots, and rehearse explanations. |
| 26 October | Individual presentation, assigned slot 3. |
| 27 October–5 November | Address feedback, complete validated extensions, and submit final code and report. |

Deliverables will include source code, architecture diagram, pinned dependencies/model configuration, startup and experiment commands, saved workloads, fault controls, correctness checks, raw traces, plotting scripts, sample results, and a 3–4 page report. AI assistance and external code will be attributed, with the checks used to validate them. This document describes proposed work; implementation and performance claims will be based on completed checks and recorded results.

## Reading and relationship to the project

The main reading is **Orca: A Distributed Serving System for Transformer-Based Generative Models** (OSDI 2022), https://www.usenix.org/conference/osdi22/presentation/yu. Its iteration-level scheduling motivates admitting and retiring requests at generation-step boundaries. Request routing between workers and scheduling within a worker are distinct mechanisms and will be evaluated separately. The local CPU implementation and timing simulator will simplify Orca's production execution environment; they will not reproduce its GPU system or reported performance.

Assignment requirements are based on `CISC3010_Distributed_Systems_Individual_Project.md`, the local snapshot retrieved on 12 October 2026. The explicit final deadline of 5 November is used for planning; the assignment's conflicting relative-week wording and proposal submission channel require course clarification.
