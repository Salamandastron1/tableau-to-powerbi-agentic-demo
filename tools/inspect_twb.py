"""Read Tableau XML without Tableau. Inventory one workbook or a folder."""
import argparse
import csv
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def inspect(path: Path) -> dict:
    root = ET.parse(path).getroot()
    if root.tag != "workbook":
        raise ValueError(f"{path}: expected a Tableau <workbook> root")
    sources, fields, calculations, parameters = [], [], [], []
    for source in root.findall("./datasources/datasource"):
        connection = source.find("connection")
        if connection is not None:
            sources.append({"name": source.get("name"), "caption": source.get("caption"),
                            "connection": dict(connection.attrib)})
        for col in source.findall("column"):
            field = {"source": source.get("name"), **col.attrib}
            calc = col.find("calculation")
            if col.get("param-domain-type"):
                domain = col.find("range")
                parameters.append({**field, "range": dict(domain.attrib) if domain is not None else {}})
            else:
                fields.append(field)
                if calc is not None:
                    calculations.append({**field, "formula": calc.get("formula", "")})
    sheets = []
    for sheet in root.findall("./worksheets/worksheet"):
        sheets.append({
            "name": sheet.get("name"),
            "rows": sheet.findtext("./table/rows", ""),
            "columns": sheet.findtext("./table/cols", ""),
            "marks": [m.get("class") for m in sheet.findall(".//mark")],
            "encodings": [dict(e.attrib, channel=e.tag) for e in sheet.findall(".//encodings/*")],
            "filters": [{"column": f.get("column"), "class": f.get("class"),
                         "definition": ET.tostring(f, encoding="unicode").strip()}
                        for f in sheet.findall(".//filter")],
        })
    dashboards = [{"name": d.get("name"), "worksheets": [
        z.get("name") for z in d.findall(".//zone") if z.get("name")
    ]} for d in root.findall("./dashboards/dashboard")]
    # A transparent sizing heuristic, not a conversion-success prediction.
    table_calcs = sum("LOOKUP(" in c["formula"].upper() for c in calculations)
    lod_calcs = sum("{" in c["formula"] for c in calculations)
    filter_count = len({f["column"] for s in sheets for f in s["filters"]})
    score = len(sheets) + 2 * len(calculations) + 5 * table_calcs + 8 * lod_calcs + filter_count
    return {"path": str(path), "datasources": sources, "fields": fields,
            "calculations": calculations, "parameters": parameters, "worksheets": sheets,
            "dashboards": dashboards, "complexity_score": score,
            "complexity_bucket": "low" if score <= 10 else "medium" if score <= 25 else "high",
            "table_calculations": table_calcs, "lod_calculations": lod_calcs}


def summary(item: dict) -> dict:
    result = {"workbook": item["path"]}
    for key in ("datasources", "fields", "calculations", "worksheets", "parameters", "dashboards"):
        result[key] = len(item[key])
    result["filters"] = len({f["column"] for s in item["worksheets"] for f in s["filters"]})
    for key in ("table_calculations", "lod_calculations", "complexity_score", "complexity_bucket"):
        result[key] = item[key]
    return result


def readable(item: dict) -> str:
    lines = [f"\nWORKBOOK: {item['path']}"]
    for source in item["datasources"]:
        lines.append(f"  SOURCE {source['name']}: {source['connection']}")
    for field in item["fields"]:
        lines.append(f"  FIELD {field['name']} ({field['datatype']}, {field.get('role', '')})")
    for calc in item["calculations"]:
        lines.append(f"  CALC {calc['caption']}: {calc['formula']}")
    for param in item["parameters"]:
        lines.append(f"  PARAMETER {param['caption']}: default={param.get('value')} range={param['range']}")
    for sheet in item["worksheets"]:
        lines.extend([f"  WORKSHEET {sheet['name']}", f"    rows: {sheet['rows']}",
                      f"    columns: {sheet['columns']}; marks: {', '.join(sheet['marks'])}"])
        for encoding in sheet["encodings"]:
            lines.append(f"    {encoding['channel']}: {encoding.get('column')}")
        for filt in sheet["filters"]:
            lines.append(f"    filter: {filt['column']}")
            lines.append(f"      {filt['definition']}")
    for dashboard in item["dashboards"]:
        lines.append(f"  DASHBOARD {dashboard['name']}: {', '.join(dashboard['worksheets'])}")
    lines.append(f"  COMPLEXITY: {item['complexity_score']} ({item['complexity_bucket']}; sizing heuristic only)")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--csv", type=Path, help="Write one summary row per workbook")
    parser.add_argument("--json", action="store_true", help="Print detailed machine-readable inventory")
    args = parser.parse_args()
    paths = sorted(args.path.rglob("*.twb")) if args.path.is_dir() else [args.path]
    if not paths:
        parser.error(f"No .twb files found in {args.path}")
    items, errors = [], []
    for path in paths:
        try:
            items.append(inspect(path))
        except (ET.ParseError, OSError, ValueError) as exc:
            errors.append(f"{path}: {exc}")
    if args.json:
        print(json.dumps({"workbooks": items, "errors": errors}, indent=2))
    else:
        for item in items:
            print(readable(item))
    if args.csv and items:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        with args.csv.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(summary(items[0])))
            writer.writeheader()
            writer.writerows(summary(item) for item in items)
        print(f"Inventory CSV: {args.csv}", file=sys.stderr)
    for error in errors:
        print(f"FAIL {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
