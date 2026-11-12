"""Offline reference parity and PBIP structure checks. Does NOT execute a BI engine."""
import argparse
import csv
import hashlib
import json
import re
import sqlite3
import sys
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

try:
    from .fetch_schemas import cache_path
    from .inspect_twb import inspect
    from .migrate import MODEL, NAME, REPORT, ROOT, bar_is_stacked, check_profile, source_file, text_hash
    from .schema_check import check_document
except ImportError:
    from fetch_schemas import cache_path
    from inspect_twb import inspect
    from migrate import MODEL, NAME, REPORT, ROOT, bar_is_stacked, check_profile, source_file, text_hash
    from schema_check import check_document


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_rows(source):
    with source.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    require(len(rows) > 0, "CSV contains no rows")
    for row in rows:
        row["date"] = date.fromisoformat(row["order_date"])
        row["units"] = int(row["units"])
        row["revenue"] = Decimal(row["revenue"])
        require(row["units"] > 0, "Units must be positive in this fixture")
        require(row["revenue"].is_finite() and row["revenue"] >= 0, "Revenue must be finite and nonnegative")
        require(row["revenue"] * 100 == (row["revenue"] * 100).to_integral_value(), "Revenue must have exact cents")
        require(all(row[k] for k in ("region", "territory", "product_line", "sku")), "Blank dimension")
    return rows


def divide(numerator, denominator):
    return numerator / denominator if denominator else None


