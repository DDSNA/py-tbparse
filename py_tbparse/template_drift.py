"""`template drift`: does a folder (or glob) of data files still fit a template? (WP17c)

Not part of the R package. The files are read as one source (`multifile.py`) and every file is compared with a
reference: the template's mapping (or the mapping saved in answers) and the columns the answers saved, else
the template's own field names. The rules (D001...) are functions registered with the findings engine
(`findings.py`) in the scope `"drift"`, so `--format junit|sarif|github`, `--only`, `--skip` and the exit codes
work as in `template check`. Ids are stable and never reused. To add a rule, write one more function with
`@rule("D0xx", "drift", ...)` and add the id to the list in `tests/test_template_drift.py`.

One finding is one file and one issue; `object` is the file's name (relative to the folder, or to the fixed part
of the glob), plus the column when the issue is about one. What counts as the baseline when nothing is saved:
the encoding, separator, Excel header cell and column order that most files share (a tie goes to the file that
sorts first), the type most files give a column (a tie goes to the type the mapped field expects, then to the
merged type).

Nothing here is checked in Tableau Desktop: the rules say what differs between files, not what Tableau does
with them. In particular, that Tableau treats `Region` and `region ` as different columns, and matches a union's
columns by name, is recollection (see the WP17 research).
"""

from __future__ import annotations

import difflib
import json
import os
import re
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Union

import pandas as pd

from .findings import Subject, finding, rule, rule_ids, rules, run_rules
from .multifile import MAX_FILES, FilePart, MultiSource, read_many
from .rename import _match_key
from .templates import (
    ANSWERS_NAME,
    MANIFEST_NAME,
    DataSource,
    TemplateError,
    _NUMERIC,
    _DATES,
    _answers_entry,
    _match_fields,
    _overlay_mapping,
    load_answers,
    load_template,
)

SCOPE = "drift"
_SIMILAR = 0.6          # how alike two column names must be to be called a likely rename


def drift_rule_ids() -> list[str]:
    return rule_ids(SCOPE)


@dataclass
class DriftContext:
    """What the rules compare each file with."""

    multi: MultiSource
    entry: dict                       # the template's datasource entry (name, fields)
    mapping: pd.DataFrame             # the reference mapping, one row per template field
    ref_names: set                    # columns the reference knows (exact spelling)
    ref_order: list                   # column order the files are compared with
    saved: Optional[dict] = None      # the saved `data` block of the answers, if it is a multi-file one
    saved_columns: bool = False       # the column order comes from the answers
    saved_fingerprint: Optional[str] = None
    base_dir: Optional[str] = None    # what the saved file paths are relative to
    _facts: Optional[dict] = field(default=None, repr=False)

    def fields(self) -> dict:
        return {f["name"]: f for f in self.entry["fields"]}

    def facts(self) -> dict:
        if self._facts is None:
            self._facts = _analyse(self)
        return self._facts


# ------------------------------------------------------------- reference --

def _kind_of(path: str) -> str:
    p = Path(path)
    if p.suffix.lower() == ".json":
        return "answers"
    if p.suffix.lower() == ".twbx":
        with zipfile.ZipFile(p) as z:
            names = z.namelist()
        if MANIFEST_NAME in names:
            return "template"
        if ANSWERS_NAME in names:
            return "answers"
    return "template"


def _pick_entry(manifest: dict, which: Optional[str]) -> dict:
    entries = manifest.get("datasources", [])
    if which:
        for e in entries:
            if which in (e["name"], e.get("caption")):
                return e
        raise TemplateError(f"no datasource {which!r}; there is: " + ", ".join(e.get("caption") or e["name"] for e in entries))
    pick = [e for e in entries if any(f["required"] for f in e["fields"])] or entries
    if len(pick) != 1:
        raise TemplateError("several datasources; pick one with datasource=: " + ", ".join(e.get("caption") or e["name"] for e in pick))
    return pick[0]


def _names_of(f: dict) -> list:
    return list(dict.fromkeys(n for n in [f.get("caption"), f["name"].strip("[]"), f.get("remote"), f.get("alias")] if n))


