# OrthoSales migration demo

- Work only in this repository. Python 3.11+ standard library only. Synthetic data only.
- Lead with report-definition forklift migration, not data relocation or re-architecture.
- This is a reviewed recipe for the supplied OrthoSales profile, not a general or one-click Tableau converter.
- Use `python tools\inspect_twb.py sample` to inventory before translating.
- Translation rules and limits: `docs/mapping.md`; when reset removed it, read `prebuilt/docs/mapping.md`.
- Method A: run `python tools\migrate.py sample\OrthoSales.twb` to emit the reviewed PBIP, TMDL and PBIR.
  For the live change: `python tools\migrate.py sample\changes\OrthoSales.twb --replace`.
- Method B: the `tableau-mcp-workflow` agent uses only the `tableau` and `pbip` MCP servers
  (`.vscode/mcp.json`); writes stay in `output/`.
- After any change run `python tools\preview.py` and open `preview/index.html` (local renderer, not Power BI).
  Do not copy prebuilt output during a migration or invent new formulas silently.
- Run `python tools\validate.py` after generation. Stop on FAIL. Never call Python checks DAX-engine validation.
- For implementation changes run `python -m unittest discover -s tests -v`.
- For a live migration, do not edit the sample, tools, schemas or prebuilt files, commit, push, install software,
  browse, delegate, or reset without an explicit request. Only generated output and mapping should change.
- Only `python tools\reset.py` removes the generated artifacts.
  `python tools\reset.py fallback` restores and checks the prebuilt fallback, and must be identified as a restore.
- Pin report JSON to schemas in `schemas/manifest.json`; schemas are already fetched from Microsoft.
  Do not refetch them during the live run.
- Report Desktop/Power Query/DAX execution as unverified unless actually observed in those applications.
