"""Emit the reviewed OrthoSales PBIP profile, refusing unsupported workbook changes."""
import argparse
import csv
import hashlib
import json
import shutil
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    from .fetch_schemas import SCHEMAS
    from .inspect_twb import inspect
    from .make_data import FIELDS
    from .migration_rules import BASE_MEASURES, CALCULATIONS, mapping_text
    from .schema_check import check_document
except ImportError:
    from fetch_schemas import SCHEMAS
    from inspect_twb import inspect
    from make_data import FIELDS
    from migration_rules import BASE_MEASURES, CALCULATIONS, mapping_text
    from schema_check import check_document

ROOT = Path(__file__).resolve().parents[1]
NAME = "OrthoSales"
MODEL = f"{NAME}.SemanticModel"
REPORT = f"{NAME}.Report"


def text_hash(path: Path) -> str:
    return hashlib.sha256(path.read_text(encoding="utf-8-sig").encode("utf-8")).hexdigest()


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8", newline="\n")


def write_json(path: Path, document: dict, schema: str | None = None):
    if schema:
        document = {"$schema": SCHEMAS[schema], **document}
        check_document(document)
    write(path, json.dumps(document, indent=2, ensure_ascii=True))


def source_file(workbook: Path, item: dict) -> Path:
    if len(item["datasources"]) != 1:
        raise ValueError("Reviewed profile requires exactly one text-file data source.")
    connection = item["datasources"][0]["connection"]
    if connection.get("class") != "textscan":
        raise ValueError("Reviewed profile supports only Tableau textscan CSV connections.")
    source = (workbook.parent / connection.get("directory", "") / connection["filename"]).resolve()
    if not source.is_relative_to(ROOT):
        raise ValueError("Source must remain inside this demo repository.")
    with source.open(encoding="utf-8-sig", newline="") as stream:
        if tuple(csv.DictReader(stream).fieldnames or ()) != FIELDS:
            raise ValueError(f"CSV fields must match the reviewed profile: {FIELDS}")
    return source


def check_profile(item: dict):
    def signature(element):
        return (element.tag, element.attrib, (element.text or "").strip(),
                [signature(child) for child in element])

    region_filter = ET.fromstring(
        '<filter class="categorical" column="[ortho_sales].[none:region:nk]" context="true">'
        '<groupfilter function="all" /></filter>')
    sku_filter = ET.fromstring(
        '<filter class="categorical" column="[ortho_sales].[none:sku:nk]">'
        '<groupfilter function="end" count="[Parameters].[Top N]" end="top" units="records">'
        '<groupfilter function="order" direction="DESC" expression="SUM([revenue])">'
        '<groupfilter function="level-members" level="[none:sku:nk]" />'
        '</groupfilter></groupfilter></filter>')
    actual = {c["caption"]: c["formula"] for c in item["calculations"]}
    expected = {name: rule["tableau"] for name, rule in CALCULATIONS.items()}
    if actual != expected or len(item["calculations"]) != len(expected):
        raise ValueError("Unsupported calculated fields or changed formulas. Review the mapping; do not guess.")
    expected_sheets = {
        "Revenue by Region": ("[ortho_sales].[none:region:nk]", "[ortho_sales].[sum:revenue:qk]", ["Bar"]),
        "Monthly Units by Product Line": (
            "[ortho_sales].[sum:units:qk]", "[ortho_sales].[none:Order Month:ok]", ["Line"]),
        "Top SKUs": ("[ortho_sales].[none:sku:nk]", "", ["Text"]),
    }
    if len(item["worksheets"]) != 3 or {s["name"] for s in item["worksheets"]} != set(expected_sheets):
        raise ValueError("Unsupported worksheet layout; this recipe covers the three supplied worksheets.")
    for sheet in item["worksheets"]:
        if (sheet["rows"], sheet["columns"], sheet["marks"]) != expected_sheets[sheet["name"]]:
            raise ValueError(f"Unsupported shelves/marks: {sheet['name']}")
    params = item["parameters"]
    if len(params) != 1 or params[0]["caption"] != "Top N" or params[0].get("value") != "10" or (
        params[0]["range"] != {"granularity": "1", "max": "20", "min": "1"}
    ):
        raise ValueError("Unsupported parameter; expected Top N default 10, range 1 to 20.")
    if len(item["dashboards"]) != 1 or set(item["dashboards"][0]["worksheets"]) != set(expected_sheets):
        raise ValueError("Unsupported dashboard worksheet composition.")
    for sheet in item["worksheets"]:
        region = [f for f in sheet["filters"] if f["column"] == "[ortho_sales].[none:region:nk]"]
        if len(region) != 1 or signature(ET.fromstring(region[0]["definition"])) != signature(region_filter):
            raise ValueError(f"Expected all-values Region context filter on {sheet['name']}")
        extra = [f for f in sheet["filters"] if f not in region]
        if sheet["name"] == "Top SKUs":
            if len(extra) != 1 or signature(ET.fromstring(extra[0]["definition"])) != signature(sku_filter):
                raise ValueError("Unsupported Top N filter.")
        elif extra:
            raise ValueError(f"Unsupported filters on {sheet['name']}")
    line = next(s for s in item["worksheets"] if s["name"] == "Monthly Units by Product Line")
    if line["encodings"] != [{"column": "[ortho_sales].[none:product_line:nk]", "channel": "color"}]:
        raise ValueError("Unsupported line-chart series encoding.")
    bar_is_stacked(item)


