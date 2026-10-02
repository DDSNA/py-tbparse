"""Workbook templates: make one from a finished workbook, apply it to new data.

Not part of the R package. Modelled on Tableau's Accelerators (a list of
required fields, a type-checked mapping, unmapped fields break the sheets
that use them), Power BI `.pbit` files (no data inside, parameter values
asked for on use), Grafana's "export for sharing" (connections become
placeholders) and Copier (the answers are saved in the output so the
template can be re-applied later).

A template is an ordinary `.twbx` (Tableau still opens it) with a
`template.json` manifest inside. Applying it keeps every sheet, dashboard,
calculation and format of the template and points its fields at the new
data: each field keeps the local name that sheets and formulas use, and only
the physical column behind it (the metadata record's `remote-name`) and the
connection change. This mirrors what Tableau's Replace Data Source does, but
the output has not been opened in Tableau itself.
"""

from __future__ import annotations

import copy
import datetime as _dt
import difflib
import hashlib
import io
import json
import os
import re
import zipfile
from dataclasses import dataclass, field as _field
from pathlib import Path
from typing import Iterable, Optional, Union

import pandas as pd
from lxml import etree

from ._clean import is_missing
from .parser import TwbParser
from .rename import _match_key
from .usage import field_usage

MANIFEST_NAME = "template.json"
ANSWERS_NAME = "template-answers.json"
TEMPLATE_FORMAT = "py-tbparse-template"
MANIFEST_VERSION = 1

MAPPING_COLUMNS = [
    "datasource", "field", "caption", "datatype", "required", "used_by",
    "mapped_to", "data_type", "status", "score",
]

_SECRET_ATTRS = ("username", "password")
_CONNECTION_ATTRS = ("class", "server", "dbname", "schema", "port", "directory", "filename",
                     "warehouse", "service", "authentication")
# Members of a .twbx that hold data rather than the workbook's own assets.
_DATA_SUFFIXES = (".hyper", ".tde", ".csv", ".txt", ".tsv", ".xlsx", ".xls", ".xlsm", ".json",
                  ".zip", ".shp", ".shx", ".dbf", ".prj", ".kml", ".geojson", ".mdb", ".accdb", ".sav")

# Tableau's remote-type codes for the file connections we write.
_REMOTE_TYPE = {"string": 129, "integer": 20, "real": 5, "boolean": 11, "date": 7, "datetime": 135}
_NUMERIC = {"integer", "real"}
_DATES = {"date", "datetime"}


class TemplateError(ValueError):
    """The template cannot be made or applied as asked."""


# ---------------------------------------------------------------- helpers --

def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def _version() -> str:
    from . import __version__

    return __version__


def _endswith_tag(el, name: str) -> bool:
    # Tableau prefixes some tags with feature flags: `_.fcp.Flag.true...object-graph`.
    return isinstance(el.tag, str) and (el.tag == name or el.tag.endswith("..." + name))


def _text_of(el) -> str:
    return " ".join(t.strip() for t in el.itertext() if t.strip()) if el is not None else ""


def _role(datatype: Optional[str]) -> str:
    return "measure" if datatype in _NUMERIC else "dimension"


def _non_parameter_datasources(doc) -> list:
    return [ds for ds in doc.xpath("/workbook/datasources/datasource[@name]") if ds.get("name") != "Parameters"]


def _physical_fields(ds) -> list[dict]:
    """The fields a datasource takes straight from its data, from the
    metadata records that link each physical column to a local name."""
    out, seen = [], set()
    for rec in ds.xpath("./connection//metadata-record[@class='column']"):
        local = rec.findtext("local-name")
        if not local or local in seen:
            continue
        seen.add(local)
        out.append({
            "name": local,
            "remote": rec.findtext("remote-name") or local.strip("[]"),
            "table": rec.findtext("parent-name"),
            "datatype": rec.findtext("local-type") or "string",
        })
    return out


# ------------------------------------------------------------------ make --

def _parameters(doc) -> list[dict]:
    out = []
    for col in doc.xpath("/workbook/datasources/datasource[@name='Parameters']/column[@name]"):
        members = [m.get("value") for m in col.xpath("./members/member[@value]")]
        rng = col.find("range")
        out.append({
            "name": col.get("name"),
            "caption": col.get("caption") or col.get("name").strip("[]"),
            "datatype": col.get("datatype"),
            "value": col.get("value"),
            "allowed": members or None,
            "range": {k: rng.get(k) for k in ("min", "max", "granularity") if rng.get(k) is not None}
            if rng is not None else None,
            "description": _text_of(col.find("desc")) or None,
        })
    return out


