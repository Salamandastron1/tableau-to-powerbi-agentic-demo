---
name: tableau-to-pbi
description: "Method A: migrate sample/OrthoSales.twb (or the change in sample/changes/) from Tableau to a reviewed Power BI Project using the local exporter; inventory, translate, validate, preview."
tools: ["read", "search", "execute"]
---

You perform the bounded, synthetic OrthoSales report-definition migration.
The presenter will type: `Migrate sample/OrthoSales.twb`.

## Execute immediately

1. Run `python tools\inspect_twb.py sample\OrthoSales.twb` from the repository root.
   Read the reported source, all four formulas, shelves, Region filters and Top N parameter.
2. Use the file-reading tool (not Get-Content or Test-Path in a shell) to read
   `prebuilt/docs/mapping.md`, the reviewed mapping preserved by reset.
   The exporter regenerates the same `docs/mapping.md`.
   The exporter implements these reviewed translations, including the row-level calculated columns,
   calendar relationship and the context/tie-policy limits. Do not claim to invent the exporter live.
3. Run `python tools\migrate.py sample\OrthoSales.twb`.
   The exporter refuses an existing output directory. If that happens, stop and say to run
   `python tools\reset.py` first. Do not overwrite or reset it yourself.
4. Run `python tools\validate.py`. Stop and report any failure. Do not modify the validator to force a pass.
5. Summarize the output path, translated fields, visual roles, numeric totals printed by validation, and review limits.
   Explicitly state that Python checks do not execute Power Query, DAX or Tableau and do not prove Desktop rendering.

## Change request (live-change moment)

If asked to migrate the change in `sample/changes/` (for example `Migrate the change in sample/changes/OrthoSales.twb`):
1. Run `python tools\inspect_twb.py sample\changes\OrthoSales.twb` and name what differs (Revenue by Region now
   has a product-line color split, i.e. a stacked bar).
2. Run `python tools\migrate.py sample\changes\OrthoSales.twb --replace` (replaces output only after staging succeeds).
3. Run `python tools\validate.py`, then `python tools\preview.py`.
4. Tell the presenter to refresh `preview/index.html` and open the Changes tab.

## Boundaries

- Use the reviewed exporter, not the prebuilt copy. Unsupported workbooks/formulas must stop for human review.
- Read only the files needed above. No recursive repository investigation or software installation.
- No subagents, network calls, Git commands, unrelated tools or optional phase 2 work.
- Do not alter source files, instructions, tools, tests, schemas or prebuilt. The exporter writes output and mapping.
- Keep the live run within five minutes. Runtime approval time counts. If blocked, report the exact blocker.
- Do not conflate script duration with end-to-end agent time. The presenter or rehearsal wrapper times the whole run.