def _reference(source, answers, datasource: Optional[str]) -> tuple[dict, Optional[dict]]:
    """`(datasource entry, saved answers or None)` from a template or an answers file (and optional answers)."""
    if isinstance(source, dict) or (not hasattr(source, "manifest") and _kind_of(os.fspath(source)) == "answers"):
        saved = load_answers(source)
        manifest = (saved.get("template") or {}).get("manifest")
        if not manifest:
            raise TemplateError("these answers carry no copy of the template's fields; pass the template as well "
                                "(`template drift TEMPLATE FILES --answers ANSWERS`)")
        return _pick_entry(manifest, datasource or saved.get("datasource")), saved
    template = source if hasattr(source, "manifest") else load_template(os.fspath(source))
    saved = load_answers(answers) if answers is not None else None
    if saved is not None and template.id and saved.get("template", {}).get("id") not in (None, template.id):
        raise TemplateError(f"these answers were made for another template (id {saved['template']['id']}, "
                            f"this one is {template.id})")
    return template.datasource(datasource or (saved or {}).get("datasource")), saved


def _common(values: Iterable, tie: Iterable = ()):
    """The most common value; a tie goes to the first of `tie` that is among the leaders, else to the first seen."""
    values = list(values)
    if not values:
        return None
    counts = Counter(values)
    top = max(counts.values())
    leaders = [v for v in counts if counts[v] == top]
    for t in tie:
        if t in leaders:
            return t
    return leaders[0]


def build_context(source, files, answers=None, datasource: Optional[str] = None, sheet: Union[str, int, None] = None,
                  max_files: int = MAX_FILES) -> DriftContext:
    """Read the files and settle the reference (see the module docstring); raises `TemplateError` or
    `FileNotFoundError` when either cannot be done."""
    entry, saved = _reference(source, answers, datasource)
    prior = _answers_entry(saved, entry["name"]) if saved is not None else {}
    saved_data = prior.get("data") or {}
    base_dir = (saved or {}).get("_base_dir")
    if sheet is None and saved_data.get("sheet"):
        sheet = saved_data["sheet"]
    multi = read_many(files, sheet=sheet, max_files=max_files)
    # Match on names only: a column that one odd file turned into text must still be the mapped column (D006
    # reports the type), not drop out of the mapping because the merged type no longer fits the field.
    names_only = DataSource(path=multi.merged.path, kind=multi.merged.kind,
                            fields=[{"name": n, "datatype": None} for n in multi.names()])
    mapping = _match_fields(entry["fields"], names_only, entry["name"])
    if prior.get("mapping"):
        mapping, stale = _overlay_mapping(mapping, prior["mapping"], names_only, entry)
        names = {f["name"] for f in entry["fields"]}
        for fld in stale:        # a saved column no file has any more is still the column the answers mean
            if fld in names:
                mapping.loc[mapping["field"] == fld, "mapped_to"] = prior["mapping"][fld]
    mapped = {c for c in mapping["mapped_to"] if c}
    if saved_data.get("columns"):
        ref_names = set(saved_data["columns"]) | mapped
        ref_order = list(saved_data["columns"])
    else:
        ref_names = {n for f in entry["fields"] for n in _names_of(f)} | mapped
        ok = [tuple(p.columns) for p in multi.parts if p.data is not None]
        ref_order = list(_common(ok) or ())
    return DriftContext(multi=multi, entry=entry, mapping=mapping, ref_names=ref_names, ref_order=ref_order,
                        saved=saved_data if saved_data.get("kind") == "union" else None,
                        saved_columns=bool(saved_data.get("columns")),
                        saved_fingerprint=saved_data.get("schema_fingerprint"), base_dir=base_dir)


# -------------------------------------------------------------- analysis --

def _digits(text: str) -> list:
    return re.findall(r"\d+", text)