def reference_checks(rows, item):
    """Tableau-style Decimal aggregation vs independent SQL integer-cent grouping."""
    formulas = {c["caption"]: c["formula"] for c in item["calculations"]}
    require(re.fullmatch(r"SUM\(\[revenue\]\) / SUM\(\[units\]\)", formulas["Average Selling Price"]),
            "Unsupported Tableau ASP reference formula")
    bucket = re.fullmatch(r"IF \[revenue\] >= (\d+) THEN '([^']+)' ELSE '([^']+)' END", formulas["Revenue Band"])
    require(bucket is not None, "Unsupported Tableau IF reference formula")
    threshold, high, low = Decimal(bucket[1]), bucket[2], bucket[3]
    require(formulas["Order Month"] == "DATETRUNC('month', [order_date])", "Unsupported DATETRUNC formula")
    require("LOOKUP(SUM([revenue]), -12)" in formulas["YoY Revenue Growth"], "Expected 12-mark Tableau lag")
    sql_rows = [(r["order_date"], r["region"], r["product_line"], r["sku"],
                 r["units"], int(r["revenue"] * 100)) for r in rows]
    revenue, units = defaultdict(Decimal), defaultdict(int)
    buckets = defaultdict(int)
    for r in rows:
        revenue[r["region"]] += r["revenue"]
        units[r["region"]] += r["units"]
        buckets[high if r["revenue"] >= threshold else low] += 1
    metrics = {}
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE sales (day TEXT, region TEXT, product TEXT, sku TEXT, units INTEGER, cents INTEGER)")
        db.executemany("INSERT INTO sales VALUES (?, ?, ?, ?, ?, ?)", sql_rows)
        region_sql = db.execute("SELECT region, SUM(cents), SUM(units) FROM sales GROUP BY region").fetchall()
        for region, cents, qty in region_sql:
            require(revenue[region] == Decimal(cents) / 100, f"Revenue mismatch: {region}")
            require(units[region] == qty, f"Units mismatch: {region}")
            require(divide(revenue[region], Decimal(units[region])) == divide(Decimal(cents), Decimal(qty * 100)),
                    f"ASP mismatch: {region}")
            metrics[region] = {"revenue": str(revenue[region]), "units": units[region],
                               "asp": str(divide(revenue[region], Decimal(units[region])).quantize(Decimal("0.01")))}
        total_revenue = sum((r["revenue"] for r in rows), Decimal(0))
        total_units = sum(r["units"] for r in rows)
        total_cents_sql, total_units_sql = db.execute("SELECT SUM(cents), SUM(units) FROM sales").fetchone()
        require(total_revenue == Decimal(total_cents_sql) / 100 and total_units == total_units_sql,
                "Grand-total revenue or units mismatch")
        total_asp = divide(total_revenue, Decimal(total_units))
        require(total_asp == divide(Decimal(total_cents_sql), Decimal(total_units_sql * 100)),
                "Grand-total ASP must be ratio of sums")
        sql_buckets = dict(db.execute(
            "SELECT CASE WHEN cents >= ? THEN ? ELSE ? END, COUNT(*) FROM sales GROUP BY 1",
            (int(threshold * 100), high, low)).fetchall())
        require(dict(buckets) == sql_buckets, "Revenue Band row-level mismatch")
        for r in rows:
            tableau_month = r["date"].replace(day=1).isoformat()
            sql_month = db.execute("SELECT date(?, 'start of month')", (r["order_date"],)).fetchone()[0]
            require(tableau_month == sql_month, "Order Month truncation mismatch")
        contexts = [None] + sorted(revenue)
        yoy_count, top_count = 0, 0
        annual = {}
        for region in contexts:
            subset = [r for r in rows if region is None or r["region"] == region]
            grouped_revenue, grouped_units = defaultdict(Decimal), defaultdict(int)
            for r in subset:
                key = (r["order_date"][:7], r["product_line"])
                grouped_revenue[key] += r["revenue"]
                grouped_units[key] += r["units"]
            monthly_sql = db.execute(
                "SELECT substr(day,1,7), product, SUM(cents), SUM(units) FROM sales "
                "WHERE (? IS NULL OR region = ?) GROUP BY 1,2", (region, region)).fetchall()
            require(len(monthly_sql) == len(grouped_revenue), "Monthly group coverage mismatch")
            for month, product, cents, qty in monthly_sql:
                require(grouped_revenue[month, product] == Decimal(cents) / 100, "Monthly revenue mismatch")
                require(grouped_units[month, product] == qty, "Monthly units by product line mismatch")
            # Tableau LOOKUP indexes displayed marks; compare to calendar-key lookup.
            for product in sorted({r["product_line"] for r in subset}):
                months = sorted(m for m, p in grouped_revenue if p == product)
                require(len(months) == 24, f"LOOKUP(-12) equivalence requires all 24 monthly marks: {region}/{product}")
                for index, month in enumerate(months):
                    current = grouped_revenue[month, product]
                    lag = grouped_revenue[months[index - 12], product] if index >= 12 else None
                    tableau_yoy = divide(current - lag, abs(lag)) if lag is not None else None
                    prior_month = f"{int(month[:4]) - 1}{month[4:]}"
                    prior = db.execute(
                        "SELECT SUM(cents) FROM sales WHERE substr(day,1,7)=? AND product=? "
                        "AND (? IS NULL OR region=?)", (prior_month, product, region, region)).fetchone()[0]
                    calendar_yoy = divide(current - Decimal(prior) / 100, abs(Decimal(prior) / 100)) if prior is not None else None
                    require(tableau_yoy == calendar_yoy, f"YoY mismatch: {region}/{product}/{month}")
                    yoy_count += 1
            yearly = {year: sum((r["revenue"] for r in subset if r["date"].year == year), Decimal(0))
                      for year in (2024, 2025)}
            sql_yearly = {int(year): Decimal(cents) / 100 for year, cents in db.execute(
                "SELECT substr(day,1,4), SUM(cents) FROM sales WHERE (? IS NULL OR region=?) "
                "GROUP BY 1", (region, region)).fetchall()}
            require(yearly == sql_yearly, f"Annual prior-year revenue mismatch: {region}")
            annual[region or "All"] = str(divide(yearly[2025] - yearly[2024], yearly[2024]))
            sku_totals = defaultdict(Decimal)
            for r in subset:
                sku_totals[r["sku"]] += r["revenue"]
            for n in (1, 5, 10, 20):
                winners = sorted(sku_totals, key=lambda sku: (-sku_totals[sku], sku))[:n]
                sql_top = db.execute(
                    "SELECT sku, SUM(cents) AS total FROM sales WHERE (? IS NULL OR region=?) "
                    "GROUP BY sku ORDER BY total DESC, sku ASC LIMIT ?", (region, region, n)).fetchall()
                require(winners == [sku for sku, _ in sql_top], f"Top {n} mismatch: {region}")
                require(sum((sku_totals[sku] for sku in winners), Decimal(0)) ==
                        Decimal(sum(cents for _, cents in sql_top)) / 100, "Top N grand-total mismatch")
                top_count += 1
    require(divide(Decimal(1), Decimal(0)) is None, "Zero denominator must be BLANK")
    return {
        "rows": len(rows), "regions": metrics, "revenue_bands": dict(buckets),
        "yoy_contexts": yoy_count, "top_n_contexts": top_count, "annual_yoy": annual,
        "total_revenue": str(total_revenue), "total_units": total_units,
        "total_asp": str(total_asp.quantize(Decimal("0.01"))),
    }


