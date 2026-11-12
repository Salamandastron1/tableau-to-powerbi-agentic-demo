# Moving Reporting to Power BI, Agentic Style

Demo repository: move Tableau report definitions to Power BI with GitHub Copilot agents and MCP tools.

Live preview (local renderer, not Power BI): open `preview/index.html`, or the GitHub Pages link in the repository description.
First run after cloning: `python tools\reset.py fallback` (restores the validated output, then `python tools\validate.py`).
All data is fictional. No real customer, patient, or inventory data is used.

## Start here: 10-minute run of show

The customer wants a forklift: move existing Tableau reports to Power BI as-is and exit Tableau.
Tableau does not hold the data; both definitions read the same CSV. Only the report definition moves.
This is an agent plus a reviewed, repeatable recipe with human review, not a one-click Microsoft converter.

Before the audience arrives (about 6 seconds):

```powershell
python tools\reset.py fallback
```

This restores the reviewed baseline, validates it, and rebuilds `preview\index.html`.
Open `preview\index.html` in Edge and keep it in a tab.

| Min | Step | Click / type | One-line reset |
| --- | --- | --- | --- |
| 0-2 | 1. Side by side | In `preview\index.html`: change Region to East, then Top N to 5 and 20. Point at identical values, the Tableau XML vs PBIR/DAX under each pair, and the green checks. | `python tools\reset.py fallback` |
| 2-5 | 2. Method A (agent uses the reviewed exporter) | VS Code Chat -> agent picker `tableau-to-pbi` -> type `Migrate the change in sample/changes/OrthoSales.twb`. Approve the Python commands. When done, refresh the preview: Revenue by Region becomes a stacked bar by product line on both sides; open the Changes tab (2 files); point at `validate.py: PASS`. | `python tools\reset.py fallback` |
| 5-8 | 3. Method B (agent loop on MCP tools) | `python tools\reset.py fallback`. VS Code: confirm `tableau` and `pbip` servers are running (`.vscode/mcp.json`, Command Palette -> `MCP: List Servers` -> Start). New chat -> agent `tableau-mcp-workflow` -> type `Migrate the Revenue by Region worksheet from sample/changes/OrthoSales.twb`. Expand the tool calls in chat (get_worksheet, get_visual, set_source_workbook, write_visual, validate). Then run `python tools\preview.py` and refresh. | `python tools\reset.py fallback` |
| 8-10 | 4. Scale story | Open `.github/workflows/tableau-migration.md`: on push of a `.twb` or manual dispatch, the same MCP loop runs and opens a draft PR with output and the preview artifact for human review. Not executed today. Close with the comparison table below. | none |

If an agent stalls past about 2 minutes: stop the chat request, then run the deterministic equivalent and say so.

```powershell
python tools\reset.py fallback                                   # baseline, validated, preview rebuilt
python tools\migrate.py sample\changes\OrthoSales.twb --replace  # what Method A runs (not an agent timing)
python tools\validate.py
python tools\preview.py                                          # refresh the browser tab
```

### Method A vs Method B

| | Method A: agent writes/uses migration code | Method B: agentic workflow on MCP tools |
| --- | --- | --- |
| Who writes the logic | Engineers plus agent write a reviewed exporter (`tools/migrate.py`) once | The agent decides each change; MCP tools only read Tableau and write schema-checked PBIR/TMDL |
| MCP role | Optional: agent may read the workbook through the `tableau` server | Required: every read and write is an MCP tool call |
| Repeatability | Deterministic; same input -> byte-identical output; unit-testable in CI | Model-dependent; bounded by tool schemas, write sandbox (`output/` only) and `validate` |
| Review point | Review the exporter and mapping once; spot-check outputs | Review each pull request diff and preview |
| Scale story | Batch run over hundreds of workbooks per reviewed profile | GitHub Agentic Workflow per changed workbook -> draft PR |
| Use when | Many reports share patterns (profiles) | Long tail, one-off or irregular reports |

