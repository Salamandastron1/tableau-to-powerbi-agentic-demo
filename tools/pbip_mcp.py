"""Power BI Project (PBIP) write MCP server (stdio). Every write is confined to output/."""
import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from inspect_twb import inspect  # noqa: E402
from mcp_stdio import serve  # noqa: E402
from migrate import MODEL, REPORT, check_profile, source_file, text_hash  # noqa: E402
from schema_check import check_document  # noqa: E402
from validate import validate  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
# Test hook: an alternate output folder, still required to be inside this repository.
OUTPUT = Path(os.environ.get("PBIP_MCP_OUTPUT", ROOT / "output")).resolve()
if not OUTPUT.is_relative_to(ROOT) or OUTPUT == ROOT:
    raise SystemExit("PBIP_MCP_OUTPUT must be a folder inside the repository.")
VISUAL_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.1.0/schema.json"
NAME = re.compile(r"^[A-Za-z0-9_-]{1,50}$")


def inside_output(path: Path) -> Path:
    path = path.resolve()
    if not path.is_relative_to(OUTPUT.resolve()):
        raise ValueError("Writes are restricted to output/.")
    if not OUTPUT.is_dir():
        raise ValueError("output/ does not exist. Ask the presenter to run: python tools\\reset.py fallback")
    return path


def set_source_workbook(arguments):
    workbook = (ROOT / arguments["path"]).resolve()
    if not workbook.is_relative_to(ROOT / "sample") or workbook.suffix != ".twb":
        raise ValueError("Workbook must be a .twb under sample/.")
    item = inspect(workbook)
    check_profile(item)
    source = source_file(workbook, item)
    path = inside_output(OUTPUT / "migration.json")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest.update({"workbook": str(workbook.relative_to(ROOT)), "source": str(source.relative_to(ROOT)),
                     "workbook_sha256": text_hash(workbook), "source_sha256": text_hash(source)})
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    return {"ok": True, "workbook": manifest["workbook"], "note": "Validation will now compare output with this workbook."}


def get_visual(arguments):
    page, name = arguments.get("page", "Overview"), arguments["name"]
    if not NAME.match(page) or not NAME.match(name):
        raise ValueError("Invalid page/visual name.")
    path = inside_output(OUTPUT / REPORT / "definition" / "pages" / page / "visuals" / name / "visual.json")
    return json.loads(path.read_text(encoding="utf-8"))


def write_visual(arguments):
    page, name, visual = arguments.get("page", "Overview"), arguments["name"], arguments["visual"]
    if not NAME.match(page) or not NAME.match(name):
        raise ValueError("Invalid page/visual name.")
    if isinstance(visual, str):
        visual = json.loads(visual)
    document = {"$schema": VISUAL_SCHEMA, **{k: v for k, v in visual.items() if k != "$schema"}}
    document["name"] = name
    check_document(document)  # pinned Microsoft PBIR visualContainer schema
    page_dir = inside_output(OUTPUT / REPORT / "definition" / "pages" / page)
    if not (page_dir / "page.json").is_file():
        raise ValueError(f"Page does not exist: {page}")
    path = inside_output(page_dir / "visuals" / name / "visual.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(document, indent=2, ensure_ascii=True) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")
    return {"ok": True, "path": str(path.relative_to(ROOT)), "sha256": hashlib.sha256(text.encode()).hexdigest()[:12]}


def write_measure(arguments):
    table, name, expression = arguments["table"], arguments["name"], arguments["expression"].strip()
    if not re.fullmatch(r"[A-Za-z0-9 _-]{1,60}", table) or not re.fullmatch(r"[A-Za-z0-9 %_-]{1,80}", name):
        raise ValueError("Invalid table/measure name.")
    if "\n" in expression or not expression:
        raise ValueError("Provide a single-line, non-empty DAX expression.")
    path = inside_output(OUTPUT / MODEL / "definition" / "tables" / f"{table}.tmdl")
    if not path.is_file():
        raise ValueError(f"Table not found: {table}")
    lines = path.read_text(encoding="utf-8").splitlines()
    block = [f"\tmeasure '{name}' = {expression}"]
    if arguments.get("format_string"):
        block.append(f"\t\tformatString: {arguments['format_string']}")
    header = re.compile(r"^\tmeasure (?:'" + re.escape(name.replace("'", "''")) + r"'|" + re.escape(name) + r") = ")
    start = next((i for i, line in enumerate(lines) if header.match(line)), None)
    if start is not None:
        end = start + 1
        while end < len(lines) and lines[end].startswith("\t\t"):
            end += 1
        lines[start:end] = block
        action = "replaced"
    else:
        insert = next((i for i, line in enumerate(lines) if line.startswith("\tcolumn ")), len(lines))
        lines[insert:insert] = block + [""]
        action = "added"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return {"ok": True, "action": action, "path": str(path.relative_to(ROOT))}


def run_validate(_):
    report = validate(OUTPUT)
    return {"ok": report["ok"], "checks": report["checks"], "not_verified": report["not_verified"]}


TOOLS = {
    "set_source_workbook": ("Record which sample/ .twb this output now represents (updates output/migration.json).",
                            {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
                            set_source_workbook),
    "get_visual": ("Read an existing PBIR visual.json from output/.",
                   {"type": "object", "properties": {"page": {"type": "string"}, "name": {"type": "string"}},
                    "required": ["name"]}, get_visual),
    "write_visual": ("Write one PBIR visual.json under output/ after checking Microsoft's visualContainer schema.",
                     {"type": "object", "properties": {
                         "page": {"type": "string", "default": "Overview"},
                         "name": {"type": "string", "description": "Visual folder/name, e.g. RevenueByRegion"},
                         "visual": {"type": "object", "description": "visualContainer document: position + visual"}},
                      "required": ["name", "visual"]}, write_visual),
    "write_measure": ("Add or replace one DAX measure in a TMDL table under output/.",
                      {"type": "object", "properties": {
                          "table": {"type": "string"}, "name": {"type": "string"},
                          "expression": {"type": "string"}, "format_string": {"type": "string"}},
                       "required": ["table", "name", "expression"]}, write_measure),
    "validate": ("Run tools/validate.py checks on output/ and return PASS/FAIL per check.",
                 {"type": "object", "properties": {}}, run_validate),
}

if __name__ == "__main__":
    serve("pbip-writer", "1.0.0", TOOLS, "Writes confined to output/. Always call validate after writing.")