def norm(expression):
    return re.sub(r"\s+", "", expression)


def declarations(text, kind):
    result = {}
    for match in re.finditer(r"^\t" + kind + r" ('(?:[^']|'')*'|[A-Za-z_]\w*)(?: = (.*))?$", text, re.MULTILINE):
        name = match[1].strip("'").replace("''", "'")
        require(name not in result, f"Duplicate {kind}: {name}")
        result[name] = match[2]
    return result


def model_checks(output, source):
    definition = output / MODEL / "definition"
    expected_files = {"database.tmdl", "model.tmdl", "expressions.tmdl", "relationships.tmdl",
                      "tables\\Sales.tmdl", "tables\\Calendar.tmdl", "tables\\Top N.tmdl"}
    actual_files = {str(p.relative_to(definition)) for p in definition.rglob("*.tmdl")}
    require(actual_files == expected_files, f"Unexpected/missing TMDL files: {actual_files ^ expected_files}")
    texts = {str(p.relative_to(definition)): p.read_text(encoding="utf-8") for p in definition.rglob("*.tmdl")}
    for name, text in texts.items():
        require("\x00" not in text and "..." not in text, f"Invalid placeholder or null in {name}")
        require(not re.search(r"^ +\S", text, re.MULTILINE), f"Expected tab-indented generated TMDL: {name}")
    require(texts["database.tmdl"].strip() == "database\n\tcompatibilityLevel: 1601", "Database metadata mismatch")
    refs = re.findall(r"^\tref table (.+)$", texts["model.tmdl"], re.MULTILINE)
    require(set(refs) == {"Sales", "Calendar", "'Top N'"}, "Model table references mismatch")
    sales = texts["tables\\Sales.tmdl"]
    measures = declarations(sales, "measure")
    expected = {
        "Total Revenue": "SUM('Sales'[revenue])", "Total Units": "SUM('Sales'[units])",
        "Average Selling Price": "DIVIDE([Total Revenue], [Total Units])",
        "Revenue Prior Year": "CALCULATE([Total Revenue], DATEADD('Calendar'[Date], -1, YEAR))",
        "YoY Revenue Growth": "DIVIDE([Total Revenue] - [Revenue Prior Year], ABS([Revenue Prior Year]))",
        "Revenue Band": "SELECTEDVALUE('Sales'[Revenue Band Value])",
        "Order Month": "SELECTEDVALUE('Sales'[Order Month Value])",
        "Selected Top N": "SELECTEDVALUE('Top N'[Value], 10)",
        "Top N Revenue": "VAR Winners = TOPN([Selected Top N], ALLSELECTED('Sales'[sku]), "
                         "[Total Revenue], DESC, 'Sales'[sku], ASC) "
                         "RETURN CALCULATE([Total Revenue], KEEPFILTERS(Winners))",
    }
    require(set(measures) == set(expected), "Missing or unexpected DAX measures")
    for name, expression in expected.items():
        require(norm(measures[name]) == norm(expression), f"Emitted DAX differs from reviewed translation: {name}")
    columns = declarations(sales, "column")
    require(columns.get("Revenue Band Value") == 'IF(\'Sales\'[revenue] >= 10000, "Large", "Standard")',
            "Revenue Band calculated column mismatch")
    require(columns.get("Order Month Value") == "DATE(YEAR('Sales'[order_date]), MONTH('Sales'[order_date]), 1)",
            "Order Month calculated column mismatch")
    require(set(columns) == {"order_date", "region", "territory", "product_line", "sku", "units", "revenue",
                             "Revenue Band Value", "Order Month Value"}, "Sales column coverage mismatch")
    for name, dtype in (("order_date", "dateTime"), ("units", "int64"), ("revenue", "decimal")):
        require(re.search(rf"\tcolumn {name}\n\t\tdataType: {dtype}\n", sales), f"Type mismatch: {name}")
    expressions = texts["expressions.tmdl"]
    path_match = re.search(r'^expression DataFilePath = "((?:[^"]|"")*)"', expressions, re.MULTILINE)
    require(path_match is not None, "Missing DataFilePath Power Query parameter")
    require(Path(path_match[1].replace('""', '"')).resolve() == source.resolve(), "Power Query CSV path does not match Tableau source")
    for token in ("Csv.Document(File.Contents(DataFilePath)", 'Columns=7', 'Encoding=65001',
                  'Table.PromoteHeaders', '"revenue", Currency.Type', '"units", Int64.Type',
                  '"order_date", type date', '"en-US"'):
        require(token in expressions, f"Missing Power Query source/type conversion: {token}")
    require("\tpartition Sales = m\n\t\tmode: import\n\t\tsource = SalesSource" in sales, "Sales partition mismatch")
    calendar = texts["tables\\Calendar.tmdl"]
    for token in ("dataCategory: Time", "\t\tisKey", "Date.StartOfYear", "Date.EndOfYear", "List.Dates",
                  'Date.ToText([Date], "yyyy-MM", "en-US")'):
        require(token in calendar, f"Missing calendar requirement: {token}")
    relationship = texts["relationships.tmdl"]
    for token in ("fromColumn: Sales.order_date", "toColumn: Calendar.Date", "fromCardinality: many",
                  "toCardinality: one", "crossFilteringBehavior: oneDirection"):
        require(token in relationship, f"Relationship mismatch: {token}")
    require("GENERATESERIES(1, 20, 1)" in texts["tables\\Top N.tmdl"], "Top N domain mismatch")
    return {
        "Sales": {"columns": set(columns), "measures": set(measures)},
        "Calendar": {"columns": {"Date", "Month"}, "measures": set()},
        "Top N": {"columns": {"Value"}, "measures": set()},
    }


