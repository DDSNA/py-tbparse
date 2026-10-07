"""JSON-ready helpers the GUI's Templates view is built on (no HTTP, no state).

Every function takes loaded objects (`Template`, `DataSource`) and returns plain dicts and lists that
`json.dumps` accepts. A mistake of the person using the page (a column mapped twice, a bad parameter value, a
missing token) comes back as a message in `problems`, never as an exception; only a programming error raises.
`templates.py` is used, not changed.
"""

from __future__ import annotations

import dataclasses
import math
import re
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Optional

import pandas as pd
from lxml import etree

from . import templates as _t
from ._xml import parse_file
from .template_check import check_template
from .templates import DataSource, Template, TemplateError

_CAP = 2000   # rows of any table sent to the page


def _plain(value):
    """A value `json.dumps` accepts: NaN and NA become None, numpy numbers become Python ones."""
    if value is None or value is pd.NA:
        return None
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        value = value.item()
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _rows(df: pd.DataFrame) -> list[dict]:
    return [{str(k): _plain(v) for k, v in row.items()} for row in df.to_dict("records")]


def _records(df: pd.DataFrame, cap: int = _CAP) -> dict:
    """`{rows, total, truncated}`: at most `cap` rows of `df`, and how many were left out."""
    return {"rows": _rows(df.head(cap)), "total": int(len(df)), "truncated": max(0, int(len(df)) - cap)}


def _problem(exc: Exception) -> str:
    return str(exc.args[0]) if exc.args else exc.__class__.__name__


# ------------------------------------------------------------- summaries --

def template_summary(t: Template, *, label: str) -> dict:
    """What the page shows once a template is chosen. `label` is the file name only: no server path ever
    goes into the result."""
    datasources = []
    for e in t.manifest.get("datasources", []):
        datasources.append({"name": e["name"], "caption": e.get("caption"), "fields": len(e["fields"]),
                            "required": sum(1 for f in e["fields"] if f["required"])})
    parameters = []
    for p in t.manifest.get("parameters", []):
        allowed = list(p.get("allowed") or [])
        parameters.append({"caption": p["caption"], "datatype": p["datatype"], "value": p["value"],
                           "allowed": "; ".join(allowed), "allowed_values": allowed})
    try:
        findings = _rows(check_template(t))
    except Exception as e:   # a rule that crashes must not turn the page into a 500
        findings = [{"check": "template-check", "severity": "error", "detail": f"the template check failed: {_problem(e)}"}]
    return {"name": t.name, "description": t.manifest.get("description"), "id": t.id, "revision": t.revision,
            "manifest_version": t.manifest.get("version"), "label": label, "datasources": datasources,
            "parameters": parameters, "tokens": _rows(t.tokens()), "findings": findings}


def data_summary(d: DataSource, *, label: str) -> dict:
    return {"kind": d.kind, "label": label, "sheet": d.sheet,
            "columns": [{"name": f["name"], "datatype": f["datatype"]} for f in d.fields]}


def excel_sheets(path: str) -> list[str]:
    """The visible sheets of an `.xlsx`/`.xlsm`, so the page can offer a picker."""
    try:
        import openpyxl
    except ImportError:
        raise TemplateError("reading Excel files needs openpyxl: pip install 'py-tbparse[excel]'") from None
    try:
        book = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    except (zipfile.BadZipFile, KeyError, openpyxl.utils.exceptions.InvalidFileException) as e:
        raise TemplateError(f"{Path(path).name} is not a readable Excel file: {e}") from None
    try:
        return [ws.title for ws in book.worksheets if ws.sheet_state == "visible"]
    finally:
        book.close()


def tableau_datasources(path: str) -> list[str]:
    """The datasources (caption, else name) of a `.twb`, `.twbx` or `.tds` that have a connection, so the page
    can offer a picker instead of parsing `read_data`'s error message."""
    p = Path(path)
    if p.suffix.lower() == ".tds":
        root = parse_file(p).getroot()
        candidates = [root] if root.tag == "datasource" else root.xpath("//datasource[@name]")
    elif p.suffix.lower() in (".twb", ".twbx"):
        from .parser import TwbParser
        candidates = _t._non_parameter_datasources(TwbParser(str(p)).xml_doc)
    else:
        raise TemplateError(f"{p.name} is not a Tableau workbook or data source")
    return [d.get("caption") or d.get("name") for d in candidates if d.find("connection") is not None]


# --------------------------------------------------------------- mapping --

_STATUS_WORDS = {None: "ok", "numeric type differs": "numeric-differs", "date type differs": "date-differs",
                 "type mismatch": "mismatch"}


