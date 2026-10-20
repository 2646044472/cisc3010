# AI use and own contributions

## Topic 14 — TokenFlow

Codex assisted with the Topic 14 proposal, research into public OpenAI/Orca/vLLM mechanisms, architecture, router and scheduler implementation, CPU-model integration, UI, tests, experiment orchestration, checker, and documentation. This assistance is substantial and must be disclosed with the submitted work.

On 20 October, Codex additionally reviewed the Orca, PagedAttention, Sarathi-Serve and DistServe papers and implemented an Orca-style Qwen2 CPU selective execution path. It reuses pretrained Qwen2 layers and Transformers Attention/cache primitives while sharing linear and MLP computation across requests. Real bounded prefill, execution traces, numerical/greedy reference checks and repeated comparative experiments were also added. Paper relationships and limitations are detailed in `docs/LLM_PAPER_NOTES.md`; current measurements are in `docs/LLM_OPTIMIZATION_RESULTS.md`.

PyTorch and Transformers provide neural-model execution and tokenizer/cache primitives. Qwen supplies the default Qwen2.5-0.5B-Instruct weights; HuggingFaceTB supplied SmolLM2 weights for the initial smoke check. The project implements worker processes, request admission and routing, token-step scheduling, bounded resource reservations, simulator prefix-cache accounting, SSE relay, cancellation and worker-failure handling, traces, independent correctness checks, and controlled experiments. It does not implement model training, GPU kernels, tensor parallelism, or production PagedAttention.

Validation includes a separate greedy-generation reference comparison, multi-process model/simulator runs, scheduler/routing tests, request-output and lifecycle checks, repeated experiments, and browser verification. Actual evidence and limitations belong in `docs/LLM_VALIDATION.md` and saved run artifacts. The student must inspect and understand the implementation, explain its assumptions, and verify the commands before submission. Cite the model, libraries, main paper and public engineering references; do not attribute this teaching implementation to OpenAI.

## Topic 9 — Replay Lab (earlier prototype)

Codex assisted with topic comparison, architecture, initial implementation, the local dashboard, deterministic crash scenarios, correctness checks and documentation.

Kafka and confluent-kafka provide the broker protocol, durable partition log and consumer-group implementation. Project additions are synthetic AI-telemetry generation, explicit commit/effect policies, abrupt-process failure and restart orchestration, transactional sink deduplication, separate attempt/effect auditing, an independent event-ID/value checker, a local observability dashboard, and controlled experiment/export scripts.

Validation consists of actual runs against a real Kafka broker, all four scenario checks, multi-process group assignments/reassignments, checker/transaction tests, and repeat consumer-count measurements. The exact results and limitations belong in the generated raw run artifacts and `docs/VALIDATION.md`; do not treat generated explanations as verified without reading those results. The student should run the commands, inspect offsets and failure windows, and be able to explain the implementation before submission.

No complete prompt history is required by the assignment. Cite Kafka, client libraries and the selected paper in the final report; record presentation-feedback changes when they exist.