def _analyse(ctx: DriftContext) -> dict:
    """Per file name: the mapped columns it lacks, the columns the reference does not know, and which of those pair
    up as a rename (`spelling` or `similar`)."""
    mapped = [(r.field, r.mapped_to, bool(r.required)) for r in ctx.mapping.itertuples() if r.mapped_to]
    out = {}
    for part in ctx.multi.parts:
        if part.data is None:
            continue
        have = set(part.columns)
        missing = [(f, c, req) for f, c, req in mapped if c not in have]
        extras = [c for c in part.columns if c not in ctx.ref_names]
        pairs: list = []
        free = list(extras)
        for kind in ("spelling", "similar"):
            for _f, m, _r in missing:
                if any(m == p[0] for p in pairs) or not _match_key(m):
                    continue
                if kind == "spelling":
                    hit = next((e for e in free if _match_key(e) == _match_key(m)), None)
                else:
                    scored = [(difflib.SequenceMatcher(None, _match_key(m), _match_key(e)).ratio(), e) for e in free
                              if _match_key(e) and _digits(_match_key(e)) == _digits(_match_key(m))]
                    scored = [s for s in scored if s[0] >= _SIMILAR]
                    hit = max(scored, key=lambda s: s[0])[1] if scored else None
                if hit is not None:
                    pairs.append((m, hit, kind))
                    free.remove(hit)
        out[part.name] = {"missing": missing, "extras": extras, "pairs": pairs, "free": free}
    return out


def _quote(text: str) -> str:
    return "'" + text + "'"


# ----------------------------------------------------------------- rules --

@rule("D001", SCOPE,
      severity="error",
      title="Column the mapping needs is missing from a file",
      fix="Restore the column in the file, or map the field to another column; an optional field only loses what uses it")
def mapped_column_missing(s: Subject):
    """A column the template's mapping needs is missing from a file."""
    ctx: DriftContext = s.extra
    for r in ctx.mapping.itertuples():
        if r.required and not r.mapped_to:
            yield finding(r.field.strip("[]"), "no file has a column for this required field")
    for part in ctx.multi.parts:
        for fld, col, req in ctx.facts().get(part.name, {}).get("missing", []):
            yield finding(f"{part.name}: {col}", f"the column mapped to {fld.strip('[]')} is missing"
                          + ("" if req else " (the field is optional)"),
                          severity="error" if req else "warning")


@rule("D002", SCOPE,
      severity="error",
      title="File with another encoding or separator than the rest",
      fix="Save the file with the encoding and separator of the others; one text connection has one of each")
def encoding_or_separator(s: Subject):
    """A CSV file has another encoding or separator than most of the files."""
    ctx: DriftContext = s.extra
    csv = [p for p in ctx.multi.parts if p.kind == "csv" and p.encoding]
    enc = _common(p.encoding for p in csv)
    sep = _common(p.separator for p in csv)
    shown = {"\t": "tab", ",": "comma", ";": "semicolon", "|": "pipe"}
    for p in csv:
        if p.encoding != enc:
            yield finding(p.name, f"the encoding is {p.encoding}; most files are {enc}")
        if p.separator != sep:
            yield finding(p.name, f"the separator is a {shown.get(p.separator, p.separator)}; "
                                  f"most files use a {shown.get(sep, sep)}")


@rule("D003", SCOPE,
      severity="warning",
      title="File has a column the template does not know",
      fix="If the column is wanted, add it to the template and update; otherwise ignore it (it becomes a nullable column)")
def extra_column(s: Subject):
    """A file has a column the template or the saved answers do not know."""
    ctx: DriftContext = s.extra
    for part in ctx.multi.parts:
        for col in ctx.facts().get(part.name, {}).get("free", []):
            yield finding(f"{part.name}: {col}", "the column is not in the template or the saved answers")


@rule("D004", SCOPE,
      severity="warning",
      title="Mapped column is missing and a similar one is new",
      fix="If it is the same column renamed, rename it back in the file or map the field to it; a union keeps both names as separate columns")
