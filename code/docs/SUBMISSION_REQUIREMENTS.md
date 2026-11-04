# Submission requirements and evidence

This guide maps the submitted work to the [assignment snapshot](CISC3010_Distributed_Systems_Individual_Project.md) and [proposal](proposal.md). It is a reading aid, not an additional performance claim. The snapshot was retrieved on 12 October 2026; this audit does not establish whether the instructor subsequently changed the requirements.

## Assignment core: Topic 14

| Requirement | Submitted implementation or evidence | Report location |
| --- | --- | --- |
| Router and at least two separate inference workers; visible queues | [Gateway and process pool](../llm_lab/gateway.py), [worker queue and engine](../llm_lab/worker.py), two-worker [recording](../demo/TokenFlow_Demo.mp4) | Figure 1; Section 2 |
| Small CPU model or explicitly timed simulator; incremental responses | Real Qwen FP32 [backend](../llm_lab/backend.py); separate simulator. Workers return newline-delimited JSON over HTTP; the gateway relays client Server-Sent Events (SSE). | Sections 2, 3.1 and 4.3 |
| Round robin and least outstanding; arrival, assignment, first response, completion and output length | Gateway assignment/accounting; worker token sequence events; client observations in [raw-routing.zip](../evidence/routing/raw-routing.zip) | Sections 2, 3.2 and 5.1 |
| Same short/long mixture under both policies | Saved workload; 24 real-model trials, 120 requests per trial, six paired repeats per policy/rate. Configuration and workload checks are in [the verifier](../scripts/verify_routing_evidence.py). | Sections 3.1-3.3; Figure 2 |
| Throughput, first-token time and P95 completion | [Routing summary](../evidence/routing/summary.csv), [paired effects](../evidence/routing/paired-effects.csv), individual requests and raw traces | Figure 2; Section 3 |
| Arrival model, hardware limits and router/worker pressure | Fixed-interval open-loop arrivals at 1/s and 3/s; shared CPU, model threads, slots and token budget documented. High-load full-slot samples indicate worker pressure; gateway CPU is measured separately. Whole-host saturation is not established. | Sections 3.1, 3.3 and 6 |
| Correctness evidence | [Independent checker](../llm_lab/check.py), [archived 32-test log](../evidence/verification/automated-tests.log), [12 real-model reference cases](../evidence/additional/qwen-reference-20261028.json), raw fault and cancellation traces | Section 5 |
| Connect Orca to the implemented mechanism and explain simplifications | Iteration-level admission and selective computation inside a worker; gateway routing chooses a replica for a whole request. CPU replicas simplify Orca's GPU execution environment. | Related work; Sections 2, 4 and 6 |

The assignment explicitly permits multiple processes on one laptop. Two workers meet its minimum. More workers, a GPU, a graphical interface and a positive speedup are not requirements. The required routing study does not establish a reliable throughput winner; that is a reported result, not an omitted experiment.

## Optional extensions and proposal commitments

The assignment says **static versus continuous batching OR worker-stop recovery**. This submission includes evidence for both, with different scope:

| Item | Status and boundary | Evidence |
| --- | --- | --- |
| Static versus continuous batching | Completed in the explicitly timed simulator, as proposed. Twelve rerun trials, 48 requests each, three repeats per setting. These are not Qwen speedup measurements. | Report Section 4.3 / Figure 5; [aggregate summary](../evidence/additional/simulator-rerun-summary.csv), [short/long class summary](../evidence/additional/simulator-class-summary.csv) |
| Worker stop and recovery | Real-model failure run records nine completions and seven failures; detection is 0.554 s in that run. New traffic can use the survivor. Demo shows manual restart and model reload; partial answers do not resume. | Report Section 5.2; demo 2:50-3:30; [additional archive](../evidence/additional/raw-additional-experiments.zip) |
| Real-model scheduling stretch goal | Implemented continuous admission and selective computation. A separate three-repeat experiment compares selective with independent execution while holding admission fixed. This is not a real-model static-versus-continuous ablation. | Report Sections 4.1-4.2 / Figures 3-4; [selective execution](../llm_lab/selective.py) |
| Cancellation and worker token/KV budgets | Implemented; cancellation run checks cleanup. No production memory-management guarantee is claimed. | [Worker](../llm_lab/worker.py), [tests](../tests/test_llm_lab.py), report Sections 5.2 and 6 |
| Client quotas and controlled surge | Token-bucket, concurrency and estimated-token limits are implemented. Tests check independent client buckets and release; the recording demonstrates 429 rejection under a burst. This is not a multi-tenant production isolation benchmark. | [Admission](../llm_lab/admission.py), tests, demo 1:03-1:33 |
| Estimated remaining-work routing | The optional `token_work` heuristic exists and has a routing test. It estimates remaining requested budget, not true future generation length. No measured superiority is claimed in the final report. | `Gateway.score` and `test_work_estimator_uses_remaining_requested_budget` |
| Additional proposed metrics | Raw suite results include `tokens_s`, queue-time summaries and outcome counts; the simulator class CSV reports per-length waiting time and TTFT with variation. The four-page report prioritizes required metrics. | `random-suite/results.json` in the routing archive; suite `results.json` files in the additional archive; class-summary CSV |

The two tested routing rates represent light and overloaded conditions; they are not an exhaustive capacity curve. The main experiment deliberately avoids admission rejection. The separate burst and fault scenarios must not be pooled into successful-request latency results.

## Final deliverables

| Assignment deliverable | Where to find it |
| --- | --- |
| Source, setup, dependencies, hardware, startup, demo and experiment commands | [Main README](../README.md), [service guide](LLM_README.md), pinned requirements and [sample requests](../samples/requests.json) |
| Configuration, generators, checks, raw results and plotting scripts | [Evidence guide](../evidence/README.md), `code/llm_lab/experiment.py`, `code/llm_lab/check.py`, `code/scripts/verify_routing_evidence.py`, `code/scripts/plot_llm_results.py`, `code/scripts/build_report.py` |
| Three-to-four-page report: question, architecture, implementation, correctness, experiments, interpretation, limitations | [Four-page PDF](../../report.pdf); references fit within the same four pages |
| Changes following presentation and own additions | Report Section 7 identifies evaluation and verification added after the presentation and distinguishes implementation contributions from Qwen/PyTorch/Transformers. It reports actual changes without attributing them to unrecorded feedback. |
| AI assistance and external-code attribution | Report Section 7 and references |

The snapshot specifies **GitHub repo submission** and an explicit final deadline of **5 November**. A local ZIP is a portable copy, not evidence that the course submission has been made or that the remote repository contains the latest report. Its relative-week wording is inconsistent, so the explicit date is the planning reference.

## Why these figures are included

Each figure answers a specific question; no decorative icons or additional illustrations are needed.

| Figure | What the reader should understand |
| --- | --- |
| 1: process architecture | Which components are separate processes, which worker owns queue/model/KV state, and where HTTP requests and token responses travel |
| 2: required routing experiment | Whether the two policies differ at each load, in which metric, and how large run-to-run variation is |
| 3: model-step mechanism | Which operations share computation and why Attention/KV state remain request-local |
| 4: real execution comparison | What changes when computation is shared, separately from the routing experiment |
| 5: simulator admission comparison | How admission timing affects waiting/first-token delay under the declared simulator model |

Table 1 is intentionally a small table: it exposes the opposing P95/P99 streaming changes more directly than another plot. Trial observations remain available in the evidence even when the main figure displays only means and sample standard deviations. Standard-deviation whiskers are not confidence intervals or a standalone significance test.
