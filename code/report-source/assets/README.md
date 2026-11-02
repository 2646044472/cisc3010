# Report figures

The four-page PDF combines a full-width gray title/abstract card with a two-column body, sans-serif headings, serif text and native vector figures. Rebuild from the `code/` directory with:

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

The routing figure separates load conditions into two columns and metrics into three rows. Solid points show means, horizontal whiskers show sample SD, and right-aligned numbers show means. Trial points and pair lines are omitted to avoid overlap; all trial values remain in `figure-data.json` and the evidence archive. The execution and simulator figures use zero-based horizontal mean bars, sample-SD whiskers and individual observations with small vertical offsets. Numeric labels show the means. Plot scales and units are stated on the axes; real-model and simulator results remain separate. `figure-data.json` records the plotted trial records and source-file SHA256 hashes. `layout-check.json` records occupied and remaining points in each report frame; the builder rejects overflowing frames.

Table 1 is transcribed from the separately validated prefill experiment documented in `docs/LLM_OPTIMIZATION_RESULTS.md`; its raw observations and aggregate table are in the additional evidence archive. Its change column is `(chunked mean / whole-prompt mean - 1) * 100`, calculated from unrounded means and then rounded to one decimal place. The report's prose source is `code/report-source/TokenFlow_Final_Report.md`; hidden region comments control the four-page layout while remaining readable as Markdown.

## Fonts

The body embeds STIX General, distributed by Matplotlib under the SIL Open Font License. The four unmodified font files and their copyright/license notice are in `fonts/`. The builder needs only ReportLab; Matplotlib and system-installed fonts are not required. Headings and diagrams use PDF's standard Helvetica family. The visual reference document itself and its proprietary fonts, logos and annotations are not included.
