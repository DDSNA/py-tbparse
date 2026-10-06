"""Generate Markdown pages: a small generic renderer, and the template page built with it.

Not part of the R package. The renderer (`escape_cell`, `inline_code`, `heading`, `code_block`,
`md_table`, `render`) knows nothing about Tableau: it escapes what breaks a table (pipes,
newlines, `<`), keeps the order it is given and never adds a timestamp, so the same input gives the
same text and a page can live in git and be reviewed as a diff.

`template_markdown` is the page `py-tbparse template show --markdown` prints; `workbook_markdown` is the
workbook data dictionary (`py-tbparse docs`, WP11 basic). Both are built from the functions above and share
`_connection_text`, so a connection is shown (and its secrets left out) the same way on both pages.
"""

from __future__ import annotations

import os
import re
from typing import Iterable, Optional, Sequence

from .templates import Template, _connections, safe_connection
from .dashboards import dashboard_targets

_CELL_ESCAPES = {"\\": "\\\\", "|": "\\|", "*": "\\*", "_": "\\_", "<": "&lt;", ">": "&gt;",
                 "&": "&amp;", "`": "\\`", "[": "\\[", "]": "\\]", "~": "\\~"}
# A line that starts one of these would be a heading, list, rule, fence or numbered list: escape its first character.
_LINE_START = re.compile(r"^(\s*)(?:([#+=-])|(\d+)(?=[.)]))")
_MAX_TEXT = 300     # characters kept of a parameter description or an allowed value


class Code(str):
    """A table cell (or text) to show as inline code, such as a field name."""


def _plain(value) -> str:
    if value is None:
        return ""
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return str(value)


def escape_cell(value) -> str:
    """Text safe inside a table cell, and in a paragraph: backslash, pipe, `*`, `_`, `<`, `>`, `&`, backtick,
    `[`, `]` and `~` escaped (so no link, image, code span, fence or entity can open), a `#`, `-`, `+`, `=` or
    list number at the start of a line escaped, line breaks as `<br>`. Non-Latin text is left alone."""
    text = _plain(value).replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(_CELL_ESCAPES.get(c, c) for c in text)
    text = "\n".join(_LINE_START.sub(lambda m: m.group(1) + ("\\" + m.group(2) if m.group(2) else m.group(3) + "\\"), line)
                     for line in text.split("\n"))
    return text.replace("\n", "<br>")


def clip(value, limit: int = _MAX_TEXT) -> str:
    """`value` as text, cut to `limit` characters with a note that says so (for text a workbook author wrote)."""
    text = _plain(value)
    return text if len(text) <= limit else f"{text[:limit]}... (truncated, {len(text)} characters)"


def inline_code(value) -> str:
    """A code span: its delimiter is longer than any backtick run inside, a pipe is escaped (it would
    split a table cell even in code) and a line break becomes a space."""
    text = _plain(value).replace("\r", " ").replace("\n", " ").replace("|", "\\|")
    longest = run = 0
    for c in text:
        run = run + 1 if c == "`" else 0
        longest = max(longest, run)
    fence = "`" * (longest + 1)
    pad = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{fence}{pad}{text}{pad}{fence}"


def heading(level: int, text: str) -> str:
    if not 1 <= level <= 6:
        raise ValueError(f"heading level must be 1 to 6, got {level}")
    return f"{'#' * level} {_plain(text).replace(chr(10), ' ')}"


def code_block(text: str, lang: str = "") -> str:
    """A fenced block, its fence longer than any run of backticks inside."""
    longest = run = 0
    for c in text:
        run = run + 1 if c == "`" else 0
        longest = max(longest, run)
    fence = "`" * max(3, longest + 1)
    return f"{fence}{lang}\n{text}\n{fence}"


def _cell(value) -> str:
    if isinstance(value, Code):
        return inline_code(value) if value else ""
    return escape_cell(value)


