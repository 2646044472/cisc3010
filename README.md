# TokenFlow

**Request Routing and Iteration-Level LLM Serving**

CHEONG KIN NGAI (Bankey) · CISC3010 · Topic 14

This is the GitHub repository for the TokenFlow course project: [github.com/2646044472/cisc3010](https://github.com/2646044472/cisc3010). It contains the source code, final report, demo and experimental evidence. If you are reading an extracted ZIP, the same project is available online at this link.

TokenFlow is a local inference service with an HTTP gateway and two independent Qwen2.5-0.5B-Instruct worker processes. It makes routing, queueing, incremental generation and worker failure observable, and evaluates their effects through controlled experiments on a shared CPU host.

**[Read the report](report.pdf)** · **[Watch the demo](code/demo/TokenFlow_Demo.mp4)** · **[Code and setup](code/README.md)** · **[Experimental evidence](code/evidence/README.md)**

## Repository contents

```text
README.md       Project overview and quick start
report.pdf      Four-page final paper
code/           Source, tests, demo, raw evidence and report sources
```

The [requirements map](code/docs/SUBMISSION_REQUIREMENTS.md) connects the assignment and [proposal](code/docs/proposal.md) to the implementation, experiments and report sections.

## Main results

- **Routing:** 24 real-model trials replay 2,880 requests under round robin and least outstanding. Least outstanding lowers mean trial P95 first-token time at 1 request/s; neither tested arrival rate establishes a reliable throughput winner.
- **Selective execution:** a separate real-model comparison increases throughput from 0.787 to 1.154 requests/s in the tested configuration. This measures shared computation, not a routing gain.
- **Admission and failure:** a clearly labelled simulator compares static with continuous admission. Real-model fault and cancellation runs check explicit outcomes and resource cleanup. Restart is manual; interrupted answers do not resume.

Both model replicas share one host. The experiments do not establish production-scale capacity or cross-host fault tolerance. The paper reports the workload, hardware limits, variation and interpretation of each comparison.

## Quick start

Validated on Windows with Python 3.13.9 and a CPU. From this repository's root in PowerShell:

```powershell
cd code

# Real Qwen inference: installs dependencies and downloads pinned weights on first use.
.\scripts\start-llm.ps1 -Backend cpu-model -Port 8800 -Workers 2

# Alternatively, run the deterministic simulator without model downloads.
.\scripts\start-llm.ps1 -Backend simulator -Port 8790 -Workers 2
```

Run one command at a time, then open <http://127.0.0.1:8800> for Qwen or <http://127.0.0.1:8790> for the simulator. Use `Ctrl+C` to stop. See [the code README](code/README.md) for resource requirements, sample requests, tests and experiment commands.

## Reproduce the paper

From `code/`, with the virtual environment created by the launcher:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-report.txt
.\.venv\Scripts\python.exe scripts\build_report.py
```

This rebuilds the root `report.pdf` from [editable text and figure sources](code/report-source/) and archived results. It does not require model weights or inference. The [evidence guide](code/evidence/README.md) documents independent checks and regeneration of experiment summaries.

## Attribution

The main reading is Yu et al., *Orca: A Distributed Serving System for Transformer-Based Generative Models* (OSDI 2022). The implementation uses pretrained Qwen, PyTorch and Transformers, with project-specific routing, worker scheduling, lifecycle handling and verification. Substantial Codex assistance and its validation are documented in [AI_USE.md](code/AI_USE.md).
