"""Write preview/index.html: Tableau definition vs generated Power BI definition, side by side.

Local preview renderer only. Values are computed in Python from each side's definition; neither
Tableau nor Power BI is executed.
"""
import argparse
import csv
import difflib
import html
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

try:
    from .inspect_twb import inspect
    from .migrate import MODEL, REPORT, ROOT
    from .validate import declarations, validate
except ImportError:
    from inspect_twb import inspect
    from migrate import MODEL, REPORT, ROOT
    from validate import declarations, validate

PREVIEW = ROOT / "preview" / "index.html"
REGIONS = ("All", "Central", "East", "South", "West")


def load_rows(source):
    with source.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        row["units"] = int(row["units"])
        row["revenue"] = Decimal(row["revenue"])
    return rows


def ranked(totals):
    return [[k, float(v)] for k, v in sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))]


# ---------- Tableau side: interpret worksheet shelves from the .twb ----------

def tableau_side(workbook, item, rows):
    root = ET.parse(workbook).getroot()
    calcs = {c["name"].strip("[]"): c["formula"] for c in item["calculations"]}

    def resolve(ref):
        match = re.fullmatch(r"\[[^\]]+\]\.\[(\w+):([^:\]]+):\w+\]", ref.strip())
        if not match:
            raise ValueError(f"Unsupported shelf reference: {ref}")
        derivation, column = match.groups()
        formula = calcs.get(column)
        if formula == "DATETRUNC('month', [order_date])":
            return derivation, lambda r: r["order_date"][:7]
        if formula is not None:
            raise ValueError(f"Preview does not interpret calculation {column}")
        return derivation, (lambda r, c=column: r[c])

    sheets = {s.get("name"): s for s in root.findall("./worksheets/worksheet")}
    spec = {s["name"]: s for s in item["worksheets"]}
    out = {}
    for region in REGIONS:
        subset = [r for r in rows if region == "All" or r["region"] == region]
        result = {}
        bar = spec["Revenue by Region"]
        _, dim = resolve(bar["rows"])
        deriv, measure = resolve(bar["columns"])
        if deriv != "sum":
            raise ValueError("Preview supports SUM aggregation only")
        series = [e for e in bar["encodings"] if e["channel"] == "color"]
        series_key = resolve(series[0]["column"])[1] if series else (lambda r: "")
        totals = defaultdict(Decimal)
        for r in subset:
            totals[(dim(r), series_key(r))] += measure(r)
        # Tableau without an explicit sort orders dimension members alphabetically.
        result["bar"] = [[c, s, float(v)] for (c, s), v in sorted(totals.items())]
        line = spec["Monthly Units by Product Line"]
        _, measure = resolve(line["rows"])[0], resolve(line["rows"])[1]
        _, month = resolve(line["columns"])
        _, color = resolve(line["encodings"][0]["column"])
        points = defaultdict(int)
        for r in subset:
            points[(color(r), month(r))] += measure(r)
        result["line"] = {}
        for (s, m), v in sorted(points.items()):
            result["line"].setdefault(s, []).append([m, v])
        top = sheets["Top SKUs"].find(".//filter[@column='[ortho_sales].[none:sku:nk]']/groupfilter/groupfilter")
        if top is None or top.get("expression") != "SUM([revenue])" or top.get("direction") != "DESC":
            raise ValueError("Preview supports Top N by SUM([revenue]) descending only")
        sku_totals = defaultdict(Decimal)
        for r in subset:
            sku_totals[r["sku"]] += r["revenue"]
        result["top"] = ranked(sku_totals)
        out[region] = result
    return out


# ---------- Power BI side: interpret PBIR bindings and DAX measure definitions ----------

