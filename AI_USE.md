# AI use and own contributions

## Topic 14 — TokenFlow

Codex assisted with the Topic 14 proposal, research into public OpenAI/Orca/vLLM mechanisms, architecture, router and scheduler implementation, CPU-model integration, UI, tests, experiment orchestration, checker, and documentation. This assistance is substantial and must be disclosed with the submitted work.

On 20 October, Codex additionally reviewed the Orca, PagedAttention, Sarathi-Serve and DistServe papers and implemented an Orca-style Qwen2 CPU selective execution path. It reuses pretrained Qwen2 layers and Transformers Attention/cache primitives while sharing linear and MLP computation across requests. Real bounded prefill, execution traces, numerical/greedy reference checks and repeated comparative experiments were also added. Paper relationships and limitations are detailed in `docs/LLM_PAPER_NOTES.md`; current measurements are in `docs/LLM_OPTIMIZATION_RESULTS.md`.

PyTorch and Transformers provide neural-model execution and tokenizer/cache primitives. Qwen supplies the default Qwen2.5-0.5B-Instruct weights; HuggingFaceTB supplied SmolLM2 weights for the initial smoke check. The project implements worker processes, request admission and routing, token-step scheduling, bounded resource reservations, simulator prefix-cache accounting, SSE relay, cancellation and worker-failure handling, traces, independent correctness checks, and controlled experiments. It does not implement model training, GPU kernels, tensor parallelism, or production PagedAttention.

Validation includes a separate greedy-generation reference comparison, multi-process model/simulator runs, scheduler/routing tests, request-output and lifecycle checks, repeated experiments, and browser verification. Actual evidence and limitations belong in `docs/LLM_VALIDATION.md` and saved run artifacts. The student must inspect and understand the implementation, explain its assumptions, and verify the commands before submission. Cite the model, libraries, main paper and public engineering references; do not attribute this teaching implementation to OpenAI.

On 22 October, Codex extended the fixed two-worker deployment into a configurable pool of 1–16 model processes, generalized UI counts and per-replica evidence checks, and added a reproducible shared-host replica-count benchmark. Four real replicas were tested. The final demo default remains two after measuring limited throughput gains and worse tail token gaps at four. Each replica still holds a complete model. This does not implement automatic scaling or multi-host orchestration.

On 23 October, Codex added bounded observations from real worker iterations and an Execution inspector for explaining prefill/decode membership, selective execution and resource release. It also recorded real-model admission, cancellation and worker-failure scenarios, edited a 77-second presentation video, and aligned the demo slide and English speaker notes. Displayed iteration membership is checked against the saved worker trace. These captures are functional evidence and do not replace the repeated benchmarks.

On 28 October, Codex assisted with the final repository organization, four-page report, evidence packaging, portable routing verifier, and short/long simulator analysis. All 32 automated tests were rerun, the 40 archived routing runs were rechecked against their raw traces, 12 Qwen reference cases were rerun, and a separate 12-trial simulator admission comparison was repeated. The real-model and simulator results remain separate. No specific presentation feedback was reported; the submission records that fact rather than attributing changes to invented comments.

## Topic 9 — Replay Lab (earlier prototype)

Codex assisted with topic comparison, architecture, initial implementation, the local dashboard, deterministic crash scenarios, correctness checks and documentation.

Kafka and confluent-kafka provide the broker protocol, durable partition log and consumer-group implementation. Project additions are synthetic AI-telemetry generation, explicit commit/effect policies, abrupt-process failure and restart orchestration, transactional sink deduplication, separate attempt/effect auditing, an independent event-ID/value checker, a local observability dashboard, and controlled experiment/export scripts.

Validation consists of actual runs against a real Kafka broker, all four scenario checks, multi-process group assignments/reassignments, checker/transaction tests, and repeat consumer-count measurements. The exact results and limitations belong in the generated raw run artifacts and `docs/VALIDATION.md`; do not treat generated explanations as verified without reading those results. The student should run the commands, inspect offsets and failure windows, and be able to explain the implementation before submission.

No complete prompt history is required by the assignment. Cite Kafka, client libraries and the selected paper in the final report; record presentation-feedback changes when they exist.
