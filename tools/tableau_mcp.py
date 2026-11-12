"""Read-only Tableau workbook MCP server (stdio). Reads .twb XML under sample/ only."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from inspect_twb import inspect, summary  # noqa: E402
from mcp_stdio import serve  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "sample"


def workbook(arguments):
    path = (ROOT / arguments.get("path", "sample/OrthoSales.twb")).resolve()
    if not path.is_relative_to(SAMPLE) or path.suffix.lower() != ".twb" or not path.is_file():
        raise ValueError("path must be an existing .twb under sample/")
    return path, inspect(path)


def list_workbooks(_):
    return [str(p.relative_to(ROOT).as_posix()) for p in sorted(SAMPLE.rglob("*.twb"))]


def get_workbook_inventory(arguments):
    path, item = workbook(arguments)
    return {"summary": summary(item), "datasources": item["datasources"],
            "parameters": item["parameters"], "dashboards": item["dashboards"],
            "worksheets": [s["name"] for s in item["worksheets"]]}


def get_calculated_fields(arguments):
    _, item = workbook(arguments)
    return [{"caption": c["caption"], "formula": c["formula"], "role": c.get("role"),
             "datatype": c.get("datatype")} for c in item["calculations"]]


def get_worksheet(arguments):
    _, item = workbook(arguments)
    name = arguments.get("name")
    for sheet in item["worksheets"]:
        if sheet["name"] == name:
            return sheet
    raise ValueError(f"Worksheet not found: {name}. Available: {[s['name'] for s in item['worksheets']]}")


PATH = {"path": {"type": "string", "description": "Workbook path relative to repo root, e.g. sample/changes/OrthoSales.twb"}}
TOOLS = {
    "list_workbooks": ("List Tableau .twb workbooks under sample/.", {"type": "object", "properties": {}}, list_workbooks),
    "get_workbook_inventory": ("Data sources, parameters, dashboards, worksheet names and complexity summary.",
                               {"type": "object", "properties": PATH, "required": ["path"]}, get_workbook_inventory),
    "get_calculated_fields": ("Calculated fields with their Tableau formulas.",
                              {"type": "object", "properties": PATH, "required": ["path"]}, get_calculated_fields),
    "get_worksheet": ("One worksheet: rows/columns shelves, marks, encodings (color etc.) and filters XML.",
                      {"type": "object", "properties": {**PATH, "name": {"type": "string"}},
                       "required": ["path", "name"]}, get_worksheet),
}

if __name__ == "__main__":
    serve("tableau-workbook", "1.0.0", TOOLS, "Read-only access to synthetic Tableau workbooks under sample/.")