def pbi_side(output, rows):
    sales = (output / MODEL / "definition" / "tables" / "Sales.tmdl").read_text(encoding="utf-8")
    measures = declarations(sales, "measure")
    relationship = (output / MODEL / "definition" / "relationships.tmdl").read_text(encoding="utf-8")
    if "fromColumn: Sales.order_date" not in relationship or "toColumn: Calendar.Date" not in relationship:
        raise ValueError("Preview needs the Sales->Calendar relationship")

    def column(binding):
        table, name = binding["Expression"]["SourceRef"]["Entity"], binding["Property"]
        if table == "Sales":
            return lambda r: r[name]
        if (table, name) == ("Calendar", "Month"):
            return lambda r: r["order_date"][:7]
        raise ValueError(f"Preview cannot bind column {table}.{name}")

    def measure(name):
        expression = measures.get(name)
        if expression is None:
            raise ValueError(f"Measure not defined in TMDL: {name}")
        match = re.fullmatch(r"SUM\('Sales'\[(\w+)\]\)", expression.strip())
        if match:
            return lambda r, c=match[1]: r[c]
        if name == "Top N Revenue" and "TOPN([Selected Top N], ALLSELECTED('Sales'[sku]), [Total Revenue], DESC, 'Sales'[sku], ASC)" in expression:
            return measure("Total Revenue")
        raise ValueError(f"Preview cannot evaluate DAX for {name}: {expression}")

    def load(name):
        path = output / REPORT / "definition" / "pages" / "Overview" / "visuals" / name / "visual.json"
        visual = json.loads(path.read_text(encoding="utf-8"))["visual"]
        roles = {role: [p["field"] for p in state["projections"]] for role, state in visual["query"]["queryState"].items()}
        return visual, roles

    bar_visual, bar = load("RevenueByRegion")
    line_visual, line = load("MonthlyUnits")
    top_visual, top = load("TopSKUs")
    out = {}
    for region in REGIONS:
        # Region slicer filters every visual on the page.
        subset = [r for r in rows if region == "All" or r["region"] == region]
        result = {}
        cat = column(bar["Category"][0]["Column"])
        series = column(bar["Series"][0]["Column"]) if "Series" in bar else (lambda r: "")
        value = measure(bar["Y"][0]["Measure"]["Property"])
        totals, by_category = defaultdict(Decimal), defaultdict(Decimal)
        for r in subset:
            totals[(cat(r), series(r))] += value(r)
            by_category[cat(r)] += value(r)
        descending = bar_visual["query"]["sortDefinition"]["sort"][0]["direction"] == "Descending"
        order = sorted(by_category, key=lambda c: (-by_category[c], c) if descending else (by_category[c], c))
        result["bar"] = [[c, s, float(v)] for c in order for (cc, s), v in sorted(totals.items()) if cc == c]
        month, color = column(line["Category"][0]["Column"]), column(line["Series"][0]["Column"])
        units = measure(line["Y"][0]["Measure"]["Property"])
        points = defaultdict(int)
        for r in subset:
            points[(color(r), month(r))] += units(r)
        result["line"] = {}
        for (s, m), v in sorted(points.items()):
            result["line"].setdefault(s, []).append([m, v])
        sku, revenue = column(top["Values"][0]["Column"]), measure(top["Values"][1]["Measure"]["Property"])
        sku_totals = defaultdict(Decimal)
        for r in subset:
            sku_totals[sku(r)] += revenue(r)
        result["top"] = ranked(sku_totals)
        out[region] = result
    return out, {"bar": bar_visual["visualType"], "line": line_visual["visualType"], "top": top_visual["visualType"]}


def same_values(a, b):
    def bar_map(items):
        return {(c, s): round(v, 2) for c, s, v in items}
    return {
        "bar": all(bar_map(a[r]["bar"]) == bar_map(b[r]["bar"]) for r in REGIONS),
        "line": all(a[r]["line"] == b[r]["line"] for r in REGIONS),
        "top": all(a[r]["top"] == b[r]["top"] for r in REGIONS),
    }