def column_choices(entry: dict, data: DataSource) -> dict:
    """For each field type the template needs, every column of the data and how well it fits:
    `ok | numeric-differs | date-differs | mismatch`. `{datatype: [{column, datatype, status}]}`; at most
    six types times the columns, so the page can fill each dropdown from it."""
    out = {}
    for datatype in sorted({f["datatype"] for f in entry["fields"]}):
        out[datatype] = [{"column": f["name"], "datatype": f["datatype"],
                          "status": _STATUS_WORDS[_t._type_status(datatype, f["datatype"])]}
                         for f in data.fields]
    return out


def mapping_frame(rows: dict, base: pd.DataFrame, data: Optional[DataSource] = None) -> pd.DataFrame:
    """The full mapping frame for `{field: column}` as the page sends it: `base` (the suggestion) with each
    named field set to its column (`""` or None clears it). Goes through `load_mapping`, which refuses a column
    mapped twice. A field `base` does not have, or a column the data does not have, is a `ValueError`."""
    df = base.copy()
    known = set(df["field"])
    for field in rows:
        if field not in known:
            raise ValueError(f"the template has no field {field!r}")
    columns = set(data.names()) if data is not None else None
    for field, column in rows.items():
        column = "" if column is None else str(column).strip()
        if column and columns is not None and column not in columns and data.column(column) not in columns:
            raise ValueError(f"the data has no column {column!r}")
        at = df["field"] == field
        df.loc[at, "mapped_to"] = column
        if data is not None:
            picked = data.column(column) if column else None
            df.loc[at, "data_type"] = data.datatype(picked) if picked else ""
            df.loc[at, "status"] = "chosen" if picked else "unmapped"
            df.loc[at, "score"] = None
    return _t.load_mapping(df)


# ------------------------------------------------------------------ plan --

def _param_errors(t: Template, params: dict) -> list[tuple]:
    """`(caption or None, message)` for each given value that cannot be used."""
    known = {}
    for p in t.manifest.get("parameters", []):
        known[p["caption"]] = p
        known[p["name"].strip("[]")] = p
    out = []
    for key, raw in (params or {}).items():
        p = known.get(key) or known.get(str(key).strip("[]"))
        if p is None:
            out.append((None, f"the template has no parameter {key!r}"))
            continue
        try:
            literal = _t._param_literal(p["datatype"], raw)
        except TemplateError as e:
            out.append((p["caption"], f"{_problem(e)}"))
            continue
        allowed = p.get("allowed") or []
        # an allowed value that holds a {{token}} is only known once the tokens are filled (issue #24): not checked here
        if allowed and not any("{{" in a for a in allowed) and literal not in allowed:
            out.append((p["caption"], f"{raw!r} is not one of its allowed values"))
    return out


def _token_state(t: Template, given: dict) -> tuple[list[dict], list[str]]:
    declared = t.manifest.get("tokens")
    given = {k: v for k, v in (given or {}).items()}
    if declared is None:
        return [], ([f"tokens given ({', '.join(sorted(given))}), but the template declares none"] if given else [])
    by_name = {d["name"]: d for d in declared}
    problems = [f"the template has no token {name!r}" for name in sorted(set(given) - set(by_name))]
    rows = []
    for name, d in by_name.items():
        value = given.get(name)
        missing = value is None and d.get("default") is None
        where = "; ".join(f"{w['kind']} of {w['object']}" for w in d.get("where", []))
        error = None
        if missing:
            error = f"no value for token {name!r} (used in " + ", ".join(f"{w['kind']} of {w['object']}" for w in d.get("where", [])) + ")"
        else:
            bad = _t._tokens.illegal_character(str(value if value is not None else d.get("default")))
            if bad:
                error = f"token {name!r}: the value holds {bad}, which is not allowed in XML"
        if error:
            problems.append(error)
        rows.append({"token": name, "default": d.get("default"), "given": value, "missing": missing,
                     "where": where, "error": error})
    return rows, problems