def _connections(ds) -> list[dict]:
    """Where a datasource's data lives, without credentials."""
    conns = ds.xpath("./connection/named-connections/named-connection/connection") or ds.xpath("./connection")
    out = []
    for c in conns:
        info = {k: c.get(k) for k in _CONNECTION_ATTRS if c.get(k)}
        if info.get("class") != "federated":
            out.append(info)
    return out


def _scrub(doc) -> None:
    for el in doc.iter():
        if isinstance(el.tag, str) and el.tag == "connection":
            for attr in _SECRET_ATTRS:
                if el.get(attr):
                    el.set(attr, "")


def _strip_extracts(doc) -> int:
    n = 0
    for ds in doc.xpath("/workbook/datasources/datasource"):
        for el in list(ds):
            if _endswith_tag(el, "extract"):
                ds.remove(el)
                n += 1
    return n


def build_manifest(parser: TwbParser, name: Optional[str] = None, description: Optional[str] = None) -> dict:
    """The manifest `make_template` writes: what a template needs to be applied."""
    doc = parser.xml_doc
    usage = field_usage(parser)
    used = {(r.datasource, r.field): r for r in usage.itertuples(index=False)}
    datasources = []
    for ds in _non_parameter_datasources(doc):
        dsname = ds.get("name")
        cols = {c.get("name"): c for c in ds.xpath("./column[@name]")}
        fields = []
        for f in _physical_fields(ds):
            col = cols.get(f["name"])
            if col is not None and col.get("{http://www.tableausoftware.com/xml/user}auto-column"):
                continue  # Tableau's own [Number of Records] etc.
            u = used.get((dsname, f["name"]))
            fields.append({
                "name": f["name"],
                "caption": col.get("caption") if col is not None else None,
                "remote": f["remote"],
                "datatype": (col.get("datatype") if col is not None else None) or f["datatype"],
                # what the data delivered; differs from `datatype` when the author retyped the field
                "physical_type": f["datatype"],
                "customized": bool(col is not None and col.get("datatype-customized") == "true"),
                "role": (col.get("role") if col is not None else None) or _role(f["datatype"]),
                "required": bool(u and u.used),
                "used_by": list(u.sheets) if u else [],
                "description": _text_of(col.find("desc")) if col is not None and col.find("desc") is not None else None,
            })
        datasources.append({
            "name": dsname,
            "caption": ds.get("caption"),
            "connections": _connections(ds),
            "fields": fields,
        })
    src = Path(parser.twbx_path or parser.path)
    return {
        "format": TEMPLATE_FORMAT,
        "version": MANIFEST_VERSION,
        "name": name or src.stem,
        "description": description or "",
        "source": src.name,
        "created": _now(),
        "created_with": f"py-tbparse {_version()}",
        "datasources": datasources,
        "parameters": _parameters(doc),
        "worksheets": doc.xpath("/workbook/worksheets/worksheet/@name"),
        "dashboards": doc.xpath("/workbook/dashboards/dashboard/@name"),
    }


def _is_data_member(name: str) -> bool:
    low = name.lower()
    # TwbxExternalCache holds cached query results: data too.
    return low.startswith(("data/", "twbxexternalcache/")) or low.endswith(_DATA_SUFFIXES)


