# Report figures

The PDF uses these native vector drawings, rather than screenshots or generated decorative images. Rebuild from the repository root with:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-report.txt
.\.venv\Scripts\python.exe scripts\build_report.py
```

| Figure | Source | Interpretation |
| --- | --- | --- |
| `architecture.svg` | Implemented gateway and two-worker deployment | Process boundaries and request routing; one shared host |
| `routing.svg` | `evidence/routing/raw-routing.zip`, `random-suite/results.json` | All 24 primary trials; six pairs per arrival rate |
| `mechanism.svg` | `llm_lab/selective.py` and documented execution path | Schematic selective layer computation; not a captured iteration |
| `execution.svg` | Additional archive, `experiment-a501f3f100/results.json` | Six real Qwen trials, independent versus selective execution |
| `simulator.svg` | Additional archive, `experiment-submission-20261028/results.json` | Twelve simulator trials, static versus continuous admission |

Open points are individual trials. Heavy marks and whiskers are mean +/- sample SD. Gray lines connect repeat pairs in routing/execution plots. Plot scales and units are stated on the axes; real-model and simulator results remain separate. `figure-data.json` records the plotted trial records and source-file SHA256 hashes. `layout-check.json` records occupied and remaining points in each report frame; the builder rejects overflowing frames.

Table 1 is transcribed from the separately validated prefill experiment documented in `docs/LLM_OPTIMIZATION_RESULTS.md`; its raw observations and aggregate table are in the additional evidence archive. The report's prose source is `report/TokenFlow_Final_Report.md`; hidden region comments control the four-page layout while remaining readable as Markdown.