Worth evaluating (verified to exist, not used here): Tableau MCP (https://github.com/tableau/tableau-mcp) for
reading published Tableau content, and Microsoft's Power BI Authoring MCP server
(https://github.com/microsoft/powerbi-modeling-mcp) for semantic model edits and DAX query validation.

### Caveats (say briefly)

- The preview is a local Python renderer of both definitions, not Tableau or Power BI. Power BI Desktop and
  Tableau are not installed here: opening, refresh, rendering and DAX/Power Query execution are unverified.
- Copilot CLI rehearsals: one Method A run succeeded in 159.626 s earlier today; later CLI runs (Method A
  81.830 s, 84.094 s; Method B 96.708 s) failed authentication before any tool call. VS Code chat with the
  agent picker has not been rehearsed. Sign in to Copilot in VS Code before the demo.
- Method B was verified end to end over real MCP stdio by `tests/test_mcp.py` (scripted client, not a model).
- The GitHub Agentic Workflow follows the gh-aw documentation but was not compiled (`gh aw compile`) or run.
- Visible difference in the preview: Tableau sorts regions alphabetically (no sort on the shelf); the
  generated PBIR sorts descending by revenue. Values are identical.

## Prerequisites and preflight

Use this repository as the VS Code workspace. Python 3.11+ is sufficient; no pip packages, services,
tenant, network connection or API keys are needed for exporter/validation/fallback.
The live agent additionally needs an authenticated GitHub Copilot subscription and approved terminal tools.

Run from the repository root in PowerShell:

```powershell
python -m unittest discover -s tests -v
python tools\reset.py fallback
python tools\validate.py
```

Keep the successful fallback open in the editor before the meeting.
For a complete agent rehearsal, when Copilot CLI authentication works:

```powershell
python tools\rehearse.py
```

This resets generated artifacts, runs the actual `tableau-to-pbi` agent with the exact demo prompt,
times process startup through agent exit, enforces a 300-second deadline, and validates files independently.
Failures restore the fallback and retain a FAIL result. Raw transcripts and timing evidence stay in the
git-ignored `rehearsal` directory. It does not prove the VS Code interaction time.

CLI login blocker: authenticate with `copilot login` yourself before rehearsal.
Do not paste tokens into a terminal command, chat, source file, or environment file.
For VS Code, confirm Copilot is signed in, the workspace is trusted, and Python terminal commands are approved.

## Backup: original Method A-only sequence

| Step | Action | One-line reset/recovery |
| --- | --- | --- |
| Before audience arrives | `python tools\reset.py fallback`; `python tools\validate.py`; test Desktop if available | `python tools\reset.py fallback` |
| 1. Show source XML | Open `sample\OrthoSales.twb` in VS Code, not Tableau; show the CSV connection and calculations | No state changed; reopen the file |
| 2. Inventory | `python tools\inspect_twb.py sample --csv inventory.csv` | Rerun the same command; it overwrites only the inventory CSV |
| 3. Prepare the before state | Close Power BI Desktop if it has this project open, then `python tools\reset.py` | `python tools\reset.py fallback` |
| 4. Live migration | New VS Code Copilot chat, select `tableau-to-pbi`, start a stopwatch, type `Migrate sample/OrthoSales.twb` | `python tools\reset.py` before retry; fallback if blocked |
| 5. Check numbers and definitions | `python tools\validate.py`; show `docs\mapping.md` and the generated model/report files | `python tools\reset.py fallback` |
| 6. Open report if installed | `Invoke-Item .\output\OrthoSales.pbip`; refresh, then test Region and Top N | Close Desktop, then `python tools\reset.py fallback`; reopen |

If the agent is blocked or approaches five minutes, stop that agent interaction first, then run:

```powershell
python tools\reset.py fallback
python tools\validate.py
```

Say: "This restores the prebuilt definition that passed our offline checks; it is not the live agent run."
Do not race a running agent against a reset.

The deterministic no-agent recovery is:

```powershell
python tools\reset.py
python tools\migrate.py sample\OrthoSales.twb
python tools\validate.py
```

Say: "I am running the reviewed exporter directly." Never label that command an agent timing.

### VS Code picker troubleshooting

- Use the Copilot harness and open this repository, not a parent directory.
- Select `tableau-to-pbi` in the agent selector in a new chat.
- If missing, use Command Palette -> `Chat: Open Customizations` -> Agents and confirm
  `.github/agents/tableau-to-pbi.agent.md` is listed. Reload the window only after saving other work.
- The agent should run inventory, read the preserved mapping, run the exporter, and run validation.
  No new packages, internet research, unrelated edits or delegation are required.
- If output already exists, the exporter refuses to overwrite it. Reset explicitly before retry.

## Thirty-minute talk track

| Minutes | Content |
| --- | --- |
| 0-5 | Confirm the forklift goal: existing report behavior first; contract exit depends on validated coverage, not this sample |
| 5-8 | Explain source data versus report definition; show the same CSV connection |
| 8-10 | Demo: XML, four calculations, three worksheets, dashboard, Region and Top N |
| 10-11 | Demo: workbook/folder inventory and sizing CSV |
| 11-14 | Demo: reset, choose the agent, submit the prompt; narrate the mapping while it works |
| 14-16 | Demo: validation, exact numbers, generated DAX and review caveats |
| 16-18 | Demo: open/refresh in Desktop only if preflight passed; otherwise show the text project and explicitly name the missing gate |
| 18-24 | Hundreds-of-reports path: inventory, complexity buckets, reviewed profiles, batch branches, human-reviewed pull requests, visual acceptance |
| 24-26 | Optional phase 2 talk track below, only if phase 1 is solid |
| 26-30 | Questions, acceptance criteria, ownership and next workbook sample |

The demo segment is ten minutes. Do not spend it debugging sign-in or installing Desktop.

### What to point at

- `sample/OrthoSales.twb`: one CSV source, four calculated fields, three worksheets and one dashboard.
- `sample/data/ortho_sales.csv`: 2,000 rows, 2024-2025, four regions and five product lines.
- `output/OrthoSales.SemanticModel/definition/tables/Sales.tmdl`: nine DAX measures and two row-level calculated columns.
- `output/OrthoSales.Report/definition/pages/Overview`: three data visuals and two slicers on one overview page.
- `docs/mapping.md`: ratio of sums; calendar-based prior year; row-level IF; date truncation; context and tie policies.

## What validation proves

`python tools\validate.py` prints seven PASS/FAIL groups and exits nonzero on failure.

| Check | Evidence |
| --- | --- |
| Data and lineage | CSV types, exact currency cents, normalized source hashes, supported source definitions |
| Arithmetic | Independent Python Decimal aggregation versus SQLite integer-cent grouping |
| Revenue and average selling price | `SUM(revenue)` and `SUM(revenue) / SUM(units)` by region |
| Monthly units | Every month/product-line group, both unfiltered and by Region |
| Year-over-year growth | `(current - prior) / ABS(prior)`; 600 monthly contexts including missing-prior-year BLANK; annual revenue checks |
| Row calculations | Every row's revenue band and month truncation |
| Top N | 20 selection contexts: All/four regions, N = 1, 5, 10, 20; deterministic tie-breaker and winning-set totals |
| Definitions | All four calculations have a measure; row-level dimensions also have columns; typed CSV, calendar and relationship |
| Project/report structure | JSON against pinned Microsoft schema keywords used by the output, pointers, roles, bindings, page bounds and sorting |

The standard-library schema checker is not a complete JSON Schema implementation.
TMDL checks cover this exporter's structural subset, not Microsoft's parser.
No Python test runs Tableau, evaluates DAX or Power Query, loads a model, or checks rendering.

### Expected reference numbers

| Region | Revenue | Units | Average selling price |
| --- | ---: | ---: | ---: |
| Central | $7,355,030.50 | 4,124 | $1,783.47 |
| East | $8,845,439.00 | 4,889 | $1,809.25 |
| South | $7,392,136.00 | 4,065 | $1,818.48 |
| West | $7,327,971.00 | 4,055 | $1,807.14 |
| All | $30,920,576.50 | 17,133 | $1,804.74 |

Values above were computed by validation, not estimated. The complete reference metrics are available with:

```powershell
python tools\validate.py --json
```

## Outstanding Desktop acceptance gate

On a Windows machine with current Power BI Desktop installed:

1. Enable the Power BI project and enhanced report format preview options if that Desktop build requires them.
2. Open `output\OrthoSales.pbip`, confirm there is no TMDL/report loading error, and select Refresh.
3. If prompted for source privacy, set a suitable local-file privacy level for this synthetic source.
4. Confirm the regional bars match the table above and the line chart has 24 months with five product lines.
5. Select East in Region. Confirm the East revenue and units above, not the unfiltered totals.
6. With Top N untouched, confirm the table has 10 SKU rows. Select 1, 5 and 20 and confirm those row counts.
   The grand total must be the sum of displayed winning SKUs. Clear Region and repeat.
7. In DAX Query View, execute the queries below and compare results to `validate.py --json`.
8. Record application version, refresh outcome, slicer results and screenshots before calling it visually validated.

```dax
EVALUATE
ROW("Revenue", [Total Revenue], "Units", [Total Units], "ASP", [Average Selling Price])

EVALUATE
SUMMARIZECOLUMNS(
    'Sales'[region],
    "Revenue", [Total Revenue],
    "Units", [Total Units],
    "ASP", [Average Selling Price]
)

EVALUATE
SUMMARIZECOLUMNS(
    'Calendar'[Month],
    'Sales'[product_line],
    "Revenue", [Total Revenue],
    "PriorYear", [Revenue Prior Year],
    "YoY", [YoY Revenue Growth]
)
ORDER BY 'Calendar'[Month], 'Sales'[product_line]
```

The fallback source path is rebound to the current checkout during restore. It is not tied to the build machine.
For a moved checkout regenerate or restore before opening; do not copy the machine-specific generated output alone.

## Measured timings and limitations

Observed on this machine on 12 November 2026:

| Operation | Measured seconds | Measurement boundary |
| --- | ---: | --- |
| Actual successful Copilot CLI run | 159.626 | Process startup through agent exit, including inventory, mapping read, export and validation |
| Later CLI authentication failures | 81.830; 84.094 | Failed before generation; not successful migrations |
| Final reviewed exporter | 0.322 | Script's internal timer; not agent wall clock |
| Final offline validation | 0.612 | Script's internal timer on a warm run |
| Final restore and validate fallback | 4.444 | Reset script's internal timer |
| Final twenty-nine-test suite | 18.585 | unittest runner, including mixed-batch inventory and actual process-tree timeout cleanup |
| Preview build (addendum) | 3.035 | `tools/preview.py` internal timer after the stacked-bar change |
| Restore fallback plus preview | 6.046 | `tools/reset.py fallback` internal timer |
| MCP stdio Method B test | 36.251 | `tests/test_mcp.py`: real servers, scripted client |
| Final thirty-two-test suite (addendum) | 126.973 | unittest runner, all tests including MCP and preview |

Startup load and authentication vary. Do not advertise one successful run as a latency guarantee.
Desktop opening and VS Code interactive timing have not been measured.

### What is shaky

- CLI authentication is currently blocking repeat rehearsals despite an earlier successful run.
- Power BI and Tableau application compatibility have not been tested on this machine.
- This exporter intentionally supports only the supplied profile. It rejects changed formulas, shelves,
  series encodings, filter defaults and parameter domains rather than silently dropping them.
- `LOOKUP(-12)` is position-based. Its calendar-year translation needs complete ascending monthly marks
  and the specified product-line partition. Missing/hidden months and different addressing need review.
- Region filtering before Top N is explicit in both definitions: the sample's Tableau Region filters
  are context filters. Exactly-N tie handling uses ascending SKU; confirm this with the report owner.
- The layout preserves the three visual roles, not exact Tableau typography, spacing, interactions or dashboard chrome.
- Sales/inventory-on-hand parity is not claimed: the requested fixture contains only sales fields.

## Scale to hundreds of reports

```powershell
python tools\inspect_twb.py sample --csv inventory.csv
```

The inventory recursively reads `.twb` files. Malformed files are reported and make the exit code nonzero,
while valid workbooks still appear in the summary.
Packaged `.twbx` files, extracts, SQL credentials and published Tableau Server content are not supported here.

The transparent sizing heuristic is:

`score = worksheets + 2 * calculations + 5 * LOOKUP_calculations + 8 * LOD_calculations + distinct_filter_fields`

Buckets: low <= 10; medium <= 25; high > 25. This sample scores 18, medium.
Level-of-detail (LOD) detection is heuristic. The score sizes review effort; it does not predict successful conversion.

1. Inventory source connections, formulas, parameters, table-calculation addressing, filters and visual dependencies.
2. Group workbooks into reviewed migration profiles. This repository implements one such profile.
3. Keep data sources in place where appropriate; review authentication, refresh, gateways and security separately.
4. Run each conversion in an isolated branch/job with explicit failure reporting. A generic batch converter is not included.
5. Open pull requests containing source inventory, mapping, generated definitions and test evidence.
6. Report owners review filter order, totals, tie policies, nulls, date logic, security and visual equivalence.
7. Refresh and visually accept in Desktop/service, validate deployment and licensing, then decide when Tableau can retire.
   Do not cancel a contract based on this synthetic proof.

## Optional phase 2: two-minute talk track only

"First we move the report as-is. Once its model and access controls are accepted, a separate phase can
let an agent answer approved questions or flag unusual trends using that same governed semantic model.
For example: Which region changed most year over year, and which product lines explain it?
That is a follow-on experience, not a prerequisite for getting the existing reports out of Tableau."

No Fabric deployment, natural-language query service, anomaly detector, or autonomous business action is implemented.

## Maintenance

```powershell
# Reproduce the committed synthetic data (seed 42, 2,000 rows).
python tools\make_data.py

# Reset, regenerate and validate after an intentional recipe change.
python tools\reset.py
python tools\migrate.py sample\OrthoSales.twb
python tools\validate.py
python -m unittest discover -s tests -v

# Refresh pinned official schemas only when intentionally updating formats.
python tools\fetch_schemas.py
```

`tools/freeze.py` creates the prebuilt snapshot only after offline validation.
It refuses to overwrite an existing snapshot. Replacing `prebuilt` is an explicit maintainer operation:
review changes and application evidence, remove that exact directory deliberately, then freeze and test fallback again.
Do not regenerate the fallback during the live presentation.

No changes are pushed. Milestones are local commits on `feat/tableau-power-bi-demo`.

## Sources

Microsoft. "Power BI Desktop Projects (PBIP)." Microsoft Learn. Accessed 12 Nov. 2026.
https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-overview.

Microsoft. "Power BI Desktop Project Semantic Model Folder." Microsoft Learn. Accessed 12 Nov. 2026.
https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-dataset.

Microsoft. "Power BI Desktop Project Report Folder." Microsoft Learn. Accessed 12 Nov. 2026.
https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-report.

Microsoft. "Tabular Model Definition Language (TMDL) Overview." Microsoft Learn. Accessed 12 Nov. 2026.
https://learn.microsoft.com/en-us/analysis-services/tmdl/tmdl-overview.

Microsoft. "JSON Schemas." GitHub, https://github.com/microsoft/json-schemas. Accessed 12 Nov. 2026.
Pinned schema URLs and SHA-256 hashes are in `schemas/manifest.json`; the MIT license is in `schemas/LICENSE.txt`.
Only line endings were normalized when caching.

Microsoft. "Custom Agents in VS Code." Visual Studio Code Documentation. Accessed 12 Nov. 2026.
https://code.visualstudio.com/docs/copilot/customization/custom-agents.

Microsoft. "Report Theme JSON Schema, 2.159." Power BI Desktop Samples, GitHub. Accessed 12 Nov. 2026.
https://github.com/microsoft/powerbi-desktop-samples/blob/main/Report%20Theme%20JSON%20Schema/reportThemeSchema-2.159.json.
The slicer definitions distinguish `data.mode`, `selection.singleSelect` (multi-select with CTRL),
and `selection.strictSingleSelect` (true single selection).