def bar_is_stacked(item: dict) -> bool:
    """Reviewed variant: Revenue by Region may be split by product line (stacked bar)."""
    bar = next(s for s in item["worksheets"] if s["name"] == "Revenue by Region")
    if bar["encodings"] == []:
        return False
    if bar["encodings"] == [{"column": "[ortho_sales].[none:product_line:nk]", "channel": "color"}]:
        return True
    raise ValueError("Unsupported bar-chart encoding; only an optional product-line color split is reviewed.")


def path_expression(source: Path) -> str:
    escaped = str(source.resolve()).replace('"', '""')
    return f'expression DataFilePath = "{escaped}" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]\n'


def emit_model(output: Path, source: Path):
    model = output / MODEL
    definition = model / "definition"
    write_json(model / "definition.pbism", {"version": "4.0", "settings": {"qnaEnabled": False}}, "pbism")
    write(definition / "database.tmdl", "database\n\tcompatibilityLevel: 1601")
    write(definition / "model.tmdl", """model Model
\tculture: en-US
\tdefaultPowerBIDataSourceVersion: powerBI_V3
\tsourceQueryCulture: en-US

\tannotation PBI_QueryOrder = ["Sales", "Calendar", "Top N"]

\tref table Sales
\tref table Calendar
\tref table 'Top N'
""")
    write(definition / "expressions.tmdl", path_expression(source) + """
expression SalesSource =
\t\tlet
\t\t\tRaw = Csv.Document(File.Contents(DataFilePath), [Delimiter=",", Columns=7, Encoding=65001, QuoteStyle=QuoteStyle.Csv]),
\t\t\tHeaders = Table.PromoteHeaders(Raw, [PromoteAllScalars=true]),
\t\t\tTyped = Table.TransformColumnTypes(Headers, {{"order_date", type date}, {"region", type text}, {"territory", type text}, {"product_line", type text}, {"sku", type text}, {"units", Int64.Type}, {"revenue", Currency.Type}}, "en-US")
\t\tin
\t\t\tTyped
""")
    measures = {**BASE_MEASURES, **{name: (rule["dax"], rule["format"]) for name, rule in CALCULATIONS.items()}}
    sales = ["table Sales", ""]
    for name, (expression, fmt) in measures.items():
        sales += [f"\tmeasure '{name}' = {expression}"]
        if fmt:
            sales += [f"\t\tformatString: {fmt}"]
        sales += [""]
    for name in FIELDS:
        dtype = "dateTime" if name == "order_date" else "int64" if name == "units" else (
            "decimal" if name == "revenue" else "string")
        sales += [f"\tcolumn {name}", f"\t\tdataType: {dtype}",
                  f"\t\tsummarizeBy: {'sum' if name in ('units', 'revenue') else 'none'}",
                  f"\t\tsourceColumn: {name}"]
        if name == "order_date":
            sales += ["\t\tformatString: yyyy-MM-dd"]
        if name == "revenue":
            sales += ["\t\tformatString: $#,##0.00"]
        sales += [""]
    for rule in CALCULATIONS.values():
        if "column_dax" in rule:
            sales += [f"\tcolumn '{rule['column_name']}' = {rule['column_dax']}",
                      f"\t\tdataType: {'dateTime' if rule['column_name'].startswith('Order') else 'string'}",
                      "\t\tsummarizeBy: none", ""]
    sales += ["\tpartition Sales = m", "\t\tmode: import", "\t\tsource = SalesSource"]
    write(definition / "tables" / "Sales.tmdl", "\n".join(sales))
    write(definition / "tables" / "Calendar.tmdl", """table Calendar
\tdataCategory: Time

\tcolumn Date
\t\tdataType: dateTime
\t\tisKey
\t\tformatString: yyyy-MM-dd
\t\tsummarizeBy: none
\t\tsourceColumn: Date

\tcolumn Month
\t\tdataType: string
\t\tsummarizeBy: none
\t\tsourceColumn: Month

\tpartition Calendar = m
\t\tmode: import
\t\tsource =
\t\t\t\tlet
\t\t\t\t\tStart = Date.StartOfYear(List.Min(SalesSource[order_date])),
\t\t\t\t\tEnd = Date.EndOfYear(List.Max(SalesSource[order_date])),
\t\t\t\t\tDates = List.Dates(Start, Duration.Days(End - Start) + 1, #duration(1, 0, 0, 0)),
\t\t\t\t\tCalendarTable = Table.FromColumns({Dates}, type table [Date = date]),
\t\t\t\t\tWithMonth = Table.AddColumn(CalendarTable, "Month", each Date.ToText([Date], "yyyy-MM", "en-US"), type text)
\t\t\t\tin
\t\t\t\t\tWithMonth
""")
    write(definition / "tables" / "Top N.tmdl", """table 'Top N'

\tcolumn Value
\t\tdataType: int64
\t\tformatString: 0
\t\tsummarizeBy: none
\t\tisNameInferred
\t\tsourceColumn: [Value]

\tpartition 'Top N' = calculated
\t\tmode: import
\t\tsource = GENERATESERIES(1, 20, 1)
""")
    write(definition / "relationships.tmdl", """relationship Sales_Calendar
\tfromColumn: Sales.order_date
\ttoColumn: Calendar.Date
\tfromCardinality: many
\ttoCardinality: one
\tcrossFilteringBehavior: oneDirection
""")


