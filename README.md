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

## Environment and installation

The experiments were recorded on Windows with Python 3.13.9, an Intel Core Ultra 5 338H with 12 logical CPUs, and approximately 31.5 GiB RAM. Both Qwen replicas share that CPU host. A GPU is not required. Other platforms have not been verified for this submission.

The following commands use PowerShell. Install Git and Python 3.13, then clone the repository and create a virtual environment. All subsequent commands start from the `code/` directory unless stated otherwise.

```powershell
git clone https://github.com/2646044472/cisc3010.git
cd cisc3010\code
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-llm.txt -r requirements-plots.txt
.\.venv\Scripts\python.exe -c "import sys, torch, transformers, matplotlib; print(sys.version); print(torch.__version__, transformers.__version__, matplotlib.__version__)"
```

The requirements files pin PyTorch, Transformers and Matplotlib. The simulator itself uses the Python standard library. Installing the model dependencies is also necessary to run the complete test suite, including the real-model component tests.

The CPU backend uses `Qwen/Qwen2.5-0.5B-Instruct`, revision `7ae557604adf67be50417f59c2c2f167def9a775`. The first model startup downloads approximately 1 GB of weights into `code/.runtime/qwen25-05b/`. Allow additional disk space for dependencies and memory for two full FP32 replicas. Internet access is needed for the initial dependency and model downloads. The full first-time model download was not repeated during the recorded clean-checkout validation.

## Start the service and check a request

In the first PowerShell window, start the real model from `code/`. The gateway uses port 8800 and its two workers use 8801 and 8802.

```powershell
.\scripts\start-llm.ps1 -Backend cpu-model -Port 8800 -Workers 2 -Threads 2
```

Wait for both workers to load, then open http://127.0.0.1:8800. In a second PowerShell window, change to the same `code/` directory and run the checked-in sample prompts.

```powershell
.\.venv\Scripts\python.exe -m llm_lab health --url http://127.0.0.1:8800
.\.venv\Scripts\python.exe scripts\send_sample.py --url http://127.0.0.1:8800
```

The health command reports two healthy workers. The sample command prints each request's status, worker, token count, first-token time and response. The application also exposes queues, routing policy, execution steps and worker controls. Stop the service with `Ctrl+C` in the first window.

To try the same request flow without model weights, start the simulator in a separate window and use its port. The worker ports are 8791 and 8792.

```powershell
.\scripts\start-llm.ps1 -Backend simulator -Port 8790 -Workers 2
```

From another window in `code/`:

```powershell
.\.venv\Scripts\python.exe -m llm_lab health --url http://127.0.0.1:8790
.\.venv\Scripts\python.exe scripts\send_sample.py --url http://127.0.0.1:8790
```

The browser address is http://127.0.0.1:8790. Run each backend on its stated port and make sure its gateway and worker ports are free. The [service guide](code/docs/LLM_README.md) documents configuration and troubleshooting.

## Run the tests

With the dependencies installed as above, run this command from `code/`:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The suite covers gateway and worker behavior, scheduling, cleanup, correctness checking and small Qwen2 model operations. It also includes tests from the earlier Kafka lab. The 2 November verification records 32 passing tests. Without the model dependencies, the Qwen2 component tests are skipped rather than exercised.

## Verify the reported experiments

The archived results can be checked without running inference again. From `code/`, run:

```powershell
.\.venv\Scripts\python.exe scripts\verify_routing_evidence.py
```

The verifier reads `code/evidence/routing/raw-routing.zip`, checks request lifecycles and token order, validates workload and configuration consistency, and recalculates latency percentiles. It checks 40 runs and 3,904 requests, including the separate order diagnostic. The 24-run primary comparison is the random-mix subset. The command prints a JSON verification summary and writes `summary.csv`, `paired-effects.csv`, `verification.json`, and plots under `code/verification-output/routing/`.