def likely_rename(s: Subject):
    """A mapped column is missing and a new column has a similar name."""
    ctx: DriftContext = s.extra
    for part in ctx.multi.parts:
        for old, new, kind in ctx.facts().get(part.name, {}).get("pairs", []):
            if kind == "similar":
                yield finding(f"{part.name}: {old}", f"the column is missing and {_quote(new)} looks like it renamed (similar name)")


@rule("D005", SCOPE,
      severity="warning",
      title="Mapped column differs only in case, spaces or punctuation",
      fix="Use the exact spelling in the file; Tableau is thought to treat the two spellings as different columns")
def spelling_only_rename(s: Subject):
    """A mapped column is missing and a column differs from it only in case, spaces or punctuation."""
    ctx: DriftContext = s.extra
    for part in ctx.multi.parts:
        for old, new, kind in ctx.facts().get(part.name, {}).get("pairs", []):
            if kind == "spelling":
                yield finding(f"{part.name}: {old}", f"the column is missing and {_quote(new)} differs only in case, "
                                                     "spaces or punctuation")


@rule("D006", SCOPE,
      severity="warning",
      title="Column reads as another type than in most files",
      fix="Clean the odd values in the file, or retype the column; a mixed column becomes text in the merged source")
def type_conflict(s: Subject):
    """A column reads as another type in this file than in most files."""
    ctx: DriftContext = s.extra
    mapped = {r.mapped_to: ctx.fields().get(r.field) for r in ctx.mapping.itertuples() if r.mapped_to}
    merged = {f["name"]: f["datatype"] for f in ctx.multi.merged.fields}
    for col, by_type in ctx.multi.conflicts.items():
        f = mapped.get(col)
        want = (f.get("physical_type") or f["datatype"]) if f else None
        counts = {t: len(names) for t, names in by_type.items()}
        top = max(counts.values())
        leaders = [t for t in counts if counts[t] == top]
        ref = want if want in leaders else merged[col] if merged[col] in leaders else sorted(leaders)[0]
        for t, names in by_type.items():
            if t == ref:
                continue
            bad = want is not None and (want in _NUMERIC or want in _DATES or want == "boolean") and t == "string"
            for name in names:
                yield finding(f"{name}: {col}", f"the column reads as {t}; most files read it as {ref} (merged: {merged[col]})"
                              + (f", and the template field wants {want}" if bad else ""),
                              severity="error" if bad else "warning")


@rule("D007", SCOPE,
      severity="warning",
      title="Excel sheet or header cell differs from the other files",
      fix="Move the header back to the cell the others use, or name the right sheet; a missing sheet leaves the file unread")
def excel_layout(s: Subject):
    """An Excel file lacks the sheet, or its header starts in another cell than in most files."""
    ctx: DriftContext = s.extra
    excel = [p for p in ctx.multi.parts if p.kind == "excel"]
    for p in excel:
        if p.status == "no-sheet":
            yield finding(p.name, p.error, severity="error")
    origin = _common(p.origin for p in excel if p.origin)
    for p in excel:
        if p.origin and p.origin != origin:
            yield finding(p.name, f"the header starts at {p.origin}; most files start at {origin}")


@rule("D008", SCOPE,
      severity="warning",
      title="File has no header or no data rows", fix="Check the export that made the file; an empty file adds no rows")
def empty_file(s: Subject):
    """A file has no header, or a header and no data rows."""
    for p in s.extra.multi.parts:
        if p.status == "empty":
            yield finding(p.name, p.error)


@rule("D009", SCOPE,
      severity="info",
      title="File has the same columns in another order", fix="Nothing to do for a union that matches columns by name; check anything that reads by position")
def column_order(s: Subject):
    """A file has the same columns in another order."""
    ctx: DriftContext = s.extra
    ref = [c for c in ctx.ref_order]
    for p in ctx.multi.parts:
        if p.data is None:
            continue
        shown = [c for c in ref if c in set(p.columns)]
        own = [c for c in p.columns if c in set(ref)]
        if shown != own:
            yield finding(p.name, "the same columns in another order than the saved answers" if ctx.saved_columns
                          else "the same columns in another order than in most files")