def report_checks(output, symbols, stacked=False):
    report = output / REPORT
    page = report / "definition" / "pages" / "Overview"
    required = [output / f"{NAME}.pbip", report / "definition.pbir", output / MODEL / "definition.pbism",
                report / "definition" / "version.json", report / "definition" / "report.json",
                page.parent / "pages.json", page / "page.json"]
    for path in required:
        require(path.is_file(), f"Missing project artifact: {path}")
    for path in output.rglob("*"):
        if path.suffix in (".pbip", ".pbir", ".pbism", ".json"):
            document = json.loads(path.read_text(encoding="utf-8"))
            if path.name != "migration.json":
                check_document(document)
    project = json.loads((output / f"{NAME}.pbip").read_text())
    require(project["artifacts"] == [{"report": {"path": REPORT}}], "PBIP report pointer mismatch")
    pbir = json.loads((report / "definition.pbir").read_text())
    require(pbir["datasetReference"] == {"byPath": {"path": f"../{MODEL}"}}, "Report model pointer mismatch")
    require(pbir["version"] == "4.0", "Expected PBIR enhanced report version 4.0")
    pbism = json.loads((output / MODEL / "definition.pbism").read_text())
    require(pbism["version"] == "4.0", "TMDL requires PBISM version 4.0 or above")
    metadata = json.loads((page.parent / "pages.json").read_text())
    require(metadata["pageOrder"] == ["Overview"] and metadata["activePageName"] == "Overview", "Page order mismatch")
    page_doc = json.loads((page / "page.json").read_text())
    expected = {
        "Region": ("slicer", {"Values": [("Sales", "region", False)]}),
        "TopN": ("slicer", {"Values": [("Top N", "Value", False)]}),
        "RevenueByRegion": ("barChart", {"Category": [("Sales", "region", False)],
                                         "Series": [("Sales", "product_line", False)],
                                         "Y": [("Sales", "Total Revenue", True)]}) if stacked else (
            "clusteredBarChart", {"Category": [("Sales", "region", False)],
                                  "Y": [("Sales", "Total Revenue", True)]}),
        "MonthlyUnits": ("lineChart", {"Category": [("Calendar", "Month", False)],
                                       "Series": [("Sales", "product_line", False)],
                                       "Y": [("Sales", "Total Units", True)]}),
        "TopSKUs": ("tableEx", {"Values": [("Sales", "sku", False), ("Sales", "Top N Revenue", True)]}),
    }
    paths = list(page.rglob("visual.json"))
    require({p.parent.name for p in paths} == set(expected), "Missing or unexpected dashboard visuals")
    for path in paths:
        visual = json.loads(path.read_text())
        name = path.parent.name
        require(visual["name"] == name, f"Visual name/folder mismatch: {name}")
        config, pos = visual["visual"], visual["position"]
        require(0 <= pos["x"] and pos["x"] + pos["width"] <= page_doc["width"], f"Visual outside page width: {name}")
        require(0 <= pos["y"] and pos["y"] + pos["height"] <= page_doc["height"], f"Visual outside page height: {name}")
        kind, roles = expected[name]
        require(config["visualType"] == kind, f"Visual type mismatch: {name}")
        actual = {}
        for role, state in config["query"]["queryState"].items():
            bindings = []
            require(not state.get("showAll", False), "Top N blank suppression requires showAll disabled")
            for proj in state["projections"]:
                is_measure = "Measure" in proj["field"]
                expression = proj["field"]["Measure" if is_measure else "Column"]
                table, prop = expression["Expression"]["SourceRef"]["Entity"], expression["Property"]
                require(table in symbols and prop in symbols[table]["measures" if is_measure else "columns"],
                        f"Unknown semantic model field: {table}.{prop}")
                bindings.append((table, prop, is_measure))
            actual[role] = bindings
        require(actual == roles, f"Worksheet-role binding mismatch: {name}")
    top = json.loads((page / "visuals" / "TopN" / "visual.json").read_text())
    objects = top["visual"]["objects"]
    require(objects["selection"][0]["properties"]["strictSingleSelect"]["expr"]["Literal"]["Value"] == "true",
            "Top N slicer must be single select")
    require(objects["data"][0]["properties"]["mode"]["expr"]["Literal"]["Value"] == "'Dropdown'",
            "Top N numeric slicer must use dropdown, not a Between range")
    selected = objects["general"][0]["properties"]["filter"]["filter"]
    require(selected == {
        "Version": 2,
        "From": [{"Name": "topn", "Entity": "Top N", "Type": 0}],
        "Where": [{"Condition": {"In": {
            "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "topn"}}, "Property": "Value"}}],
            "Values": [[{"Literal": {"Value": "10L"}}]],
        }}}],
    }, "Top N slicer must open at 10")
    for name, direction in (("MonthlyUnits", "Ascending"), ("TopSKUs", "Descending")):
        visual = json.loads((page / "visuals" / name / "visual.json").read_text())
        require(visual["visual"]["query"]["sortDefinition"]["sort"][0]["direction"] == direction,
                f"Required sort missing: {name}")
    return len(paths)