def snippets(workbook, output, item):
    root = ET.parse(workbook).getroot()
    sales = (output / MODEL / "definition" / "tables" / "Sales.tmdl").read_text(encoding="utf-8")
    measure_lines = {}
    for match in re.finditer(r"^\tmeasure ('(?:[^']|'')*'|\w+) = (.*)$", sales, re.MULTILINE):
        measure_lines[match[1].strip("'")] = match[0].strip()

    def sheet_xml(name):
        table = root.find(f"./worksheets/worksheet[@name='{name}']/table")
        text = ET.tostring(table, encoding="unicode")
        return re.sub(r"\s*<style />", "", text)

    def visual_json(name):
        path = output / REPORT / "definition" / "pages" / "Overview" / "visuals" / name / "visual.json"
        visual = json.loads(path.read_text(encoding="utf-8"))
        visual.pop("$schema", None)
        visual["visual"].pop("visualContainerObjects", None)
        return json.dumps(visual["visual"]["query"], indent=1)

    calc_rows = []
    for calc in item["calculations"]:
        calc_rows.append([calc["caption"], calc["formula"], measure_lines.get(calc["caption"], "MISSING")])
    return {
        "bar": [sheet_xml("Revenue by Region"),
                visual_json("RevenueByRegion") + "\n\n" + measure_lines.get("Total Revenue", "")],
        "line": [sheet_xml("Monthly Units by Product Line") + "\n\nOrder Month = DATETRUNC('month', [order_date])",
                 visual_json("MonthlyUnits") + "\n\n" + measure_lines.get("Total Units", "")],
        "top": [sheet_xml("Top SKUs") + "\n\nParameter Top N: default 10, range 1-20",
                visual_json("TopSKUs") + "\n\n" + measure_lines.get("Selected Top N", "") + "\n"
                + measure_lines.get("Top N Revenue", "")],
        "calcs": calc_rows,
    }