def field(table: str, name: str, measure=False) -> dict:
    return {"Measure" if measure else "Column": {"Expression": {"SourceRef": {"Entity": table}}, "Property": name}}


def projection(table: str, name: str, measure=False) -> dict:
    return {"field": field(table, name, measure), "queryRef": f"{table}.{name}", "nativeQueryRef": name}


def literal(value: str) -> dict:
    return {"expr": {"Literal": {"Value": value}}}


def emit_visual(page: Path, name, kind, title, position, roles, sort=None, single=False):
    config = {
        "visualType": kind,
        "query": {"queryState": {role: {"projections": values} for role, values in roles.items()}},
        "visualContainerObjects": {"title": [{"properties": {
            "show": literal("true"), "text": literal("'" + title.replace("'", "''") + "'")
        }}]},
        "drillFilterOtherVisuals": True,
    }
    if sort:
        config["query"]["sortDefinition"] = {
            "sort": [{"field": sort[0], "direction": sort[1]}], "isDefaultSort": True}
    if single:
        config["objects"] = {
            "data": [{"properties": {"mode": literal("'Dropdown'")}}],
            "selection": [{"properties": {"strictSingleSelect": literal("true")}}],
            "general": [{"properties": {"filter": {"filter": {
                "Version": 2,
                "From": [{"Name": "topn", "Entity": "Top N", "Type": 0}],
                "Where": [{"Condition": {"In": {
                    "Expressions": [{"Column": {
                        "Expression": {"SourceRef": {"Source": "topn"}}, "Property": "Value",
                    }}],
                    "Values": [[{"Literal": {"Value": "10L"}}]],
                }}}],
            }}}}],
        }
    x, y, width, height, z = position
    write_json(page / "visuals" / name / "visual.json", {
        "name": name, "position": {"x": x, "y": y, "width": width, "height": height, "z": z, "tabOrder": z},
        "visual": config,
    }, "visual")