@rule("D010", SCOPE,
      severity="info",
      title="File is new, or a file saved earlier is gone", fix="Run `template drift --save-answers` to record the files as they are now")
def files_changed(s: Subject):
    """A file is new, or one the saved answers listed is not here any more."""
    ctx: DriftContext = s.extra
    if not ctx.saved or not ctx.saved.get("files"):
        return

    def key(path: str) -> str:
        p = Path(path)
        if not p.is_absolute() and ctx.base_dir:
            p = Path(ctx.base_dir) / p
        return p.resolve().as_posix()

    saved = {key(f["path"]): f["path"] for f in ctx.saved["files"]}
    here = {Path(p.path).resolve().as_posix(): p.name for p in ctx.multi.parts}
    for k, name in here.items():
        if k not in saved:
            yield finding(name, "the file is new since the saved answers")
    for k, written in saved.items():
        if k not in here:
            yield finding(Path(written).name, "the saved answers list this file and these files do not include it")


@rule("D011", SCOPE,
      severity="error",
      title="File cannot be read", fix="Open the file and re-save it as a plain CSV or .xlsx")
def unreadable_file(s: Subject):
    """A file cannot be read."""
    for p in s.extra.multi.parts:
        if p.status == "unreadable":
            yield finding(p.name, p.error)


# ------------------------------------------------------------------- API --

def check_drift(source, files, answers=None, datasource: Optional[str] = None, sheet: Union[str, int, None] = None,
                only: Optional[Iterable[str]] = None, skip: Iterable[str] = (), max_files: int = MAX_FILES) -> pd.DataFrame:
    """Compare a folder, glob or list of data files with a template (a path or `Template`) or with answers (a path
    or dict), and return the findings (`findings.FINDING_COLUMNS`). `answers=` adds saved answers to a template. The
    frame's `attrs` also hold `files` (how many), `fingerprint` (merged) and `saved_fingerprint` (or None)."""
    ctx = build_context(source, files, answers=answers, datasource=datasource, sheet=sheet, max_files=max_files)
    spec = ctx.multi.pattern
    df = run_rules(Subject(path=spec, extra=ctx), SCOPE, only=only, skip=skip)
    df.attrs.update(files=len(ctx.multi.parts), fingerprint=ctx.multi.fingerprint,
                    saved_fingerprint=ctx.saved_fingerprint)
    return df


def save_union_answers(source, files, output: str, answers=None, datasource: Optional[str] = None,
                       sheet: Union[str, int, None] = None) -> str:
    """Write a copy of the answers with the datasource's `data` block replaced by the multi-file block (kind
    "union", see `MultiSource.block`), paths relative to the new file. Refuses to overwrite. Returns the path."""
    ctx = build_context(source, files, answers=answers, datasource=datasource, sheet=sheet)
    if answers is None and (hasattr(source, "manifest") or _kind_of(os.fspath(source)) != "answers"):
        raise TemplateError("saving needs answers to copy: pass answers= (or answers as the first argument)")
    saved = load_answers(answers if answers is not None else source)
    out = Path(output)
    if out.exists():
        raise FileExistsError(f"{out} exists; refusing to overwrite")
    block = ctx.multi.block(str(out.resolve().parent))
    saved.pop("_base_dir", None)
    name = ctx.entry["name"]
    replaced = False
    for e in saved.get("datasources") or []:
        if e.get("datasource") == name:
            e["data"] = block
            replaced = True
    if saved.get("datasource") == name:
        saved["data"] = block
        replaced = True
    if not replaced:
        raise TemplateError(f"the answers have no entry for datasource {name!r}; nothing to replace, nothing written")
    with open(out, "x", encoding="utf-8") as fh:
        fh.write(json.dumps(saved, indent=2))
    return str(out)


def rules_help() -> str:
    """One line per rule, for the CLI help and the docs."""
    return "\n".join(f"  {r.id}  {r.severity:<8}{r.title}" for r in rules(SCOPE))