def md_table(headers: Sequence[str], rows: Iterable[Sequence]) -> str:
    """A GitHub table. Every cell is escaped (wrap a value in `Code` to show it as code); rows keep the
    order given."""
    lines = ["| " + " | ".join(escape_cell(h) for h in headers) + " |",
             "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        row = list(row)
        if len(row) != len(headers):
            raise ValueError(f"row has {len(row)} cells, the table has {len(headers)} columns")
        lines.append("| " + " | ".join(_cell(c) for c in row) + " |")
    return "\n".join(lines)


def render(*blocks: Optional[str]) -> str:
    """Join blocks with a blank line; empty and None blocks are dropped; one final newline."""
    return "\n\n".join(b for b in blocks if b) + "\n"


# ------------------------------------------------------------ template page --

_MAX_LIST = 20


def _short_list(values: Sequence[str]) -> str:
    shown = "; ".join(clip(v) for v in values[:_MAX_LIST])
    return shown + (f"; ... and {len(values) - _MAX_LIST} more" if len(values) > _MAX_LIST else "")


def _connection_text(conn: dict) -> str:
    """A connection as `class=...; server=...`, through the `safe_connection` allowlist: where the data lives,
    never who is logged in, and a file by its name only."""
    return "; ".join(f"{k}={v}" for k, v in safe_connection(conn).items())


def _label(name: str) -> str:
    return name.strip("[]")


def _field_rows(fields: list[dict]) -> list[list]:
    return [[Code(_label(f["name"])), f.get("caption") or "", f.get("datatype"), f.get("role"),
             "; ".join(f.get("used_by") or [])] for f in sorted(fields, key=lambda f: f["name"])]


def template_markdown(template: Template) -> str:
    """A documentation page for a template: what it is, the fields it needs and which sheets use them,
    its parameters and tokens, where its data came from (never a user name or password), and its
    worksheets and dashboards. Reviewable text, in a stable order."""
    m = template.manifest
    blocks = [heading(1, escape_cell(template.name))]
    if m.get("description"):
        blocks.append(escape_cell(m["description"]).replace("<br>", "  \n"))
    props = [["Template id", Code(template.id) if template.id else "(none: a version 1 template)"],
             ["Revision", template.revision],
             ["Made from", m.get("source")],
             ["Created", m.get("created")],
             ["Created with", m.get("created_with")]]
    blocks.append(md_table(["Property", "Value"], [p for p in props if p[1] not in (None, "")]))

    blocks.append(heading(2, "Fields"))
    blocks.append("Required fields are used by a sheet, directly or through a calculation, group or set; "
                  "the new data needs a column for each.")
    heads = ["Field", "Caption", "Type", "Role", "Used by"]
    for ds in m.get("datasources", []):
        label = ds.get("caption") or ds["name"]
        required = [f for f in ds["fields"] if f["required"]]
        optional = [f for f in ds["fields"] if not f["required"]]
        blocks.append(heading(3, "Datasource: " + escape_cell(label)))
        blocks.append(heading(4, f"Required fields ({len(required)})"))
        blocks.append(md_table(heads, _field_rows(required)) if required else "None.")
        blocks.append(heading(4, f"Optional fields ({len(optional)})"))
        blocks.append(md_table(heads, _field_rows(optional)) if optional else "None.")

    blocks.append(heading(2, "Parameters"))
    params = m.get("parameters", [])
    if params:
        rows = []
        for p in sorted(params, key=lambda p: p["name"]):
            allowed = _short_list(p["allowed"]) if p.get("allowed") else (
                "; ".join(f"{k} {v}" for k, v in p["range"].items()) if p.get("range") else "")
            rows.append([p.get("caption") or _label(p["name"]), p.get("datatype"), Code(p.get("value") or ""),
                         allowed, clip(p.get("description") or "")])
        blocks.append(md_table(["Parameter", "Type", "Default", "Allowed values", "Description"], rows))
    else:
        blocks.append("None.")

    if m.get("tokens"):
        blocks.append(heading(2, "Tokens"))
        blocks.append(md_table(
            ["Token", "Default", "Used in"],
            [[Code("{{%s}}" % t["name"]), t["default"] if t.get("default") is not None else "(required)",
              "; ".join(sorted({f"{w.get('kind')}: {w.get('object')}" if w.get("object") else str(w.get("kind"))
                                for w in t.get("where") or []}))]
             for t in sorted(m["tokens"], key=lambda t: t["name"])]))

    blocks.append(heading(2, "Connections"))
    blocks.append("Where the data came from when the template was made. No user names or passwords are kept, "
                  "and a file is shown by its name only.")
    rows = []
    for ds in m.get("datasources", []):
        for c in ds.get("connections") or [{}]:
            shown = _connection_text(c)
            rows.append([ds.get("caption") or ds["name"], Code(shown) if shown else "(none)"])
    blocks.append(md_table(["Datasource", "Connection"], rows))

    uses: dict[str, list[str]] = {}
    for ds in m.get("datasources", []):
        for f in ds["fields"]:
            for sheet in f.get("used_by") or []:
                uses.setdefault(sheet, []).append(f.get("caption") or _label(f["name"]))
    blocks.append(heading(2, "Worksheets"))
    sheets = sorted(m.get("worksheets", []))
    blocks.append(md_table(["Worksheet", "Template fields it uses"],
                           [[s, "; ".join(sorted(set(uses.get(s, []))))] for s in sheets]) if sheets else "None.")

    blocks.append(heading(2, "Dashboards"))
    shown_by = {}
    for db in template.parser.xml_doc.xpath("/workbook/dashboards/dashboard[@name]"):
        shown_by.setdefault(db.get("name"), set()).update(dashboard_targets(db))
    names = sorted(m.get("dashboards", []))
    rows = [[d, "; ".join(sorted(shown_by.get(d, ())))] for d in names]
    blocks.append(md_table(["Dashboard", "Worksheets"], rows) if rows else "None.")
    return render(*blocks)


# --------------------------------------------------------- workbook dictionary --

_FORMULA_CELL = 120      # characters of a formula shown in the fields table; the rest is in a collapsible block


def _html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _used_by(row) -> str:
    parts = []
    for label, key in (("Sheets", "sheets"), ("Dashboards", "dashboards"), ("Calculations", "calculations")):
        if row[key]:
            parts.append(f"{label}: {_short_list(list(row[key]))}")
    return " / ".join(parts) if parts else "(nothing)"


def _formula_cell(formula: str) -> Code:
    flat = formula.strip()
    if len(flat) <= _FORMULA_CELL:
        return Code(flat)
    return Code(f"{flat[:_FORMULA_CELL]}... (truncated, {len(flat)} characters; in full below)")


def _details(summary: str, body: str) -> str:
    return f"<details>\n<summary>{_html(summary)}</summary>\n\n{body}\n\n</details>"


def _tables_of(ds) -> list[list[str]]:
    seen, rows = set(), []
    for rel in ds.xpath("./connection//relation[@name][@type='table' or @type='text']"):
        kind = "custom SQL" if rel.get("type") == "text" else "table"
        key = (rel.get("name"), kind, rel.get("table"))
        if key not in seen:
            seen.add(key)
            rows.append([Code(rel.get("name")), kind, Code(rel.get("table")) if kind == "table" and rel.get("table") else ""])
    return sorted(rows, key=lambda r: (str(r[0]), r[1]))


def workbook_markdown(parser, graph: bool = False) -> str:
    """The data dictionary of a workbook (a `TwbParser`) as Markdown: an overview, each datasource with its
    connections (never a user name or password, a file by its name only) and tables, a table of its fields with
    caption, type, role, formula and what uses them, the parameters, the worksheets with the fields they use and
    the dashboards that show them, and the dashboards. A formula longer than 120 characters is cut in the
    table and given in full in a collapsible block below it. `graph=True` adds the relationship graph as a
    fenced DOT block. The order is fixed and there is no timestamp, so the same workbook gives the same text.

    Formulas, captions and parameter values are printed as the workbook has them (escaped for Markdown), so
    review the page before you share it. Nothing was opened in Tableau."""
    from .usage import _sheet_uses, field_usage

    doc = parser.xml_doc
    root = doc.getroot()
    usage = field_usage(doc)
    usage = usage.astype(object).where(usage.notna(), None)    # a missing caption is None, not NaN
    file_name = os.path.basename(parser.twbx_path or parser.path)
    if parser.twbx_path:
        file_name = os.path.basename(parser.twbx_path)
    sources = sorted((ds for ds in doc.xpath("/workbook/datasources/datasource[@name]") if ds.get("name") != "Parameters"),
                     key=lambda ds: ((ds.get("caption") or ds.get("name")).casefold(), ds.get("name")))
    dashboards = sorted(doc.xpath("/workbook/dashboards/dashboard[@name]"), key=lambda d: d.get("name"))
    sheets = sorted(doc.xpath("/workbook/worksheets/worksheet/@name"))
    non_param = usage[usage["kind"] != "parameter"]
    params = usage[usage["kind"] == "parameter"]

    blocks = [heading(1, "Data dictionary: " + escape_cell(os.path.splitext(file_name)[0]))]
    props = [["File", Code(file_name)],
             ["Tableau file version", Code(root.get("version") or "")],
             ["Saved by", Code(root.get("source-build") or "")],
             ["Datasources", len(sources)],
             ["Fields", len(non_param)],
             ["Calculated fields", int((non_param["kind"] == "calculated").sum())],
             ["Parameters", len(params)],
             ["Worksheets", len(sheets)],
             ["Dashboards", len(dashboards)]]
    blocks.append(md_table(["Property", "Value"], [p for p in props if p[1] not in (None, "")]))
    blocks.append("This page was read from the workbook file by py-tbparse. Nothing was opened in Tableau, and "
                  "\"used by\" follows worksheets, dashboards and calculations only (see `docs/audit.md`).")

    labels: dict[tuple, str] = {}
    blocks.append(heading(2, "Datasources"))
    if not sources:
        blocks.append("None.")
    for ds in sources:
        name = ds.get("name")
        label = ds.get("caption") or name
        cols = {c.get("name"): c for c in ds.xpath("./column[@name]")}
        blocks.append(heading(3, "Datasource: " + escape_cell(label)))
        conns = _connections(ds)
        if conns:
            blocks.append(md_table(["Connection"], [[Code(_connection_text(c))] for c in conns]))
        tables = _tables_of(ds)
        if tables:
            blocks.append(md_table(["Table", "Kind", "Source name"], tables))
        rows, long_formulas = [], []
        mine = usage[usage["datasource"] == name]
        mine = mine.assign(_k=mine.apply(lambda r: ((r["caption"] or str(r["field"]).strip("[]")).casefold(), r["field"]), axis=1))
        for _, r in mine.sort_values("_k", kind="stable").iterrows():
            col = cols.get(r["field"])
            labels[(name, r["field"])] = r["caption"] or str(r["field"]).strip("[]")
            calc = col.find("calculation") if col is not None else None
            formula = (calc.get("formula") or "") if calc is not None else ""
            kind = r["kind"] + (" (hidden)" if col is not None and col.get("hidden") == "true" else "")
            rows.append([Code(str(r["field"]).strip("[]")), r["caption"] or "", r["datatype"] or "",
                         (col.get("role") if col is not None else None) or "", kind,
                         _formula_cell(formula) if formula.strip() else "", _used_by(r)])
            if len(formula.strip()) > _FORMULA_CELL:
                long_formulas.append((labels[(name, r["field"])], formula.strip()))
        blocks.append(heading(4, f"Fields ({len(rows)})"))
        blocks.append(md_table(["Field", "Caption", "Type", "Role", "Kind", "Formula", "Used by"], rows) if rows else "None.")
        for fname, formula in long_formulas:
            blocks.append(_details(f"Formula of {fname} ({len(formula)} characters)", code_block(formula)))

    blocks.append(heading(2, "Parameters"))
    if params.empty:
        blocks.append("None.")
    else:
        pcols = {c.get("name"): c for c in doc.xpath("/workbook/datasources/datasource[@name='Parameters']/column[@name]")}
        rows = []
        for _, r in params.sort_values("field", kind="stable").iterrows():
            labels[("Parameters", r["field"])] = r["caption"] or str(r["field"]).strip("[]")
            col = pcols.get(r["field"])
            allowed = ""
            if col is not None:
                members = [m.get("value") or "" for m in col.xpath("./members/member")]
                rng = col.find("range")
                if members:
                    allowed = _short_list(members)
                elif rng is not None:
                    allowed = "; ".join(f"{k} {rng.get(k)}" for k in ("min", "max", "granularity") if rng.get(k) is not None)
            rows.append([r["caption"] or str(r["field"]).strip("[]"), r["datatype"] or "",
                         Code(clip((col.get("value") if col is not None else "") or "")),
                         (col.get("param-domain-type") if col is not None else "") or "", allowed, _used_by(r)])
        rows.sort(key=lambda x: str(x[0]).casefold())
        blocks.append(md_table(["Parameter", "Type", "Current value", "Domain", "Allowed values", "Used by"], rows))

    shown_on: dict[str, set] = {}
    on_dashboard: dict[str, list] = {}
    for db in dashboards:
        targets = sorted(set(dashboard_targets(db)))
        on_dashboard[db.get("name")] = targets
        for t in targets:
            shown_on.setdefault(t, set()).add(db.get("name"))
    hidden = set(doc.xpath("/workbook/windows/window[@class='worksheet'][@hidden='true']/@name"))
    direct = _sheet_uses(doc)

    blocks.append(heading(2, "Worksheets (where fields are used)"))
    rows = []
    for sheet in sheets:
        used = sorted({labels.get((ds, n), str(n).strip("[]")) for ds, names in direct.get(sheet, {}).items() for n in names if n})
        rows.append([sheet, "yes" if sheet in hidden else "", "; ".join(sorted(shown_on.get(sheet, ()))), _short_list(used)])
    blocks.append(md_table(["Worksheet", "Hidden", "On dashboards", "Fields it uses directly"], rows) if rows else "None.")

    blocks.append(heading(2, "Dashboards"))
    rows = [[d, "; ".join(on_dashboard[d])] for d in sorted(on_dashboard)]
    blocks.append(md_table(["Dashboard", "Worksheets"], rows) if rows else "None.")

    if graph:
        blocks.append(heading(2, "Relationship graph"))
        blocks.append(code_block(parser.get_relationship_graph_dot(), "dot"))
    return render(*blocks)