def validate(output=ROOT / "output", mapping=ROOT / "docs" / "mapping.md"):
    results, metrics = [], {}

    def run(label, action):
        try:
            value = action()
            results.append({"status": "PASS", "check": label})
            return value
        except (OSError, ValueError, KeyError, IndexError, TypeError, ArithmeticError, ET.ParseError, sqlite3.Error) as exc:
            results.append({"status": "FAIL", "check": label, "error": str(exc)})
            return None

    def schemas():
        manifest = json.loads((ROOT / "schemas" / "manifest.json").read_text())
        for url, expected_hash in manifest["sha256"].items():
            content = cache_path(url).read_bytes().replace(b"\r\n", b"\n")
            require(hashlib.sha256(content).hexdigest() == expected_hash, f"Schema cache hash mismatch: {url}")
    run("Official Microsoft schema cache integrity (offline)", schemas)

    def inputs():
        manifest = json.loads((output / "migration.json").read_text())
        require(manifest["profile"] == "orthosales-v1", "Unsupported migration profile")
        workbook = (ROOT / manifest["workbook"]).resolve()
        require(workbook.is_relative_to(ROOT), "Workbook must stay inside repository")
        item = inspect(workbook)
        check_profile(item)
        source = source_file(workbook, item)
        require(source == (ROOT / manifest["source"]).resolve(), "Manifest/Tableau data source mismatch")
        require(text_hash(workbook) == manifest["workbook_sha256"], "Source workbook changed after migration")
        require(text_hash(source) == manifest["source_sha256"], "Source CSV changed after migration")
        require(set(manifest["calculated_fields"]) == {c["caption"] for c in item["calculations"]}, "Calculated-field inventory mismatch")
        return item, source
    input_result = run("Source lineage, supported Tableau formulas, shelves, filters and parameter", inputs)
    if input_result:
        item, source = input_result
        rows = run("CSV types, nonempty dimensions and exact currency cents", lambda: read_rows(source))
        if rows is not None:
            reference = run("Independent Decimal vs SQL parity: regional revenue/ASP, monthly units, YoY, IF, DATETRUNC, Top N",
                            lambda: reference_checks(rows, item))
            if reference:
                metrics.update(reference)
        symbols = run("TMDL structure, typed Power Query, calendar relationship and all reviewed DAX expressions",
                      lambda: model_checks(output, source))
        if symbols:
            run("PBIP/PBISM/PBIR official-schema checks, 5 visuals, slicers, bindings, page bounds and sorting",
                lambda: report_checks(output, symbols, bar_is_stacked(item)))

        def mapping_check():
            text = mapping.read_text(encoding="utf-8")
            for calc in item["calculations"]:
                require(calc["caption"] in text and calc["formula"] in text, f"Mapping missing {calc['caption']}")
                require(calc["caption"] in symbols["Sales"]["measures"], f"No DAX measure for {calc['caption']}")
        if symbols:
            run("Every Tableau calculated field documented and backed by a DAX measure", mapping_check)
    return {"ok": bool(results) and all(r["status"] == "PASS" for r in results),
            "checks": results, "metrics": metrics,
            "not_verified": ["Tableau application opening/rendering", "Power BI Desktop opening/refresh/rendering",
                             "Power Query and DAX engine execution", "VS Code interactive agent latency"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "output")
    parser.add_argument("--mapping", type=Path, default=ROOT / "docs" / "mapping.md")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    start = time.perf_counter()
    report = validate(args.output, args.mapping)
    report["elapsed_seconds"] = round(time.perf_counter() - start, 3)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for result in report["checks"]:
            print(f"{result['status']} {result['check']}" + (f": {result['error']}" if "error" in result else ""))
        for region, metric in report["metrics"].get("regions", {}).items():
            print(f"  {region}: revenue=${metric['revenue']}, units={metric['units']}, ASP=${metric['asp']}")
        if report["metrics"]:
            print(f"  Total: ${report['metrics']['total_revenue']}; {report['metrics']['total_units']} units; "
                  f"ASP=${report['metrics']['total_asp']}; "
                  f"{report['metrics']['yoy_contexts']} YoY contexts; {report['metrics']['top_n_contexts']} Top N contexts")
        print(f"{'PASS' if report['ok'] else 'FAIL'} offline validation ({report['elapsed_seconds']:.3f}s)")
        print("NOT VERIFIED: " + "; ".join(report["not_verified"]))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
