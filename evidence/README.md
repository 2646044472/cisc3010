# Experiment evidence and reproducibility

Start with the [final report](../report/TokenFlow_Final_Report.pdf) and [main README](../README.md). This folder holds the submitted inputs, results, traces and figures. All workloads are synthetic. The real-model experiments use Qwen locally; no production traffic or external API is represented.

The [32-test log](verification/automated-tests.log) and [clean-checkout checks](verification/clean-checks.json) record the 28 October validation. [Raw traces for three clean-checkout smoke runs](verification/clean-smoke-runs.zip) are available separately. The fresh real-model launcher used a newly installed virtual environment and an existing pinned weight cache; the full initial weight download was not repeated.

## Which results belong to which experiment?

| Evidence | Backend | Design | Purpose |
| --- | --- | --- | --- |
| [Routing summary](routing/summary.csv), [paired effects](routing/paired-effects.csv), [figure](routing/routing-comparison.png) | Real Qwen | 24 runs, 120 requests, 6 pairs at each of 1/s and 3/s | Required round-robin vs least-outstanding comparison |
| [Order diagnostic figure](routing/order-diagnostic.png) | Real Qwen | 16 runs, 64 requests, alternating short/long order | Constructed stress case, analyzed separately |
| [Selective execution](additional/selective-batching.png) | Real Qwen | 6 runs, 24 requests, 3 repeats per execution mode | Shared vs independent computation |
| [Chunked prefill](additional/chunked-prefill.png) | Real Qwen | 6 runs, 24 requests, 3 repeats per prefill mode | Inter-token gap tradeoff |
| Original simulator suite | Simulator | 12 runs, 48 requests, 3 repeats per scheduling mode and rate | Static vs continuous admission used in the presentation |
| [28 October simulator rerun](additional/simulator-rerun-summary.csv) · [figure](additional/simulator-rerun.png) | Simulator | 12 new runs, same design | Repeat the scheduling experiment after the presentation |
| [Qwen reference check](additional/qwen-reference-20261028.json) | Real Qwen | 12 cases | Exact generated token IDs versus Transformers |

The 40 routing runs contain 3,904 requests and 108,800 output tokens. The 2,880-request random-mix comparison is the 24-run subset; the intentionally alternating diagnostic is the remaining 1,024. Do not combine the simulator results or the separate execution/prefill comparisons into that count. The model uses two FP32 replicas on one shared CPU host. See [paper relationships and limits](../docs/LLM_PAPER_NOTES.md).

## Recheck the real-model routing archive

[Download raw-routing.zip](routing/raw-routing.zip) (about 8.5 MB). It contains the saved suite manifests and every run's `config.json`, `workload.json`, `requests.json`, client/gateway/worker traces, pressure samples, output and cleanup records. The archive has no model weights. The original [per-request CSV](routing/all-requests.csv) and [validation record](routing/validation.json) are also available without extraction.