def _write_new(path: Path, data: bytes, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite existing file: {path}")
    with open(path, "wb" if overwrite else "xb") as fh:
        fh.write(data)


def _package(parser: TwbParser, twb: bytes, extra: dict[str, bytes], keep_data: bool,
             drop: Iterable[str] = ()) -> bytes:
    """A .twbx holding `twb` plus `extra` members; the source's other
    members are copied (data files only with `keep_data`)."""
    out = io.BytesIO()
    drop = set(drop) | set(extra)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        if parser.twbx_path:
            twb_name = parser.twb_name
            with zipfile.ZipFile(parser.twbx_path) as src:
                for info in src.infolist():
                    if info.filename == twb_name:
                        dst.writestr(info, twb, compress_type=info.compress_type)
                    elif info.filename in drop or (not keep_data and _is_data_member(info.filename)):
                        continue
                    else:
                        dst.writestr(info, src.read(info.filename), compress_type=info.compress_type)
        else:
            dst.writestr(Path(parser.path).name, twb)
        for name, data in extra.items():
            dst.writestr(name, data)
    return out.getvalue()


def default_template_path(parser: TwbParser) -> str:
    src = Path(parser.twbx_path or parser.path)
    return str(src.with_name(f"{src.stem}.template.twbx"))


def make_template(
    parser: Union[TwbParser, str],
    output_path: Optional[str] = None,
    name: Optional[str] = None,
    description: Optional[str] = None,
    keep_data: bool = False,
    overwrite: bool = False,
) -> str:
    """Save a template made from a finished workbook; return its path.

    The template is a `.twbx` (default `<name>.template.twbx` beside the
    source) holding a copy of the workbook and a `template.json` manifest
    that lists the fields the workbook needs (`required` when a sheet uses
    them, directly or through calculations, groups and sets), its
    parameters and where its data came from. Passwords and user names are
    blanked. Extracts and packaged data files are left out unless
    `keep_data` (handy for an Accelerator-style template that opens with
    sample data). The source is never modified and nothing is overwritten
    unless `overwrite=True`.
    """
    if not isinstance(parser, TwbParser):
        parser = TwbParser(str(parser))
    out = Path(output_path) if output_path else Path(default_template_path(parser))
    if out.suffix.lower() != ".twbx":
        raise TemplateError(f"a template is a .twbx file, got {out.suffix or 'no extension'}")
    if out.resolve() == Path(parser.twbx_path or parser.path).resolve():
        raise FileExistsError(f"refusing to overwrite the source workbook: {out}")
    manifest = build_manifest(parser, name=name, description=description)
    doc = copy.deepcopy(parser.xml_doc)
    _scrub(doc)
    if not keep_data:
        _strip_extracts(doc)
    twb = etree.tostring(doc, xml_declaration=True, encoding="utf-8")
    data = _package(parser, twb, {MANIFEST_NAME: json.dumps(manifest, indent=2).encode("utf-8")},
                    keep_data=keep_data, drop=[ANSWERS_NAME])
    _write_new(out, data, overwrite)
    return str(out)


# ------------------------------------------------------------------ load --

@dataclass
class Template:
    path: str
    parser: TwbParser
    manifest: dict
    manifest_sha256: str = ""

    @property
    def name(self) -> str:
        return self.manifest.get("name") or Path(self.path).stem

    def datasource(self, which: Optional[str] = None) -> dict:
        """The manifest entry of one template datasource, by internal name or
        caption; with no name, the one that has required fields (or the
        only one)."""
        entries = self.manifest.get("datasources", [])
        if which:
            for e in entries:
                if which in (e["name"], e.get("caption")):
                    return e
            raise TemplateError(f"template has no datasource {which!r}; it has: "
                                + ", ".join(e.get("caption") or e["name"] for e in entries))
        with_required = [e for e in entries if any(f["required"] for f in e["fields"])]
        pick = with_required or entries
        if len(pick) != 1:
            raise TemplateError("template has several datasources; pick one with datasource=: "
                                + ", ".join(e.get("caption") or e["name"] for e in pick))
        return pick[0]

    def fields(self) -> pd.DataFrame:
        rows = []
        for ds in self.manifest.get("datasources", []):
            for f in ds["fields"]:
                rows.append({"datasource": ds.get("caption") or ds["name"], "field": f["name"],
                             "caption": f.get("caption"), "datatype": f["datatype"],
                             "required": f["required"], "used_by": "; ".join(f.get("used_by") or [])})
        return pd.DataFrame(rows, columns=["datasource", "field", "caption", "datatype", "required", "used_by"])

    def parameters(self) -> pd.DataFrame:
        rows = [{"parameter": p["caption"], "datatype": p["datatype"], "value": p["value"],
                 "allowed": "; ".join(p["allowed"]) if p.get("allowed") else ""}
                for p in self.manifest.get("parameters", [])]
        return pd.DataFrame(rows, columns=["parameter", "datatype", "value", "allowed"])


def load_template(path: str) -> Template:
    """Open a template made by `make_template`."""
    if not str(path).lower().endswith(".twbx"):
        raise TemplateError(f"not a template (.twbx expected): {path}")
    with zipfile.ZipFile(path) as z:
        if MANIFEST_NAME not in z.namelist():
            raise TemplateError(f"{path} has no {MANIFEST_NAME}; make one with `py-tbparse template make`")
        raw = z.read(MANIFEST_NAME)
    manifest = json.loads(raw.decode("utf-8"))
    if manifest.get("format") != TEMPLATE_FORMAT:
        raise TemplateError(f"{path}: unknown template format {manifest.get('format')!r}")
    if int(manifest.get("version", 0)) > MANIFEST_VERSION:
        raise TemplateError(f"{path} was made by a newer py-tbparse (manifest v{manifest['version']})")
    return Template(path=str(path), parser=TwbParser(str(path)), manifest=manifest,
                    manifest_sha256=hashlib.sha256(raw).hexdigest())


# ------------------------------------------------------------- the data --

@dataclass
class DataSource:
    """New data for a template: its fields, and how to connect to it."""

    path: str
    kind: str  # "csv" or "tableau"
    fields: list[dict] = _field(default_factory=list)  # {name, datatype}
    element: object = None  # the Tableau <datasource> for kind "tableau"

    def names(self) -> list[str]:
        return [f["name"] for f in self.fields]

    def datatype(self, name: str) -> Optional[str]:
        for f in self.fields:
            if f["name"] == name:
                return f["datatype"]
        return None


def _infer_csv_type(series: pd.Series) -> Optional[str]:
    """Tableau's type for a CSV column; None when it has no values to judge by."""
    if series.dropna().astype(str).str.strip().eq("").all():
        return None
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_integer_dtype(series):
        return "integer"
    if pd.api.types.is_float_dtype(series):
        # whole numbers with blanks come back as float
        s = series.dropna()
        return "integer" if len(s) and (s == s.round()).all() and series.isna().any() else "real"
    s = series.dropna().astype(str)
    if s.str.lower().isin(["true", "false"]).all():
        return "boolean"
    if s.str.match(r"^\d{4}-\d{1,2}-\d{1,2}([ T]\d{1,2}:\d{2}(:\d{2})?)?$").all() or \
            s.str.match(r"^\d{1,2}/\d{1,2}/\d{2,4}( \d{1,2}:\d{2}(:\d{2})?)?$").all():
        return "datetime" if s.str.contains(":").any() else "date"
    return "string"


def read_data(path: str, datasource: Optional[str] = None) -> DataSource:
    """Describe new data for `apply_template`: a CSV file, or a Tableau
    workbook (`.twb`/`.twbx`) or data source (`.tds`) already connected to
    it (pick one of several datasources with `datasource=`)."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"no such file: {path}")
    suffix = p.suffix.lower()
    if suffix in (".csv", ".txt", ".tsv"):
        sep = "\t" if suffix == ".tsv" else ","
        df = pd.read_csv(p, sep=sep, nrows=2000, encoding="utf-8-sig")
        return DataSource(path=str(p.resolve()), kind="csv",
                          fields=[{"name": str(c), "datatype": _infer_csv_type(df[c])} for c in df.columns])
    if suffix in (".twb", ".twbx"):
        doc = TwbParser(str(p)).xml_doc
        candidates = _non_parameter_datasources(doc)
    elif suffix == ".tds":
        root = etree.parse(str(p)).getroot()
        candidates = [root] if root.tag == "datasource" else root.xpath("//datasource[@name]")
    else:
        raise TemplateError(f"unsupported data file {p.name}: use a .csv, .twb, .twbx or .tds")
    if datasource:
        candidates = [d for d in candidates if datasource in (d.get("name"), d.get("caption"), d.get("formatted-name"))]
    candidates = [d for d in candidates if d.find("connection") is not None]
    if len(candidates) != 1:
        names = [d.get("caption") or d.get("name") for d in candidates]
        raise TemplateError(f"{p.name}: expected one datasource with a connection, found {len(candidates)}"
                            + (f" ({', '.join(names)}); pick one" if names else ""))
    ds = candidates[0]
    fields = [{"name": f["remote"], "datatype": f["datatype"], "local": f["name"]} for f in _physical_fields(ds)]
    if not fields:
        raise TemplateError(f"{p.name}: the datasource lists no columns (open it in Tableau once and save)")
    return DataSource(path=str(p.resolve()), kind="tableau", fields=fields, element=ds)


# --------------------------------------------------------------- mapping --

def _type_status(want: str, got: Optional[str]) -> Optional[str]:
    """None when compatible; otherwise why not (a "differs" status still maps)."""
    if got is None or want == got:
        return None
    if want in _NUMERIC and got in _NUMERIC:
        return "numeric type differs"
    if want in _DATES and got in _DATES:
        return "date type differs"
    return "type mismatch"


def suggest_mapping(
    template: Template,
    data: DataSource,
    datasource: Optional[str] = None,
    fuzzy_cutoff: float = 0.85,
) -> pd.DataFrame:
    """Pair each field the template needs with a column of the new data.

    A field matches a column whose name, ignoring case and separators,
    equals the field's caption, local name or original column name
    (`matched`); failing that, the closest name above `fuzzy_cutoff`
    (`close match`, never across a different number). Types are checked like
    Tableau's Accelerator mapper: a string column is never offered for a
    number or a date (`type mismatch`, left unmapped); integer vs real and
    date vs datetime map with a warning status. Each column is used once,
    required fields first. Unmapped fields have `status` `missing`
    (required) or `unused` (not used by any sheet).

    Returns `datasource, field, caption, datatype, required, used_by,
    mapped_to, data_type, status, score`.
    """
    if not 0 <= fuzzy_cutoff <= 1:
        raise ValueError(f"fuzzy_cutoff must be between 0 and 1, got {fuzzy_cutoff}")
    entry = template.datasource(datasource)
    by_key: dict[str, str] = {}
    for n in data.names():
        by_key.setdefault(_match_key(n), n)
    keys = list(by_key)
    taken: set = set()
    rows = []
    fields = sorted(entry["fields"], key=lambda f: not f["required"])
    for f in fields:
        names = [f.get("caption"), f["name"].strip("[]"), f.get("remote")]
        names = [n for n in names if n]
        pick, status, score = None, None, None
        for n in names:
            k = _match_key(n)
            if k in by_key and by_key[k] not in taken:
                pick, status, score = by_key[k], "matched", 1.0
                break
        if pick is None:
            best = None
            for n in names:
                k = _match_key(n)
                if not k:
                    continue
                digits = re.findall(r"\d+", k)
                for cand in difflib.get_close_matches(k, keys, n=5, cutoff=fuzzy_cutoff):
                    if re.findall(r"\d+", cand) != digits or by_key[cand] in taken:
                        continue
                    ratio = difflib.SequenceMatcher(None, k, cand).ratio()
                    if best is None or ratio > best[1]:
                        best = (by_key[cand], ratio)
            if best:
                pick, status, score = best[0], "close match", round(best[1], 3)
        if pick is not None:
            # Compare like with like: the column the template was built on vs the new one.
            # A field the author retyped keeps that type; Tableau converts the new column.
            got = data.datatype(pick)
            problems = [_type_status(f.get("physical_type") or f["datatype"], got)]
            if f.get("customized"):  # a column already of the field's own type also works
                problems.append(_type_status(f["datatype"], got))
            problem = None if None in problems else min(problems, key=lambda s: s == "type mismatch")
            if problem == "type mismatch":
                pick, status, score = None, f"type mismatch ({data.datatype(pick)} column {pick!r})", None
            elif problem:
                status = problem
        if pick is not None:
            taken.add(pick)
        elif status is None:
            status = "missing" if f["required"] else "unused"
        rows.append({
            "datasource": entry["name"], "field": f["name"], "caption": f.get("caption"),
            "datatype": f["datatype"], "required": bool(f["required"]),
            "used_by": "; ".join(f.get("used_by") or []),
            "mapped_to": pick or "", "data_type": data.datatype(pick) if pick else "",
            "status": status, "score": score,
        })
    return pd.DataFrame(rows, columns=MAPPING_COLUMNS)


def load_mapping(source: Union[str, os.PathLike, pd.DataFrame]) -> pd.DataFrame:
    """Read a mapping back in (the CSV `suggest_mapping` / `template apply
    --mapping-out` wrote, with `mapped_to` edited by hand; blank means no
    column)."""
    df = source.copy() if isinstance(source, pd.DataFrame) else pd.read_csv(
        source, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    df.columns = [str(c).strip() for c in df.columns]
    missing = [c for c in ("field", "mapped_to") if c not in df.columns]
    if missing:
        raise ValueError(f"mapping is missing column(s): {', '.join(missing)}")
    df["mapped_to"] = df["mapped_to"].map(lambda v: "" if is_missing(v) else str(v).strip())
    used = df[df["mapped_to"] != ""]["mapped_to"]
    dup = used[used.duplicated()]
    if len(dup):
        raise ValueError(f"column {dup.iloc[0]!r} is mapped to more than one field")
    return df


def broken_sheets(template: Template, mapping: pd.DataFrame, datasource: Optional[str] = None) -> pd.DataFrame:
    """Required fields with no column, and the sheets that will not work."""
    entry = template.datasource(datasource)
    mapped = {r["field"] for r in mapping.to_dict("records") if r.get("mapped_to")}
    rows = [{"field": f["name"], "caption": f.get("caption"), "sheets": "; ".join(f.get("used_by") or [])}
            for f in entry["fields"] if f["required"] and f["name"] not in mapped]
    return pd.DataFrame(rows, columns=["field", "caption", "sheets"])


# ----------------------------------------------------------------- apply --

def _param_literal(datatype: str, raw: str) -> str:
    """Tableau's literal for a parameter value: `5`, `"East"`, `#2026-01-31#`."""
    raw = str(raw).strip()
    if datatype in _NUMERIC:
        try:
            num = float(raw)
        except ValueError:
            raise TemplateError(f"{raw!r} is not a number") from None
        if datatype == "integer":
            if num != int(num):
                raise TemplateError(f"{raw!r} is not a whole number")
            return str(int(num))
        return repr(num) if num != int(num) else f"{num:.1f}"
    if datatype == "boolean":
        if raw.lower() not in ("true", "false"):
            raise TemplateError(f"{raw!r} is not true or false")
        return raw.lower()
    if datatype in _DATES:
        try:
            when = pd.Timestamp(raw)
        except (ValueError, TypeError):
            raise TemplateError(f"{raw!r} is not a date") from None
        return "#" + (when.strftime("%Y-%m-%d") if datatype == "date" else when.strftime("%Y-%m-%d %H:%M:%S")) + "#"
    return '"' + raw.replace('"', '""') + '"'


def _set_parameters(doc, params: dict[str, str], template: Template) -> dict[str, str]:
    known = {p["caption"]: p for p in template.manifest.get("parameters", [])}
    known.update({p["name"].strip("[]"): p for p in template.manifest.get("parameters", [])})
    applied = {}
    for key, raw in params.items():
        p = known.get(key) or known.get(key.strip("[]"))
        if p is None:
            raise TemplateError(f"template has no parameter {key!r}; it has: "
                                + ", ".join(q["caption"] for q in template.manifest.get("parameters", [])))
        try:
            literal = _param_literal(p["datatype"], raw)
        except TemplateError as e:
            raise TemplateError(f"parameter {p['caption']!r}: {e}") from None
        if p.get("allowed") and literal not in p["allowed"]:
            raise TemplateError(f"parameter {p['caption']!r}: {raw!r} is not one of its allowed values")
        for col in doc.xpath("/workbook/datasources/datasource[@name='Parameters']/column[@name=$n]", n=p["name"]):
            col.set("value", literal)
            calc = col.find("calculation")
            if calc is not None:
                calc.set("formula", literal)
        applied[p["caption"]] = literal
    return applied


def _connection_id(kind: str, path: str) -> str:
    return f"{kind}." + hashlib.sha1(path.encode("utf-8")).hexdigest()[:28]


_OM = "_.fcp.ObjectModelEncapsulateLegacy"   # Tableau 2020.2+ object model feature flags
_OM_TABLE = "_.fcp.ObjectModelTableType.true...column"


def _uses_object_model(doc) -> bool:
    return any(isinstance(el.tag, str) and el.tag.startswith(_OM) for el in doc.iter())


def _csv_connection(data: DataSource, local_of: dict[str, str], modern: bool = True):
    """A federated connection to a CSV file, in the shape Tableau writes.

    With `modern` (the template uses Tableau's 2020.2+ object model) it also
    returns the table column and object graph the datasource needs, and
    writes the legacy and object-model relations side by side, as Tableau
    does."""
    p = Path(data.path)
    conn_id = _connection_id("textscan", data.path)
    table = p.name
    object_id = f"{re.sub(r'[^0-9A-Za-z_]', '_', p.stem)}_" + hashlib.md5(data.path.encode("utf-8")).hexdigest().upper()
    conn = etree.Element("connection", {"class": "federated"})
    named = etree.SubElement(etree.SubElement(conn, "named-connections"), "named-connection",
                             caption=p.stem, name=conn_id)
    etree.SubElement(named, "connection", {
        "class": "textscan", "directory": p.parent.as_posix(), "filename": p.name,
        "password": "", "server": "",
    })

    def relation():
        rel = etree.Element("relation", connection=conn_id, name=table,
                            table=f"[{p.stem}#{p.suffix.lstrip('.')}]", type="table")
        cols = etree.SubElement(rel, "columns", {"character-set": "UTF-8", "header": "yes", "locale": "en_US",
                                                 "separator": "\t" if p.suffix.lower() == ".tsv" else ","})
        for i, f in enumerate(data.fields):
            etree.SubElement(cols, "column", datatype=f["datatype"], name=f["name"], ordinal=str(i))
        return rel

    if modern:
        for flag in ("false", "true"):
            rel = relation()
            rel.tag = f"{_OM}.{flag}...relation"
            conn.append(rel)
    else:
        conn.append(relation())
    records = etree.SubElement(conn, "metadata-records")
    for i, f in enumerate(data.fields):
        rec = etree.SubElement(records, "metadata-record", {"class": "column"})
        for tag, text in (
            ("remote-name", f["name"]), ("remote-type", str(_REMOTE_TYPE.get(f["datatype"], 129))),
            ("local-name", local_of[f["name"]]), ("parent-name", f"[{table}]"),
            ("remote-alias", f["name"]), ("ordinal", str(i)), ("local-type", f["datatype"]),
            ("aggregation", "Sum" if f["datatype"] in _NUMERIC else "Count"), ("contains-null", "true"),
        ):
            etree.SubElement(rec, tag).text = text
        if modern:
            etree.SubElement(rec, f"{_OM}.true...object-id").text = f"[{object_id}]"
    if not modern:
        return conn, []
    table_col = etree.Element(_OM_TABLE, caption=p.stem, datatype="table",
                              name=f"[__tableau_internal_object_id__].[{object_id}]",
                              role="measure", type="quantitative")
    graph = etree.Element(f"{_OM}.true...object-graph")
    obj = etree.SubElement(etree.SubElement(graph, "objects"), "object", caption=p.stem, id=object_id)
    props = etree.SubElement(obj, "properties", context="")
    props.append(relation())
    return conn, [table_col, graph]


def _tableau_connection(data: DataSource, local_of: dict[str, str]):
    """The new data's own connection, with each column's local name set to
    the template field it now feeds."""
    src = data.element
    conn = copy.deepcopy(src.find("connection"))
    rename = {f["local"]: local_of[f["name"]] for f in data.fields}
    for rec in conn.xpath(".//metadata-record[@class='column']"):
        el = rec.find("local-name")
        if el is not None and el.text in rename:
            el.text = rename[el.text]
    for m in conn.xpath(".//cols/map[@key]"):
        if m.get("key") in rename:
            m.set("key", rename[m.get("key")])
    # The object model (2020.2+) describes the tables of this connection.
    extras = [copy.deepcopy(el) for el in src if _endswith_tag(el, "object-graph")
              or (isinstance(el.tag, str) and el.tag.endswith("column") and el.get("datatype") == "table")]
    return conn, extras


def default_output_path(template: Template, data: DataSource) -> str:
    stem = Path(template.path).name
    for suffix in (".template.twbx", ".twbx"):
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    return str(Path(template.path).with_name(f"{stem}_{Path(data.path).stem}.twbx"))


def apply_template(
    template: Union[Template, str],
    data: Union[DataSource, str],
    mapping: Optional[pd.DataFrame] = None,
    params: Optional[dict[str, str]] = None,
    output_path: Optional[str] = None,
    datasource: Optional[str] = None,
    data_datasource: Optional[str] = None,
    allow_missing: bool = False,
    overwrite: bool = False,
    report: Optional[dict] = None,
) -> str:
    """Make a new workbook from a template and new data; return its path.

    `mapping` defaults to `suggest_mapping(template, data)`; pass an edited
    one (see `load_mapping`) to choose columns yourself. A required field
    with no column would break the sheets listed by `broken_sheets`, so that
    raises `TemplateError` unless `allow_missing=True`. `params` sets
    parameter values by caption (`{"Top N": "10"}`), checked against the
    parameter's type and allowed values.

    The template datasource's connection is replaced by one to the new data
    (a CSV file, or the connection of the given workbook / .tds); every
    field keeps the local name its sheets and formulas use. The answers
    (template, data, mapping, parameters) are saved inside the output as
    `template-answers.json`. Output is a `.twbx` (default
    `<template>_<data>.twbx` beside the template) and is never overwritten
    unless `overwrite=True`.
    """
    if not isinstance(template, Template):
        template = load_template(template)
    if not isinstance(data, DataSource):
        data = read_data(data, datasource=data_datasource)
    entry = template.datasource(datasource)
    if mapping is None:
        mapping = suggest_mapping(template, data, datasource=entry["name"])
    else:
        mapping = load_mapping(mapping)
    by_field = {f["name"]: f for f in entry["fields"]}
    chosen: dict[str, str] = {}
    for r in mapping.to_dict("records"):
        if r["field"] not in by_field:
            raise TemplateError(f"mapping names {r['field']!r}, which the template does not have")
        if r.get("mapped_to"):
            if r["mapped_to"] not in data.names():
                raise TemplateError(f"mapping uses column {r['mapped_to']!r}, which {Path(data.path).name} does not have")
            chosen[r["field"]] = r["mapped_to"]
    missing = [f for f in entry["fields"] if f["required"] and f["name"] not in chosen]
    if missing and not allow_missing:
        sheets = sorted({s for f in missing for s in f.get("used_by") or []})
        raise TemplateError(
            "no column for required field(s) "
            + ", ".join(f.get("caption") or f["name"].strip("[]") for f in missing)
            + f"; sheets that would break: {', '.join(sheets)} (map them, or pass allow_missing)"
        )

    # local name for every column of the new data
    field_of = {col: fld for fld, col in chosen.items()}
    reserved = {f["name"] for f in entry["fields"]}
    local_of: dict[str, str] = {}
    for f in data.fields:
        if f["name"] in field_of:
            local_of[f["name"]] = field_of[f["name"]]
            continue
        local = "[" + f["name"].replace("]", "]]") + "]"
        while local in reserved or local in local_of.values():
            local = local[:-1] + " (data)]"
        local_of[f["name"]] = local

    doc = copy.deepcopy(template.parser.xml_doc)
    ds_el = doc.xpath("/workbook/datasources/datasource[@name=$n]", n=entry["name"])[0]
    if data.kind == "csv":
        # a column with no values takes the type of the field it feeds (else string)
        typed = copy.copy(data)
        typed.fields = [{**f, "datatype": f["datatype"] or (
            by_field[field_of[f["name"]]].get("physical_type") or by_field[field_of[f["name"]]]["datatype"]
            if f["name"] in field_of else "string")} for f in data.fields]
        conn, extras = _csv_connection(typed, local_of, modern=_uses_object_model(doc))
    else:
        conn, extras = _tableau_connection(data, local_of)
    old = ds_el.find("connection")
    for el in list(ds_el):
        if el is not old and (_endswith_tag(el, "extract") or _endswith_tag(el, "object-graph")
                              or (isinstance(el.tag, str) and el.tag.endswith("column")
                                  and el.get("datatype") == "table")):
            ds_el.remove(el)
    if old is not None:
        old.addprevious(conn)
        ds_el.remove(old)
    else:
        ds_el.insert(0, conn)
    for el in extras:
        if _endswith_tag(el, "object-graph"):
            ds_el.append(el)  # Tableau writes it last
            continue
        cols = [c for c in ds_el if isinstance(c.tag, str) and (c.tag == "column" or c.tag.endswith("...column"))]
        (cols[-1].addnext(el) if cols else conn.addnext(el))
    # a field now fed by a column of another type takes that type, unless the
    # author set the field's type by hand (Tableau then converts the column)
    for fld, col in chosen.items():
        new_type = data.datatype(col)
        for c in ds_el.xpath("./column[@name=$n]", n=fld):
            if new_type and c.get("datatype") != new_type and c.get("datatype-customized") != "true":
                c.set("datatype", new_type)

    applied_params = _set_parameters(doc, params or {}, template)
    answers = {
        "format": TEMPLATE_FORMAT + "-answers",
        "version": MANIFEST_VERSION,
        "created": _now(),
        "created_with": f"py-tbparse {_version()}",
        "template": {"name": template.name, "file": Path(template.path).name,
                     "manifest_sha256": template.manifest_sha256},
        "data": {"file": data.path, "kind": data.kind,
                 "datasource": data.element.get("name") if data.element is not None else None},
        "datasource": entry["name"],
        "mapping": {fld: col for fld, col in chosen.items()},
        "missing": [f["name"] for f in missing],
        "parameters": applied_params,
    }
    twb = etree.tostring(doc, xml_declaration=True, encoding="utf-8")
    out = Path(output_path) if output_path else Path(default_output_path(template, data))
    if out.suffix.lower() != ".twbx":
        raise TemplateError(f"output must be a .twbx file, got {out.suffix or 'no extension'}")
    if out.resolve() in (Path(template.path).resolve(), Path(data.path).resolve()):
        raise FileExistsError(f"refusing to overwrite an input: {out}")
    packed = _package(template.parser, twb, {ANSWERS_NAME: json.dumps(answers, indent=2).encode("utf-8")},
                      keep_data=False, drop=[MANIFEST_NAME])
    _write_new(out, packed, overwrite)
    if report is not None:
        report.update(mapped=len(chosen), missing=len(missing), parameters=len(applied_params))
    return str(out)


def read_answers(path: str) -> Optional[dict]:
    """The `template-answers.json` of a workbook made by `apply_template`, or None."""
    with zipfile.ZipFile(path) as z:
        if ANSWERS_NAME not in z.namelist():
            return None
        return json.loads(z.read(ANSWERS_NAME).decode("utf-8"))
