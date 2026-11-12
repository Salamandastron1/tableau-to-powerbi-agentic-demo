---
description: |
  Method B at scale: when a Tableau workbook (.twb) is added or changed under sample/, migrate it to the
  Power BI Project in output/ through the repository's MCP tools only, build the local preview, and open
  a draft pull request for human review. Synthetic demo repository; not executed in the live demo.
on:
  push:
    branches: [main]
    paths:
      - "sample/**/*.twb"
  workflow_dispatch:
    inputs:
      workbook:
        description: "Workbook to migrate, relative to the repository root"
        required: false
        default: "sample/changes/OrthoSales.twb"
permissions:
  contents: read
engine: copilot
timeout-minutes: 15
network:
  allowed:
    - defaults
    - python
runtimes:
  python:
    version: "3.11"
steps:
  - name: Restore reviewed baseline output for the agent to modify
    run: python tools/reset.py fallback
mcp-servers:
  tableau:
    command: "python"
    args: ["tools/tableau_mcp.py"]
    allowed: ["list_workbooks", "get_workbook_inventory", "get_calculated_fields", "get_worksheet"]
  pbip:
    command: "python"
    args: ["tools/pbip_mcp.py"]
    allowed: ["set_source_workbook", "get_visual", "write_visual", "write_measure", "validate"]
tools:
  bash: ["python tools/preview.py"]
safe-outputs:
  create-pull-request:
    title-prefix: "[tableau-migration] "
    labels: [migration, needs-human-review]
    draft: true
  upload-artifact:
    max-uploads: 1
    retention-days: 7
    skip-archive: true
    allowed-paths:
      - "preview/index.html"
---

# Tableau to Power BI migration (MCP workflow)

You are migrating synthetic Tableau report definitions to a Power BI Project using MCP tools.
The data stays where it is; only report definitions move.

1. Determine the workbook: the `workbook` input for manual runs, otherwise each `.twb` under `sample/`
   changed by the triggering push (use `tableau` `list_workbooks` to confirm it exists).
2. Follow `.github/agents/tableau-mcp-workflow.agent.md`: for each worksheet, read it with the `tableau`
   tools, compare with the current visual via `pbip` `get_visual`, write only the needed change with
   `write_visual` or `write_measure`, record the source with `set_source_workbook`, then call `validate`.
3. If `validate` reports any FAIL, do not open a pull request. Report the failing checks instead.
4. Run `python tools/preview.py` and upload `preview/index.html` as an artifact.
5. Open a draft pull request containing only changes under `output/` and `docs/`. In the body include:
   the workbook migrated, each MCP tool call, each changed visual or measure, every validate PASS line,
   and this caveat: "Preview and validation are local Python checks; refresh and visual acceptance in
   Power BI Desktop or the Power BI service are still required."