From the repository root, after starting either backend once to create `.venv`:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-plots.txt
.\.venv\Scripts\python.exe scripts\verify_routing_evidence.py
```

The verifier extracts into a temporary directory, runs the independent checker on all 40 runs, compares fixed workload and resource settings, rechecks P95 against request observations, and verifies greedy token IDs within each workload family. It writes regenerated summary and paired-difference CSVs, a verification record, and PNG/SVG plots to `verification-output/routing/`. That output is local and excluded from Git. The paired 95% intervals are a Student-t approximation on run pairs, not on individual tokens.

To collect a new deliberately alternating-order diagnostic, start a **dedicated** service in one terminal and run its driver in another:

```powershell
.\.venv\Scripts\python.exe scripts\run_order_diagnostic.py serve --backend cpu-model --port 18980
# In a second terminal, while the dedicated service is running:
.\.venv\Scripts\python.exe scripts\run_order_diagnostic.py run --url http://127.0.0.1:18980
```

Defaults reproduce the 64-request, 3/s, two-phase, four-repeats-per-policy design. The run can take substantial time on CPU. It creates new runs and does not replace the historical measurements. A four-run, eight-request **simulator smoke check** on 28 October verified both phases and policies; it is not part of the real-model 40-run result. The driver checks the generated order and refuses to treat a normal service workload as the diagnostic.

## Other raw experiments

[Download raw-additional-experiments.zip](additional/raw-additional-experiments.zip) (about 3.8 MB). The `manifest.json` inside identifies suite folders and run IDs. It includes the original simulator comparison (`experiment-0abffed824`), real selective execution (`experiment-a501f3f100`), real prefill comparison (`experiment-bee76f24b0`), 1/2/4-worker scaling, separate failure/cancellation runs, and the 28 October simulator rerun (`experiment-submission-20261028`). The `reference/` folder includes the model and FP32 numerical checks and the explicitly failed earlier BF16 numerical audit.

Unpack and reproduce the saved comparisons:

```powershell
.\.venv\Scripts\python.exe -m zipfile -e evidence\additional\raw-additional-experiments.zip evidence\unpacked
.\.venv\Scripts\python.exe scripts\plot_llm_results.py evidence\unpacked\experiment-a501f3f100
.\.venv\Scripts\python.exe scripts\plot_llm_results.py evidence\unpacked\experiment-bee76f24b0
.\.venv\Scripts\python.exe scripts\plot_llm_results.py evidence\unpacked\experiment-0abffed824
.\.venv\Scripts\python.exe scripts\plot_llm_results.py evidence\unpacked\experiment-submission-20261028
.\.venv\Scripts\python.exe scripts\summarize_simulator_classes.py evidence\unpacked\experiment-submission-20261028
```

Each plot command rechecks raw runs and writes regenerated aggregates and figures into the extracted suite folder. For real-model suites it also verifies output token IDs across trials. The class-summary command rechecks the 12 rerun trials and writes `verification-output/simulator/class-summary.csv`. The extraction directory is local and excluded from Git. Avoid extracting over an existing directory you want to preserve.

To check an individual fault or cancellation run, substitute a run ID from the archive manifest:

```powershell
.\.venv\Scripts\python.exe -m llm_lab check evidence\unpacked\20261020T033250-67cc56c5
```

An expected failure scenario may pass the lifecycle check while `all_completed` is false. The stopped worker's interrupted answers are reported as failures; new requests can use the surviving worker.

## Short- and long-request observations in the simulator rerun

Each trial used 36 short and 12 long requests. Values below are the mean across three trials of each trial's mean worker-queue wait and P95 first-token time, in seconds. They follow the simulator's documented cost model and are not real-Qwen measurements. The full [class summary](additional/simulator-class-summary.csv) includes sample standard deviations and P95 queue time.

| Arrival rate | Admission | Class | Mean queue wait (s) | P95 first token (s) |
| --- | --- | --- | ---: | ---: |
| 6/s | Static | Short | 2.96 | 7.34 |
| 6/s | Continuous | Short | 0.38 | 1.25 |
| 6/s | Static | Long | 3.37 | 6.81 |
| 6/s | Continuous | Long | 0.36 | 1.30 |
| 18/s | Static | Short | 5.01 | 11.81 |
| 18/s | Continuous | Short | 1.99 | 5.05 |
| 18/s | Static | Long | 5.13 | 11.12 |
| 18/s | Continuous | Long | 2.14 | 5.25 |

There are only 12 long requests per trial; their P95 values are coarse. The rerun supports the scheduling result for this simulated cost model and workload, not a universal advantage or a real-model acceleration figure.

## Rebuild the report

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-report.txt
.\.venv\Scripts\python.exe scripts\build_report.py
```

The editable source is [TokenFlow_Final_Report.md](../report/TokenFlow_Final_Report.md). The output is the four-page PDF linked at the top of this guide.
