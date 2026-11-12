"""Small, reviewed translation profile. Unsupported formulas must stop migration."""

CALCULATIONS = {
    "Average Selling Price": {
        "tableau": "SUM([revenue]) / SUM([units])",
        "dax": "DIVIDE([Total Revenue], [Total Units])",
        "format": "$#,##0.00",
        "note": "Ratio of sums, not the average of row prices. DIVIDE returns BLANK for a zero denominator.",
    },
    "YoY Revenue Growth": {
        "tableau": "(SUM([revenue]) - LOOKUP(SUM([revenue]), -12)) / ABS(LOOKUP(SUM([revenue]), -12))",
        "dax": "DIVIDE([Total Revenue] - [Revenue Prior Year], ABS([Revenue Prior Year]))",
        "format": "0.00%",
        "note": "LOOKUP(-12) means 12 displayed marks back, not inherently a year. Equivalent here only "
                "with ascending, complete monthly marks, partitioned by product line, and both years visible. "
                "DAX uses a marked contiguous Calendar and a relationship to Sales. Missing prior year "
                "returns BLANK. Arbitrary Tableau addressing, hidden months, and partial-date contexts require review.",
    },
    "Revenue Band": {
        "tableau": "IF [revenue] >= 10000 THEN 'Large' ELSE 'Standard' END",
        "dax": "SELECTEDVALUE('Sales'[Revenue Band Value])",
        "column_name": "Revenue Band Value",
        "column_dax": 'IF(\'Sales\'[revenue] >= 10000, "Large", "Standard")',
        "format": "",
        "note": "Row-level dimension becomes a calculated column. The required same-caption measure "
                "returns a value only in a single-band context, otherwise BLANK; it is not a bucket of SUM(revenue).",
    },
    "Order Month": {
        "tableau": "DATETRUNC('month', [order_date])",
        "dax": "SELECTEDVALUE('Sales'[Order Month Value])",
        "column_name": "Order Month Value",
        "column_dax": "DATE(YEAR('Sales'[order_date]), MONTH('Sales'[order_date]), 1)",
        "format": "yyyy-MM",
        "note": "Row-level date truncation becomes a calculated column. The same-caption measure returns "
                "BLANK for multiple months. The line chart groups on Calendar[Month], not the scalar measure.",
    },
}

BASE_MEASURES = {
    "Total Revenue": ("SUM('Sales'[revenue])", "$#,##0.00"),
    "Total Units": ("SUM('Sales'[units])", "#,##0"),
    "Revenue Prior Year": (
        "CALCULATE([Total Revenue], DATEADD('Calendar'[Date], -1, YEAR))", "$#,##0.00"),
    "Selected Top N": ("SELECTEDVALUE('Top N'[Value], 10)", "0"),
    "Top N Revenue": (
        "VAR Winners = TOPN([Selected Top N], ALLSELECTED('Sales'[sku]), "
        "[Total Revenue], DESC, 'Sales'[sku], ASC) "
        "RETURN CALCULATE([Total Revenue], KEEPFILTERS(Winners))", "$#,##0.00"),
}


def mapping_text() -> str:
    lines = [
        "# Tableau to Power BI mapping", "",
        "Synthetic, reviewed profile for OrthoSales. This is report-definition translation, not data relocation.",
        "Power Query reads the same CSV as Tableau. No customer data or inventory quantities are present.", "",
        "| Tableau field | Tableau formula | Data Analysis Expressions (DAX) | Review notes |",
        "| --- | --- | --- | --- |",
    ]
    for name, rule in CALCULATIONS.items():
        dax = rule["dax"]
        if "column_dax" in rule:
            dax = f"Column {rule['column_name']}: {rule['column_dax']}; measure: {dax}"
        lines.append(f"| {name} | `{rule['tableau']}` | `{dax}` | {rule['note']} |")
    lines += [
        "", "## Supporting measures", "",
        "| Measure | DAX |", "| --- | --- |",
        *[f"| {name} | `{expr}` |" for name, (expr, _) in BASE_MEASURES.items()],
        "", "## Report behavior and review boundaries", "",
        "- One overview page mirrors the three worksheet roles: regional revenue bar, monthly units line "
        "with product-line legend, SKU/revenue table. It is not a pixel-perfect Tableau dashboard.",
        "- Region slicer filters all three visuals on that page. It starts at All.",
        "- Top N is a disconnected calculated numeric table (1 to 20). Its strict single-select dropdown "
        "opens at 10; the measure also defaults to 10 without a single-value filter. Top N Revenue returns "
        "BLANK outside the winning set so the table "
        "suppresses other SKUs. The grand total is the sum of the winning SKUs, not all sales.",
        "- Top N is evaluated after Region selection. The sample explicitly marks Region as a Tableau "
        "context filter, preserving this order of operations. SKU ascending breaks ties to return exactly N; Tableau tie "
        "ordering is not guaranteed. Verify this policy with the report owner.",
        "- YoY is modelled but is not a source worksheet in this sample. Its Python checks cover "
        "monthly and annual contexts; it must still be executed in the DAX engine.",
        "- Fixed-level-of-detail expressions are not present. A pattern like "
        "`{ FIXED [region] : SUM([revenue]) }` may use `CALCULATE` and `ALLEXCEPT`, but context filters "
        "and data-source filters must be reviewed. Unsupported expressions stop this recipe.",
        "- Python parity checks are independent arithmetic reference checks plus emitted-expression "
        "and structural checks. They do NOT execute Tableau, Power Query, DAX, or render visuals.",
        "- Source workbook is hand-authored Tableau XML. Application-level opening in Tableau is unverified.",
        "", "## Sources", "",
        'Microsoft. "Power BI Desktop Projects (PBIP)." Microsoft Learn. Accessed 12 Nov. 2026. '
        "https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-overview.",
        "", 'Microsoft. "Power BI Desktop Project Report Folder." Microsoft Learn. Accessed 12 Nov. 2026. '
        "https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-report.",
        "", 'Microsoft. "Power BI Desktop Project Semantic Model Folder." Microsoft Learn. Accessed 12 Nov. 2026. '
        "https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-dataset.",
        "", 'Microsoft. "Tabular Model Definition Language (TMDL) Overview." Microsoft Learn. Accessed 12 Nov. 2026. '
        "https://learn.microsoft.com/en-us/analysis-services/tmdl/tmdl-overview.",
        "", 'Microsoft. "DATEADD Function (DAX)." Microsoft Learn. Accessed 12 Nov. 2026. '
        "https://learn.microsoft.com/en-us/dax/dateadd-function-dax.",
        "", 'Microsoft. "TOPN Function (DAX)." Microsoft Learn. Accessed 12 Nov. 2026. '
        "https://learn.microsoft.com/en-us/dax/topn-function-dax.",
        "", 'Microsoft. "Design Guidance for Date Tables." Microsoft Learn. Accessed 12 Nov. 2026. '
        "https://learn.microsoft.com/en-us/power-bi/guidance/model-date-tables.", "",
    ]
    return "\n".join(lines)