def changes(output):
    baseline = ROOT / "prebuilt" / "output"

    def lines(path):
        text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        # The fallback stores a machine-neutral CSV path; compare structure, not checkout location.
        text = re.sub(r'^expression DataFilePath = ".*?"', 'expression DataFilePath = "<checkout>"', text, flags=re.M)
        text = re.sub(r'"workbook_sha256": "\w+"', '"workbook_sha256": "<hash>"', text)
        return text.splitlines()

    files = sorted({p.relative_to(output) for p in output.rglob("*") if p.is_file()} |
                   {p.relative_to(baseline) for p in baseline.rglob("*") if p.is_file()})
    result = []
    for rel in files:
        old, new = baseline / rel, output / rel
        a = lines(old) if old.is_file() else []
        b = lines(new) if new.is_file() else []
        if a != b:
            diff = "\n".join(difflib.unified_diff(a, b, f"prebuilt/output/{rel.as_posix()}",
                                                  f"output/{rel.as_posix()}", lineterm="", n=2))
            result.append({"file": rel.as_posix(), "diff": diff})
    return result


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>OrthoSales: Tableau vs Power BI definition preview</title>
<style>
body{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#f5f6f8;color:#1b1b1b}
header{background:#1f2937;color:#fff;padding:12px 20px}
header h1{font-size:20px;margin:0 0 4px}
.note{background:#fff4ce;color:#4a3b00;padding:8px 20px;font-size:14px;border-bottom:1px solid #e0c96b}
.controls{padding:10px 20px;background:#fff;border-bottom:1px solid #ddd;display:flex;gap:24px;align-items:center;flex-wrap:wrap}
.tabs button{padding:6px 14px;border:1px solid #888;background:#fff;cursor:pointer}
.tabs button.on{background:#1f2937;color:#fff}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:12px 20px}
.card{background:#fff;border:1px solid #ddd;border-radius:6px;padding:10px;min-width:0}
.card h3{margin:0 0 6px;font-size:15px}
.side{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:#555}
pre{background:#0f172a;color:#e2e8f0;padding:8px;font-size:11px;overflow:auto;max-height:260px;white-space:pre-wrap;word-break:break-word}
.status{padding:4px 20px;font-size:14px}
.ok{color:#0a7d27;font-weight:600}.bad{color:#b00020;font-weight:600}
table.t{border-collapse:collapse;font-size:12px;width:100%}
table.t td,table.t th{border-bottom:1px solid #eee;padding:3px 6px;text-align:left}
table.t td.n{text-align:right}
.diff .add{color:#86efac}.diff .del{color:#fca5a5}
.legend span{display:inline-block;margin-right:10px;font-size:11px}
.legend i{display:inline-block;width:10px;height:10px;margin-right:3px}
</style></head><body>
<header><h1>OrthoSales (synthetic): Tableau definition vs generated Power BI definition</h1>
<div>Workbook: __WORKBOOK__ &middot; generated __STAMP__</div></header>
<div class="note">Preview rendered from the definitions with a local renderer (preview renderer, not Power BI, not Tableau).
Final validation happens in Power BI Desktop or the Power BI service.</div>
<div class="controls">
<label>Region <select id="region"></select></label>
<label>Top N <input id="topn" type="number" min="1" max="20" value="10" style="width:60px"></label>
<span class="tabs"><button id="tab-view" class="on">Side by side</button> <button id="tab-changes">Changes (__NCHANGES__ files)</button></span>
<span>validate.py: <b class="__VCLASS__">__VSTATUS__</b></span>
</div>
<div id="view"></div>
<div id="changes" style="display:none"></div>
<script>
const D = __DATA__;
const COLORS = ["#2563eb","#f59e0b","#10b981","#ef4444","#8b5cf6","#0891b2"];
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const money = v => "$" + Math.round(v).toLocaleString("en-US");
function bars(items, title){
  const cats=[...new Set(items.map(i=>i[0]))], series=[...new Set(items.map(i=>i[1]))];
  const tot={}; items.forEach(i=>tot[i[0]]=(tot[i[0]]||0)+i[2]);
  const max=Math.max(...Object.values(tot)); const W=520,rowH=34,left=70;
  let s=`<svg width="100%" viewBox="0 0 ${W} ${cats.length*rowH+10}" role="img" aria-label="${esc(title)}">`;
  cats.forEach((c,ci)=>{ let x=left; const y=ci*rowH+5;
    s+=`<text x="${left-6}" y="${y+18}" font-size="12" text-anchor="end">${esc(c)}</text>`;
    items.filter(i=>i[0]===c).forEach(i=>{ const w=(W-left-90)*i[2]/max; const k=series.indexOf(i[1]);
      s+=`<rect x="${x}" y="${y}" width="${w}" height="24" fill="${COLORS[k%COLORS.length]}"><title>${esc(c)} ${esc(i[1])} ${money(i[2])}</title></rect>`; x+=w; });
    s+=`<text x="${x+4}" y="${y+17}" font-size="11">${money(tot[c])}</text>`; });
  s+="</svg>";
  if(series.length>1||series[0]) s+=`<div class="legend">${series.map((x,k)=>`<span><i style="background:${COLORS[k%COLORS.length]}"></i>${esc(x)}</span>`).join("")}</div>`;
  return s;
}
function lines(data){
  const keys=Object.keys(data); const months=[...new Set(keys.flatMap(k=>data[k].map(p=>p[0])))].sort();
  const max=Math.max(...keys.flatMap(k=>data[k].map(p=>p[1]))); const W=520,H=220,L=40,B=24;
  const x=m=>L+(W-L-10)*months.indexOf(m)/(months.length-1), y=v=>H-B-(H-B-10)*v/max;
  let s=`<svg width="100%" viewBox="0 0 ${W} ${H}"><line x1="${L}" y1="${H-B}" x2="${W}" y2="${H-B}" stroke="#999"/>`;
  [0,months.length-1].forEach(i=>s+=`<text x="${x(months[i])}" y="${H-6}" font-size="10" text-anchor="middle">${months[i]}</text>`);
  s+=`<text x="${L-4}" y="${y(max)+4}" font-size="10" text-anchor="end">${max}</text>`;
  keys.forEach((k,i)=>{ s+=`<polyline fill="none" stroke-width="2" stroke="${COLORS[i%COLORS.length]}" points="${data[k].map(p=>x(p[0])+","+y(p[1])).join(" ")}"><title>${esc(k)}</title></polyline>`; });
  return s+`</svg><div class="legend">${keys.map((k,i)=>`<span><i style="background:${COLORS[i%COLORS.length]}"></i>${esc(k)}</span>`).join("")}</div>`;
}
function table(rows,n){
  const shown=rows.slice(0,n); const total=shown.reduce((a,r)=>a+r[1],0);
  return `<table class="t"><tr><th>SKU</th><th>Revenue</th></tr>${shown.map(r=>`<tr><td>${esc(r[0])}</td><td class="n">${money(r[1])}</td></tr>`).join("")}<tr><th>Total (top ${shown.length})</th><th class="n">${money(total)}</th></tr></table>`;
}
function check(ok, label){ return `<span class="${ok?"ok":"bad"}">${ok?"&#10004;":"&#10008;"} ${esc(label)}</span>`; }
function pair(key, title, tTitle, pTitle, tBody, pBody){
  const v=D.validate[key], same=D.same[key];
  return `<div class="status"><b>${esc(title)}</b> &nbsp; ${check(same,"both renderers produce identical values (all 5 Region contexts)")} &nbsp; ${check(v.ok, "validate.py: "+v.label)}</div>
  <div class="pair"><div class="card"><div class="side">Tableau &middot; ${esc(tTitle)}</div>${tBody}</div>
  <div class="card"><div class="side">Power BI &middot; ${esc(pTitle)}</div>${pBody}</div></div>
  <div class="pair"><div class="card"><div class="side">Tableau source (.twb XML)</div><pre>${esc(D.snippets[key][0])}</pre></div>
  <div class="card"><div class="side">Generated code (PBIR query + DAX)</div><pre>${esc(D.snippets[key][1])}</pre></div></div>`;
}
function render(){
  const r=document.getElementById("region").value; let n=parseInt(document.getElementById("topn").value,10);
  if(!(n>=1&&n<=20)){n=10;} const T=D.tableau[r], P=D.pbi[r];
  let h=pair("bar","Revenue by Region", D.tableauMarks.bar, D.pbiTypes.bar, bars(T.bar,"Tableau bar"), bars(P.bar,"Power BI bar"));
  h+=pair("line","Monthly Units by Product Line", D.tableauMarks.line, D.pbiTypes.line, lines(T.line), lines(P.line));
  h+=pair("top","Top N SKUs by Revenue (Top N = "+n+")", D.tableauMarks.top, D.pbiTypes.top, table(T.top,n), table(P.top,n));
  h+=`<div class="status"><b>Calculated fields</b> &nbsp; ${check(D.validate.calcs.ok,"validate.py: "+D.validate.calcs.label)}</div>
  <div class="pair"><div class="card" style="grid-column:1 / span 2"><table class="t"><tr><th>Tableau field</th><th>Tableau formula</th><th>Generated DAX (TMDL)</th></tr>
  ${D.snippets.calcs.map(c=>`<tr><td>${esc(c[0])}</td><td><code>${esc(c[1])}</code></td><td><code>${esc(c[2])}</code></td></tr>`).join("")}</table></div></div>`;
  document.getElementById("view").innerHTML=h;
}
function renderChanges(){
  const c=D.changes; let h=`<div class="status">Generated <code>output/</code> compared with the reviewed <code>prebuilt/output/</code> baseline (checkout path normalized).</div>`;
  if(!c.length) h+=`<div class="status ok">No differences: output matches the prebuilt baseline.</div>`;
  c.forEach(f=>{ h+=`<div class="pair"><div class="card" style="grid-column:1 / span 2"><h3>${esc(f.file)}</h3><pre class="diff">${esc(f.diff).split("\n").map(l=>l.startsWith("+")?`<span class="add">${l}</span>`:l.startsWith("-")?`<span class="del">${l}</span>`:l).join("\n")}</pre></div></div>`; });
  document.getElementById("changes").innerHTML=h;
}
const sel=document.getElementById("region"); ["All","Central","East","South","West"].forEach(r=>sel.add(new Option(r,r)));
sel.onchange=render; document.getElementById("topn").oninput=render;
document.getElementById("tab-view").onclick=()=>{view.style.display="";changes.style.display="none";document.getElementById("tab-view").className="on";document.getElementById("tab-changes").className="";};
document.getElementById("tab-changes").onclick=()=>{view.style.display="none";changes.style.display="";document.getElementById("tab-changes").className="on";document.getElementById("tab-view").className="";};
render(); renderChanges();
</script></body></html>
"""


def build(output=ROOT / "output", target=PREVIEW):
    manifest = json.loads((output / "migration.json").read_text(encoding="utf-8"))
    workbook = (ROOT / manifest["workbook"]).resolve()
    item = inspect(workbook)
    rows = load_rows((ROOT / manifest["source"]).resolve())
    report = validate(output)
    status = {c["check"]: c["status"] == "PASS" for c in report["checks"]}

    def find(prefix):
        hit = [k for k in status if k.startswith(prefix)]
        return {"ok": bool(hit) and all(status[k] for k in hit), "label": hit[0] if hit else f"{prefix} (not run)"}

    tableau = tableau_side(workbook, item, rows)
    pbi, types = pbi_side(output, rows)
    marks = {s["name"]: s["marks"][0] for s in item["worksheets"]}
    bar_sheet = next(s for s in item["worksheets"] if s["name"] == "Revenue by Region")
    data = {
        "tableau": tableau, "pbi": pbi, "pbiTypes": types,
        "tableauMarks": {"bar": marks["Revenue by Region"] + (" (stacked by color)" if bar_sheet["encodings"] else ""),
                         "line": marks["Monthly Units by Product Line"], "top": marks["Top SKUs"] + " table"},
        "same": same_values(tableau, pbi),
        "validate": {
            "bar": find("Independent Decimal vs SQL parity"), "line": find("Independent Decimal vs SQL parity"),
            "top": find("PBIP/PBISM/PBIR"), "calcs": find("Every Tableau calculated field"),
        },
        "snippets": snippets(workbook, output, item),
        "changes": changes(output),
    }
    page = (PAGE.replace("__DATA__", json.dumps(data).replace("</", "<\\/"))
            .replace("__WORKBOOK__", html.escape(manifest["workbook"]))
            .replace("__STAMP__", time.strftime("%Y-%m-%d %H:%M:%S"))
            .replace("__NCHANGES__", str(len(data["changes"])))
            .replace("__VSTATUS__", "PASS" if report["ok"] else "FAIL")
            .replace("__VCLASS__", "ok" if report["ok"] else "bad"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(page, encoding="utf-8", newline="\n")
    return {"ok": report["ok"] and all(data["same"].values()), "same": data["same"],
            "validate_ok": report["ok"], "changes": len(data["changes"]), "path": str(target)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    start = time.perf_counter()
    try:
        result = build()
    except (OSError, ValueError, KeyError, ET.ParseError) as exc:
        print(f"FAIL preview: {exc}")
        return 1
    print(f"{'PASS' if result['ok'] else 'FAIL'} preview written: {result['path']}")
    print(f"  renderer parity {result['same']}; validate.py {'PASS' if result['validate_ok'] else 'FAIL'}; "
          f"{result['changes']} changed files vs prebuilt")
    print(f"Preview elapsed: {time.perf_counter() - start:.3f}s (local renderer, not Power BI)")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