def plan(t: Template, d: DataSource, *, datasource: Optional[str] = None, mapping: Optional[dict] = None,
         params: Optional[dict] = None, tokens: Optional[dict] = None, allow_missing: bool = False) -> dict:
    """Everything the page shows before a workbook is made: the mapping, the choices for each dropdown, what
    would break, what an apply changes, findings on the data, parameter and token state, and `ready`. Never
    raises for a person's mistake: those become `problems` (and `ready` is false)."""
    problems: list[str] = []
    out = {"mapping": _records(pd.DataFrame(columns=_t.MAPPING_COLUMNS)), "choices": {},
           "broken": _records(pd.DataFrame(columns=_t.BROKEN_COLUMNS)),
           "explain": _records(pd.DataFrame(columns=_t.EXPLAIN_COLUMNS)),
           "check": _records(pd.DataFrame(columns=_t.CHECK_COLUMNS)), "params": [], "tokens": [],
           "missing_required": [], "problems": problems, "ready": False}
    errors = _param_errors(t, params or {})
    by_caption = {caption: message for caption, message in errors if caption}
    out["params"] = [{"parameter": p["caption"], "datatype": p["datatype"], "value": (params or {}).get(p["caption"]),
                      "default": p["value"], "allowed": list(p.get("allowed") or []),
                      "error": by_caption.get(p["caption"])}
                     for p in t.manifest.get("parameters", [])]
    out["tokens"], token_problems = _token_state(t, tokens)
    problems.extend(token_problems)
    problems.extend(f"parameter {caption!r}: {message}" if caption else message for caption, message in errors)
    try:
        entry = t.datasource(datasource)
        out["choices"] = column_choices(entry, d)
        base = _t.suggest_mapping(t, d, datasource)
        frame = mapping_frame(mapping, base, d) if mapping else base
        out["mapping"] = _records(frame)
        out["broken"] = _records(_t.broken_sheets(t, frame, datasource))
        out["explain"] = _records(_t.explain(t, d, frame, datasource))
        out["check"] = _records(_t.check_data(t, d, frame, datasource, deep=False))
        missing = [r for r in frame.to_dict("records") if r["required"] and not r["mapped_to"]]
        out["missing_required"] = [str(_plain(r["caption"]) or r["field"]).strip("[]") for r in missing]
        if missing and not allow_missing:
            problems.append("no column for required field(s) "
                            + ", ".join(str(_plain(r["caption"]) or r["field"]).strip("[]") for r in missing))
    except (TemplateError, ValueError) as e:
        problems.append(_problem(e))
    out["ready"] = not problems
    return out


# ----------------------------------------------------------------- apply --

def output_data_path(raw: str, data: DataSource) -> str:
    """The path written into the output's connection for an uploaded CSV or Excel file: what the person typed
    as the file's place on their computer, with forward slashes (Tableau writes `C:/Users/me/Downloads`).
    Accepts `C:\\Users\\me\\x.csv`, `C:\\Users\\me` (a folder) and `/home/me/x.csv`. When it names a file, the
    file name must equal the uploaded one; the bare file name is used when `raw` is empty."""
    name = Path(data.path).name
    raw = (raw or "").strip()
    if not raw:
        return name
    windows = bool(re.match(r"^[A-Za-z]:", raw) or "\\" in raw)
    pure = PureWindowsPath(raw) if windows else PurePosixPath(raw)
    if pure.suffix:
        if pure.name != name:
            raise TemplateError(f"the file name in {raw!r} is {pure.name!r}, but the uploaded file is {name!r}")
        folder = pure.parent
    else:
        folder = pure
    folder_text = folder.as_posix()
    return name if folder_text in (".", "") else f"{folder_text.rstrip('/')}/{name}"


def _free_name(out_dir: Path, name: str) -> str:
    stem, suffix = Path(name).stem, Path(name).suffix
    candidate, n = name, 1
    while (out_dir / candidate).exists():
        n += 1
        candidate = f"{stem}_{n}{suffix}"
    return candidate


def apply(t: Template, d: DataSource, out_dir: str, *, data_path: Optional[str] = None, datasource: Optional[str] = None,
          mapping: Optional[dict] = None, params: Optional[dict] = None, tokens: Optional[dict] = None,
          allow_missing: bool = False) -> dict:
    """Make the workbook in `out_dir` and return `{name, path, size, report}`. Never overwrites: a name already
    taken gets `_2`, `_3` and so on. `data_path` is what goes into the output's connection (see
    `output_data_path`); the data is read from `d.path` either way. Raises `TemplateError` for what `plan` would
    list as a problem."""
    out = Path(out_dir)
    frame = None
    if mapping:
        frame = mapping_frame(mapping, _t.suggest_mapping(t, d, datasource), d)
    report: dict = {}
    # the data is looked at before its path is replaced: the path may name a folder on another computer
    findings = _t.check_data(t, d, frame if frame is not None else _t.suggest_mapping(t, d, datasource), datasource)
    target = dataclasses.replace(d, path=data_path) if data_path else d
    name = _free_name(out, Path(_t.default_output_path(t, target)).name)
    path = _t.apply_template(t, target, mapping=frame, params=params or None, output_path=str(out / name),
                             datasource=datasource, allow_missing=allow_missing, report=report,
                             tokens=tokens or None)
    report["data_findings"] = len(findings)
    return {"name": name, "path": path, "size": Path(path).stat().st_size,
            "report": {k: _plain(v) if not isinstance(v, (list, dict)) else v for k, v in report.items()}}
