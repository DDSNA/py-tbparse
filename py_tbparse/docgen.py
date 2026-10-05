"""Generate Markdown pages: a small generic renderer, and the template page built with it.

Not part of the R package. The renderer (`escape_cell`, `inline_code`, `heading`, `code_block`,
`md_table`, `render`) knows nothing about Tableau: it escapes what breaks a table (pipes,
newlines, `<`), keeps the order it is given and never adds a timestamp, so the same input gives the
same text and a page can live in git and be reviewed as a diff. The workbook data dictionary
(WP11) is meant to be written with the same functions.

`template_markdown` is the page `py-tbparse template show --markdown` prints.
"""

from __future__ import annotations

from typing import Iterable, Optional, Sequence

from .templates import _SECRET_ATTRS, Template

_CELL_ESCAPES = {"\\": "\\\\", "|": "\\|", "*": "\\*", "_": "\\_", "<": "&lt;", ">": "&gt;"}


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
    """Text safe inside a table cell: backslash, pipe, `*`, `_`, `<` and `>` escaped, line breaks
    as `<br>`. Non-Latin text is left alone."""
    text = _plain(value).replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(_CELL_ESCAPES.get(c, c) for c in text)
    return text.replace("\n", "<br>")


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
    shown = "; ".join(values[:_MAX_LIST])
    return shown + (f"; ... and {len(values) - _MAX_LIST} more" if len(values) > _MAX_LIST else "")


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
                         allowed, p.get("description") or ""])
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
    blocks.append("Where the data came from when the template was made. No user names or passwords are kept.")
    rows = []
    for ds in m.get("datasources", []):
        for c in ds.get("connections") or [{}]:
            shown = "; ".join(f"{k}={v}" for k, v in c.items() if k not in _SECRET_ATTRS and k != "password")
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
    dash = template.parser.get_dashboard_sheets()
    names = sorted(m.get("dashboards", []))
    rows = []
    for d in names:
        shown = sorted(set(dash.loc[dash["dashboard"] == d, "sheet"].dropna())) if len(dash) else []
        rows.append([d, "; ".join(shown)])
    blocks.append(md_table(["Dashboard", "Worksheets"], rows) if rows else "None.")
    return render(*blocks)
