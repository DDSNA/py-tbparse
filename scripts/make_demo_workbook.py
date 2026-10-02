#!/usr/bin/env python3
"""Write the small demo workbook the README screenshots are taken from.

    python scripts/make_demo_workbook.py            # writes docs/demo/coffee-shop.twb

It is made up (a coffee shop, invented, untidy column names, no data), so the screenshots show nothing that belongs to
anyone else, and it is built to show the GUI's features: six related tables, two dashboards, a worksheet that
is on neither, a calculation that names a field the workbook does not have, and one nothing uses. It has not
been opened in Tableau; py-tbparse only reads it.
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import quoteattr

OUT = Path(__file__).resolve().parent.parent / "docs" / "demo" / "coffee-shop.twb"

TABLES = {
    "Orders": ["order_id", "customer_id", "product_id", "order_date", "sales_usd", "profit_usd", "discount_pct", "qty"],
    "Customers": ["customer_id", "customer_name", "segment", "loyalty_tier", "city"],
    "Products": ["product_id", "product_name", "category", "supplier_id", "list_price"],
    "Suppliers": ["supplier_id", "supplier_name", "country"],
    "Returns": ["order_id", "returned_flag", "return_reason"],
    "Stores": ["city", "store_manager", "opened_on"],
}
MEASURES = {"sales_usd", "profit_usd", "discount_pct", "qty", "list_price"}

RELATIONSHIPS = [
    ("Orders", "customer_id", "Customers"),
    ("Orders", "product_id", "Products"),
    ("Orders", "order_id", "Returns"),
    ("Products", "supplier_id", "Suppliers"),
    ("Customers", "city", "Stores"),
]

CALCS = [
    # (name, caption, formula)
    ("Profit Ratio", "Profit Ratio", "SUM([profit_usd]) / SUM([sales_usd])"),
    ("Margin Band", "Margin Band", "IF [Profit Ratio] >= [Parameters].[Target Margin] THEN 'On target' ELSE 'Below' END"),
    ("Loyalty Score", "Loyalty Score", "[sales_usd] * [Loyalty Weight]"),
    ("Old Discount", "Old Discount", "[discount_pct] * 100"),
    ("Net Sales", "Net Sales", "[sales_usd] - [sales_usd] * [discount_pct]"),
]

SHEETS = {
    "Sales by Region": ["sales_usd", "city", "Net Sales"],
    "Profit Trend": ["profit_usd", "order_date", "Profit Ratio"],
    "Top Products": ["sales_usd", "product_name", "Margin Band"],
    "Returns Detail": ["order_id", "returned_flag", "return_reason"],
}
DASHBOARDS = {
    "Weekly Overview": ["Sales by Region", "Profit Trend"],
    "Product Review": ["Top Products", "Sales by Region"],
}


def build() -> str:
    cols = []
    seen = set()
    for table, fields in TABLES.items():
        for f in fields:
            if f in seen:
                continue
            seen.add(f)
            role = "measure" if f in MEASURES else "dimension"
            dtype = "real" if f in MEASURES else ("date" if f in ("order_date", "opened_on") else "string")
            cols.append(f"      <column name={quoteattr('[' + f + ']')} datatype='{dtype}' role='{role}' />")
    for name, caption, formula in CALCS:
        cols.append(
            f"      <column name={quoteattr('[' + name + ']')} caption={quoteattr(caption)} datatype='real' role='measure'>\n"
            f"        <calculation class='tableau' formula={quoteattr(formula)} />\n      </column>"
        )
    objects = "\n".join(
        f"        <object id={quoteattr(t)} caption={quoteattr(t)}><properties context=''>"
        f"<relation name={quoteattr(t)} table={quoteattr('[' + t + ']')} type='table' /></properties></object>"
        for t in TABLES
    )
    rels = "\n".join(
        f"        <relationship><expression op='='><expression op={quoteattr('[' + a + '].[' + f + ']')} />"
        f"<expression op={quoteattr('[' + b + '].[' + f + ']')} /></expression>"
        f"<first-end-point object-id={quoteattr(a)} /><second-end-point object-id={quoteattr(b)} /></relationship>"
        for a, f, b in RELATIONSHIPS
    )
    sheets = []
    for name, fields in SHEETS.items():
        deps = "\n".join(f"          <column name={quoteattr('[' + f + ']')} datatype='string' role='dimension' />" for f in fields)
        sheets.append(
            f"    <worksheet name={quoteattr(name)}>\n      <table><view>\n"
            f"        <datasource-dependencies datasource='coffee'>\n{deps}\n        </datasource-dependencies>\n"
            f"      </view></table>\n    </worksheet>"
        )
    boards = []
    for name, zone_sheets in DASHBOARDS.items():
        zones = "\n".join(
            f"        <zone worksheet={quoteattr(s)} id='{i + 1}' x='{i * 50000}' y='0' w='50000' h='100000' />"
            for i, s in enumerate(zone_sheets)
        )
        boards.append(f"    <dashboard name={quoteattr(name)}>\n      <zones>\n{zones}\n      </zones>\n    </dashboard>")
    return f"""<?xml version='1.0' encoding='utf-8' ?>
<workbook version='18.1' source-platform='win'>
  <datasources>
    <datasource name='Parameters' hasconnection='false'>
      <column name='[Target Margin]' caption='Target Margin' datatype='real' param-domain-type='range' role='measure'>
        <calculation class='tableau' formula='0.15' />
      </column>
    </datasource>
    <datasource name='coffee' caption='Coffee Shop'>
{chr(10).join(cols)}
    </datasource>
  </datasources>
  <object-graph>
    <objects>
{objects}
    </objects>
    <relationships>
{rels}
    </relationships>
  </object-graph>
  <worksheets>
{chr(10).join(sheets)}
  </worksheets>
  <dashboards>
{chr(10).join(boards)}
  </dashboards>
</workbook>
"""


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build(), encoding="utf-8")
    print("wrote", OUT)
