# TokenFlow

**Request Routing and Iteration-Level LLM Serving**

CISC3010 · Topic 14 · Cheong Kin Ngai (Bankey)

This project is available at [github.com/2646044472/cisc3010](https://github.com/2646044472/cisc3010).

TokenFlow is a local distributed inference service that routes concurrent requests to independent language-model workers. It makes queueing, streaming and worker behavior visible, then uses controlled experiments to examine how routing and scheduling affect response time.

[Final report](report.pdf) · [Recorded demo](code/demo/TokenFlow_Demo.mp4) · [Experiment evidence](code/evidence/README.md) · [Detailed setup](code/README.md)

## System overview

A gateway receives requests, applies admission limits and selects a healthy worker. The default deployment runs two independent worker processes, each with its own Qwen2.5-0.5B-Instruct model, request queue and generation state. Responses stream back through the gateway.

The gateway supports round-robin and least-outstanding routing. Within each worker, continuous admission fills available slots and selective execution shares suitable model operations across active requests. Worker health, request status and model-step activity are visible in the application.

```text
Client / workload generator
           |
     HTTP gateway
      /         \
Worker 1      Worker 2
      \         /
    streamed responses
```

Both workers run on one CPU host. Each holds a complete model copy. The [full service guide](code/docs/LLM_README.md) documents the API, controls and configuration.

## What is included

| Item | Location |
| --- | --- |
| Final report and results | [report.pdf](report.pdf) |
| Recorded 3:30 demo and captions | [code/demo/](code/demo/) |
| Gateway, workers and inference backend | [code/llm_lab/](code/llm_lab/) |
| Tests and sample requests | [code/tests/](code/tests/) · [code/samples/](code/samples/) |
| Raw results, traces and verification | [code/evidence/](code/evidence/) |
| Setup and experiment commands | [code/README.md](code/README.md) |

## Run locally

The validated environment is Windows with Python 3.13.9 and a CPU. The real model requires approximately 1 GB for downloaded weights, plus dependencies and runtime memory. Open PowerShell in the repository root and start one backend:

```powershell
cd code

# Real Qwen model. The first run installs dependencies and downloads pinned weights.
.\scripts\start-llm.ps1 -Backend cpu-model -Port 8800 -Workers 2
```

Open http://127.0.0.1:8800 after the workers have loaded. For a lightweight simulator that does not download model weights, use the following command from `code/`:

```powershell
.\scripts\start-llm.ps1 -Backend simulator -Port 8790 -Workers 2
```

Open http://127.0.0.1:8790 for the simulator. Use `Ctrl+C` to stop the service. The gateway port and the next two worker ports must be available. The [setup guide](code/README.md#run-the-demo) includes sample requests and additional configuration details.

## Tests and results

After starting a backend once to create the virtual environment, run the automated suite from `code/`:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The latest archived check reports 32 passing tests. The required routing study replays 2,880 requests across 24 real-model trials. At one request per second, least outstanding reduced mean trial P95 time to first token from 3.72 to 2.37 seconds. The throughput comparison did not establish a reliable winner at either tested rate.

A separate real-model execution experiment compares independent and selective computation. Simulator experiments compare static and continuous admission. The report describes their settings, variation and limitations. Detailed results and raw traces are in the [evidence guide](code/evidence/README.md).

## Reading and attribution

The main reading is Yu et al., [Orca: A Distributed Serving System for Transformer-Based Generative Models](https://www.usenix.org/conference/osdi22/presentation/yu), OSDI 2022. TokenFlow implements request routing, worker scheduling, lifecycle handling and verification around pretrained Qwen, PyTorch and Transformers. The report describes the project contributions and tool-assisted development.
