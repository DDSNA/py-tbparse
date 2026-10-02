"""A plain-language report card for a workbook: what is in it and what deserves a look.

Python-native (the R package has no equivalent). It only combines checks that already exist:
`validate_relationships`, `field_usage` and `missing_references`, plus counts of the things that are
information rather than problems. The GUI's overview shows it; each item carries the table (and column
filters) that lists exactly the rows it counted, so a count on the card is never a different number from
the rows it opens.
"""

from __future__ import annotations

import os

from .parser import TwbParser
from .usage import missing_references

PROBLEM, WARNING, INFO = "problem", "warning", "info"


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def _item(severity: str, key: str, title: str, detail: str, count: int, table: str, filters=None) -> dict:
    return {"id": key, "severity": severity, "title": title, "detail": detail, "count": count,
            "table": table, "filters": filters or []}


def _sheets_by_dashboard(parser: TwbParser) -> list[dict]:
    doc = parser.xml_doc
    out = []
    for db in doc.xpath("/workbook/dashboards/dashboard[@name]"):
        seen: list[str] = []
        for z in db.xpath(".//zone[@worksheet]"):
            if z.get("worksheet") not in seen:
                seen.append(z.get("worksheet"))
        out.append({"name": db.get("name"), "sheets": seen})
    return sorted(out, key=lambda d: d["name"].lower())


def workbook_report(parser: TwbParser) -> dict:
    """`{summary, counts, worksheets, dashboards, health}` for a loaded workbook.

    `health` is a list of items (`severity`, `title`, `detail`, `count`, `table`, `filters`), problems
    first. An empty list means nothing was found."""
    doc = parser.xml_doc
    overview = parser.get_overview().iloc[0].to_dict()
    overview.pop("file", None)
    # a .twbx is named by the package the person opened, not by the .twb inside it
    name = os.path.basename(getattr(parser, "twbx_path", None) or parser.path or "") or "This workbook"
    sheets = sorted({w.get("name") for w in doc.xpath("/workbook/worksheets/worksheet[@name]")}, key=str.lower)
    dashboards = _sheets_by_dashboard(parser)
    on_dashboard = {s for d in dashboards for s in d["sheets"]}

    parts = [_plural(len(dashboards), "dashboard"), _plural(len(sheets), "worksheet"),
             _plural(int(overview["datasources"]), "datasource")]
    summary = f"{name} has {parts[0]}, {parts[1]} and {parts[2]}."

    health: list[dict] = []

    from .validators import validate_relationships
    issues = validate_relationships(parser)["issues"]
    if "unknown_tables" in issues:
        n = len(issues["unknown_tables"])
        health.append(_item(PROBLEM, "unknown-tables", _plural(n, "relationship") + " point at a table the workbook does not have",
                            "Check the left and right table names against the datasources.", n, "relationships"))
    if "unknown_fields" in issues:
        n = len(issues["unknown_fields"])
        health.append(_item(PROBLEM, "unknown-fields", _plural(n, "relationship") + " use a field that is not in the workbook",
                            "The join keys may have been renamed or removed.", n, "relationships"))

    missing = missing_references(parser)
    if len(missing):
        n = len(missing)
        health.append(_item(WARNING, "missing-references", _plural(n, "reference") + " in calculations to fields that do not exist",
                            "A calculation names a field the workbook does not have, so it will show an error in Tableau.",
                            n, "missing-references"))

    usage = parser.get_field_usage()
    unused = usage[~usage["used"].astype(bool)] if len(usage) else usage
    calcs = unused[unused["kind"] == "calculated"] if len(unused) else unused
    raw = unused[unused["kind"] == "physical"] if len(unused) else unused
    if len(calcs):
        n = len(calcs)
        health.append(_item(WARNING, "unused-calculations", _plural(n, "calculation") + " no worksheet uses",
                            "Candidates to delete, unless another workbook or a published source needs them.",
                            n, "field-usage", [{"col": "kind", "text": "calculated"}, {"col": "used", "text": "false"}]))
    if len(raw):
        n = len(raw)
        health.append(_item(INFO, "unused-fields", _plural(n, "field") + " no worksheet uses",
                            "Ordinary for a wide data source; useful when you are slimming one down.",
                            n, "field-usage", [{"col": "kind", "text": "physical"}, {"col": "used", "text": "false"}]))

    loose = [s for s in sheets if s not in on_dashboard]
    if loose and dashboards:
        health.append(_item(INFO, "sheets-off-dashboards", _plural(len(loose), "worksheet") + " not on any dashboard",
                            ", ".join(loose[:6]) + (" and more" if len(loose) > 6 else ""), len(loose), ""))   # no table lists these: sheets with no zone

    inferred = int(overview["inferred_relationships"])
    if inferred:
        health.append(_item(INFO, "inferred", _plural(inferred, "relationship") + " could be inferred from matching field names",
                            "They are not modelled in the workbook; this is only a hint.", inferred, "inferred-relationships"))
    for key, getter, table, title in (
        ("custom-sql", parser.get_custom_sql, "custom-sql", "custom SQL"),
        ("initial-sql", parser.get_initial_sql, "initial-sql", "initial SQL"),
    ):
        n = len(getter())
        if n:
            health.append(_item(INFO, key, f"{n} {title} {'entry' if n == 1 else 'entries'}", "", n, table))

    # A datasource with no connection of its own is a published one, or the Parameters source that every
    # workbook with parameters has. Only mention it when something other than Parameters is in the list; the
    # count is still every row the link opens, Parameters included, and the detail says so.
    pub = parser.get_published_refs()
    likely = pub[pub["likely_published"].astype(bool)] if len(pub) else pub
    if len(likely) and (likely["name"] != "Parameters").any():
        n = len(likely)
        health.append(_item(INFO, "published", _plural(n, "datasource") + " without a connection of its own",
                            "Published data sources look like this. So does the Parameters source, which is counted too.",
                            n, "published-refs", [{"col": "likely_published", "text": "true"}]))

    order = {PROBLEM: 0, WARNING: 1, INFO: 2}
    health.sort(key=lambda h: order[h["severity"]])
    return {"summary": summary, "counts": overview, "worksheets": sheets, "dashboards": dashboards, "health": health}