To recalculate the additional execution, prefill and simulator comparisons, extract their archive to a fresh directory and run the supplied analysis scripts:

```powershell
.\.venv\Scripts\python.exe -m zipfile -e evidence\additional\raw-additional-experiments.zip evidence\unpacked
.\.venv\Scripts\python.exe scripts\plot_llm_results.py evidence\unpacked\experiment-a501f3f100
.\.venv\Scripts\python.exe scripts\plot_llm_results.py evidence\unpacked\experiment-bee76f24b0
.\.venv\Scripts\python.exe scripts\plot_llm_results.py evidence\unpacked\experiment-submission-20261028
.\.venv\Scripts\python.exe scripts\summarize_simulator_classes.py evidence\unpacked\experiment-submission-20261028
```

The plot scripts check the extracted runs and write `aggregates.csv`, `aggregates.json`, and comparison figures in each extracted suite directory. The last command writes `verification-output/simulator/class-summary.csv`. Use a fresh extraction directory to avoid overwriting results you want to keep. The [evidence guide](code/evidence/README.md) explains each archive and its run IDs.

## Run new experiments

The following commands collect new measurements. Leave the service running in the first window and run the experiment from a second window in `code/`. Results depend on machine resources and load, so new timings can differ from the archived observations.

### Required routing comparison on real Qwen

Start the CPU backend as above with two workers and two threads per worker, then run:

```powershell
.\.venv\Scripts\python.exe -m llm_lab experiment --url http://127.0.0.1:8800 --kind routing --repeats 6 --count 120 --rates 1,3
```

The driver uses seed 3010 and fixed-interval open-loop arrivals. It alternates round robin and least outstanding across six paired repeats at each rate, for 24 trials and 2,880 requests. Each trial warms both workers. The backend uses four slots per worker, a 4,096-token reservation budget and a 128-token prefill allowance. Short and long outputs are capped at 16 and 48 tokens. At 1 and 3 requests per second, dispatch alone takes roughly 32 minutes in total; model generation, warmup and analysis add time.

The command prints each completed trial and the final `runs/llm/experiment-...` suite path. That directory contains `results.json` and `summary.csv`; individual `runs/llm/<run-id>/` directories contain configurations, workloads, request results and traces. The verifier above is for the checked-in archive, while these newly collected runs can be analyzed using `scripts/plot_llm_results.py` with the printed suite path.

### Static versus continuous admission in the simulator

Start the simulator as above, then run:

```powershell
.\.venv\Scripts\python.exe -m llm_lab experiment --url http://127.0.0.1:8790 --kind batching --repeats 3 --count 48 --rates 6,18
```

This runs 12 trials with 48 requests each and a 32-token prefill allowance. The printed suite and per-run directories contain the same kinds of results and traces. For example, replace the placeholder below with the printed suite path to regenerate aggregates and a plot:

```powershell
.\.venv\Scripts\python.exe scripts\plot_llm_results.py runs\llm\experiment-REPLACE_WITH_RUN_ID
```

Simulator timings follow the documented service-cost model and are reported separately from real-Qwen measurements. The [experiment evidence guide](code/evidence/README.md) also covers the real-model execution and prefill comparisons, fault runs, and per-length summaries.

## Reported results

The primary routing study replays 2,880 requests across 24 real-model trials. At one request per second, least outstanding reduced mean trial P95 time to first token from 3.72 to 2.37 seconds. The throughput comparison did not establish a reliable winner at either tested rate. The report gives workload details, uncertainty and limitations for these and the separate scheduling experiments.

## Reading and attribution

The main reading is Yu et al., [Orca: A Distributed Serving System for Transformer-Based Generative Models](https://www.usenix.org/conference/osdi22/presentation/yu), OSDI 2022. TokenFlow implements request routing, worker scheduling, lifecycle handling and verification around pretrained Qwen, PyTorch and Transformers. The report describes the project contributions and tool-assisted development.
