# TokenFlow: Distributed LLM Serving and Load Balancing

**CISC3010 individual project, Topic 14** · CHEONG KIN NGAI (Bankey)

TokenFlow is a small inference service with one gateway and a configurable pool of independent workers. It serves a real Qwen2.5-0.5B-Instruct model on CPU, streams generated tokens, and exposes queues, routing choices and worker execution. The central question is: **how do routing and worker scheduling affect throughput and response time when short and long requests share a service?**

The default demo uses two worker processes on one computer, each with a full model copy. This shared-host deployment illustrates independent processes and partial worker failure. Cross-host fault tolerance and production-scale capacity have not been established.

## Start here

| For the reviewer | Where to look |
| --- | --- |
| Report: architecture, evidence and limitations | [Final report (PDF)](report/TokenFlow_Final_Report.pdf) · [editable source](report/TokenFlow_Final_Report.md) |
| Working product demonstration | [3:30 recording](demo/TokenFlow_Demo.mp4) · [captions](demo/TokenFlow_Demo.srt) |
| Setup, request lifecycle and controls | [Full service guide](docs/LLM_README.md) |
| Raw data, experiments and figure regeneration | [Evidence guide](evidence/README.md) |
| Tests and verification | [Correctness and tests](#correctness-and-tests) |
| Source attribution and AI use | [AI_USE.md](AI_USE.md) · [paper-to-code notes](docs/LLM_PAPER_NOTES.md) |

The recording shows actual local inference at its recorded speed. It demonstrates chat, routing, admission, model execution, cancellation and recovery. The performance comparisons below use separate controlled experiments.

## Architecture

```text
Chat / workload generator
           |
           v    HTTP requests + streamed token events
       Gateway process
  admission | routing | health | tracing
           |
     +-----+-----+
     v           v
  Worker 1    Worker 2       independent processes, same host
  FIFO queue  FIFO queue
  scheduler   scheduler
  Qwen copy   Qwen copy      request-local KV state
     \           /
      +-- logs --+------> independent checker, metrics and figures
```

The gateway selects a healthy worker using round robin or least outstanding requests. Within a worker, continuous admission fills freed slots at iteration boundaries. Selective batching combines suitable operations across active requests while keeping Attention and KV state request-local. These are three distinct decisions. The simulator has its own documented timing model; simulation results are labeled separately from real-model measurements.

## Run the demo

**Validated environment:** Windows, Python 3.13.9, Intel Core Ultra 5 338H (12 logical CPUs), approximately 31.5 GiB RAM. The real model is `Qwen/Qwen2.5-0.5B-Instruct` in FP32. It needs about 1 GB of downloaded weights in addition to Python dependencies and runtime memory. A GPU is not required. The model revision and packages are pinned in [the service guide](docs/LLM_README.md) and [requirements-llm.txt](requirements-llm.txt).

From the repository root in PowerShell:

```powershell
# Real Qwen inference; first run creates .venv and downloads dependencies/weights.
.\scripts\start-llm.ps1 -Backend cpu-model -Port 8800 -Workers 2

# Or start the standard-library simulator without model downloads.
.\scripts\start-llm.ps1 -Backend simulator -Port 8790 -Workers 2
```

Open <http://127.0.0.1:8800> for the model or <http://127.0.0.1:8790> for the simulator. Start them in separate terminals. The gateway port and following worker ports must be free: 8801-8802 or 8791-8792. Use `Ctrl+C` for orderly shutdown. Allow time for initial model loading and warmup.

Send a chat request, open **Service status** to inspect queues or select a routing policy, and open **Execution** to inspect a saved model iteration. The worker-stop control demonstrates partial failure. Restart is manual; an interrupted answer reports failure and is not silently replayed.

For a small command-line example, leave the simulator running and send the two checked-in [sample prompts](samples/requests.json):

```powershell
.\.venv\Scripts\python.exe scripts\send_sample.py --url http://127.0.0.1:8790
```

For the real backend use `--url http://127.0.0.1:8800`. The command prints each sample's assigned worker, first-token time, output length and final response.

Other operating systems have not been verified for this submission. The simulator uses only Python's standard library; plotting additionally requires Matplotlib. Model weights and local runtime files are downloaded rather than committed.

## Required experiment: routing

The main comparison uses the **real Qwen backend** with two workers and the same short/long workload under round robin and least outstanding. Requests arrive at fixed intervals without waiting for earlier completions: one or three requests per second. There are 120 requests per run, six paired repeats per policy and arrival rate, and 2,880 requests in this comparison. Worker count, resource limits, scheduling, model execution and request content are held fixed within each pair. Policy order alternates between repeats.

| Arrival rate | Policy | Requests/s | P95 first token, s | P95 completion, s |
| --- | --- | ---: | ---: | ---: |
| 1/s | Round robin | 0.964 ± 0.017 | 3.72 ± 1.29 | 13.13 ± 1.85 |
| 1/s | Least outstanding | 0.971 ± 0.005 | 2.37 ± 0.29 | 11.53 ± 1.09 |
| 3/s | Round robin | 1.294 ± 0.061 | 45.44 ± 4.40 | 52.63 ± 4.76 |
| 3/s | Least outstanding | 1.269 ± 0.057 | 45.69 ± 2.75 | 53.34 ± 3.73 |

Values are means ± sample standard deviations **across runs**, with P95 calculated within each run. At 1/s, least outstanding reduced mean trial P95 time to first token. At both rates, the paired throughput-difference interval includes zero; the experiment does not establish a reliable throughput winner or prove equivalence. At 3/s, worker slots were full in about 90-93% of samples, while gateway process CPU was about 11% of one logical core. These observations show worker-side pressure, not proof that the entire CPU or memory subsystem was saturated.

A separate, deliberately alternating long/short workload probes sensitivity to request order. It has 16 runs and 1,024 requests and should not be interpreted as typical production traffic. The complete routing archive contains **40 runs and 3,904 requests**; the required random-mix comparison above is its 24-run subset.

## Other experiments

- **Selective execution, real Qwen:** with 24 requests per run and three runs per setting, throughput rose from 0.787 to 1.154 requests/s, a 46.7% increase in this test. This compares shared and separate model operations; it is not a routing gain.
- **Chunked prefill, real Qwen:** P95 inter-token gaps rose from 544.6 to 854.6 ms while P99 decreased from 1,962.9 to 913.7 ms. There were three repeats, and P99 was inspected after the initial analysis. These are workload-specific descriptive results.
- **Static versus continuous admission, simulator:** a separate controlled comparison tests when waiting requests enter workers under a stated timing model. It is not a real-model speedup claim.
- **Worker failure, real Qwen:** in one 16-request run, nine completed and seven failed explicitly; detection was 0.554 s in that run. New requests used the surviving worker. Cancellation was a separate 12-request test.

The [evidence guide](evidence/README.md) identifies the raw run directories, settings, scripts and archives for each claim. Outputs and figures can be independently checked and regenerated.

## Correctness and tests

```powershell
# Complete automated suite, including the earlier Kafka lab tests.
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

# Recheck all 40 archived real-model routing trials and regenerate their figure.
.\.venv\Scripts\python.exe -m pip install -r requirements-plots.txt
.\.venv\Scripts\python.exe scripts\verify_routing_evidence.py
```

On 28 October, all **32 automated tests** passed ([test log](evidence/verification/automated-tests.log)). A clean staged checkout started the simulator and real Qwen, and both completed requests with two healthy workers ([smoke checks](evidence/verification/clean-checks.json)). The real-model launcher was also checked with freshly installed Python dependencies and locally cached pinned weights; a full first-time weight download was not repeated. The routing verifier rechecks workload IDs, lifecycle, token order, execution accounting, cleanup, workload settings, P95 values and exact greedy token IDs within each workload family. Twelve real-model reference cases also matched Transformers-generated token IDs. These checks cover the tested cases.

To repeat a small simulator comparison, start the simulator and run the following in another terminal:

```powershell
.\.venv\Scripts\python.exe -m llm_lab experiment --url http://127.0.0.1:8790 --kind batching --repeats 3 --count 48 --rates 6,18
```

New suites and raw runs are written under `runs/llm/`; new observations may differ from archived measurements. See [the evidence guide](evidence/README.md) for checking and plotting commands.

## Reading and attribution

The main reading is Yu et al., [Orca: A Distributed Serving System for Transformer-Based Generative Models](https://www.usenix.org/conference/osdi22/presentation/yu), OSDI 2022. Orca's iteration-level scheduling motivates continuous admission and selective batching inside a worker. The required routing experiment instead changes the gateway's choice of worker for a whole request. TokenFlow uses full CPU replicas and existing PyTorch/Transformers primitives; it does not reproduce Orca's GPU model-parallel engine, PagedAttention, model training or a provider's private infrastructure.

The project uses pretrained Qwen weights, PyTorch and Transformers. Codex provided substantial assistance across architecture, implementation, tests, experiments and documentation; the disclosure and checks are in [AI_USE.md](AI_USE.md). The earlier Kafka laboratory is preserved in [docs/KAFKA_LAB.md](docs/KAFKA_LAB.md).