def emit_report(output: Path, stacked: bool = False):
    report = output / REPORT
    definition = report / "definition"
    write_json(output / f"{NAME}.pbip", {
        "version": "1.0", "artifacts": [{"report": {"path": REPORT}}],
        "settings": {"enableAutoRecovery": True},
    }, "pbip")
    # PBIP relative reference strings require "/" even on Windows, per Microsoft.
    write_json(report / "definition.pbir", {
        "version": "4.0", "datasetReference": {"byPath": {"path": f"../{MODEL}"}},
    }, "pbir")
    write_json(definition / "version.json", {"version": "4.0.0"}, "version")
    write_json(definition / "report.json", {"themeCollection": {}}, "report")
    write_json(definition / "pages" / "pages.json", {
        "pageOrder": ["Overview"], "activePageName": "Overview",
    }, "pages")
    page = definition / "pages" / "Overview"
    write_json(page / "page.json", {
        "name": "Overview", "displayName": "Orthopedic Sales Overview (Synthetic)",
        "displayOption": "FitToPage", "width": 1280, "height": 900,
    }, "page")
    emit_visual(page, "Region", "slicer", "Region (all visuals)", (20, 10, 800, 140, 0),
                {"Values": [projection("Sales", "region")]})
    emit_visual(page, "TopN", "slicer", "Top N SKUs (default 10)", (840, 10, 420, 140, 1),
                {"Values": [projection("Top N", "Value")]}, single=True)
    bar_roles = {"Category": [projection("Sales", "region")], "Y": [projection("Sales", "Total Revenue", True)]}
    if stacked:
        bar_roles["Series"] = [projection("Sales", "product_line")]
    emit_visual(page, "RevenueByRegion", "barChart" if stacked else "clusteredBarChart",
                "Revenue by Region and Product Line" if stacked else "Revenue by Region",
                (20, 165, 570, 330, 2), bar_roles,
                (field("Sales", "Total Revenue", True), "Descending"))
    emit_visual(page, "MonthlyUnits", "lineChart", "Monthly Units by Product Line",
                (610, 165, 650, 330, 3),
                {"Category": [projection("Calendar", "Month")], "Series": [projection("Sales", "product_line")],
                 "Y": [projection("Sales", "Total Units", True)]},
                (field("Calendar", "Month"), "Ascending"))
    emit_visual(page, "TopSKUs", "tableEx", "Top SKUs by Revenue",
                (20, 515, 1240, 365, 4),
                {"Values": [projection("Sales", "sku"), projection("Sales", "Top N Revenue", True)]},
                (field("Sales", "Top N Revenue", True), "Descending"))


def migrate(workbook: Path, output: Path = ROOT / "output", mapping: Path = ROOT / "docs" / "mapping.md",
            replace: bool = False) -> dict:
    workbook, output, mapping = workbook.resolve(), output.resolve(), mapping.resolve()
    if not all(p.is_relative_to(ROOT) for p in (workbook, output, mapping)):
        raise ValueError("All migration paths must stay inside this repository.")
    if output.exists() and not replace:
        raise ValueError(f"Output already exists: {output}. Run python tools\\reset.py first, or pass --replace.")
    if output == ROOT or output in (ROOT / "sample", ROOT / "tools", ROOT / "prebuilt", ROOT / "schemas"):
        raise ValueError("Output must be a dedicated generated directory.")
    item = inspect(workbook)
    check_profile(item)
    source = source_file(workbook, item)
    manifest = {
        "profile": "orthosales-v1", "workbook": str(workbook.relative_to(ROOT)),
        "source": str(source.relative_to(ROOT)),
        "workbook_sha256": text_hash(workbook),
        "source_sha256": text_hash(source),
        "calculated_fields": list(CALCULATIONS),
        "limitations": ["Desktop/Power Query/DAX execution not verified by Python checks",
                        "Reviewed synthetic profile only; not a general Tableau converter"],
    }
    with tempfile.TemporaryDirectory(prefix=".migration-", dir=ROOT) as temp:
        staging = Path(temp) / "output"
        emit_model(staging, source)
        emit_report(staging, bar_is_stacked(item))
        write_json(staging / "migration.json", manifest)
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists():
            # Swap only after the new project is fully staged.
            shutil.move(str(output), str(Path(temp) / "retired"))
        shutil.move(str(staging), str(output))
    write(mapping, mapping_text())
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook", nargs="?", type=Path, default=ROOT / "sample" / "OrthoSales.twb")
    parser.add_argument("--replace", action="store_true", help="Replace existing output after staging succeeds")
    args = parser.parse_args()
    start = time.perf_counter()
    try:
        manifest = migrate(args.workbook, replace=args.replace)
    except (OSError, ValueError, KeyError, ET.ParseError) as exc:
        print(f"FAIL migration: {exc}")
        return 1
    print(f"PASS generated output\\{NAME}.pbip with {len(manifest['calculated_fields'])} translated fields")
    print(f"Migration script elapsed: {time.perf_counter() - start:.3f}s (not agent time)")
    print("NEXT: python tools\\validate.py; then refresh and inspect in Power BI Desktop.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
