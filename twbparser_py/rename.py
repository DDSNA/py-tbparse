"""Suggest clean field names, e.g. after pointing a workbook at a new datasource.

Not part of the R package. When a datasource is swapped for one whose schema
only partly matches, Tableau keeps working but the new names are often ugly:
`ORDER_ID`, `orderId`, `Order ID (Orders1)`, `Order ID1`, `Sales (copy)`.
`suggest_field_renames` proposes a clean name for each field and, given a
reference (the workbook or field list from before the switch), prefers the
reference's spelling so old and new line up. It only reports; nothing in the
workbook is modified.
"""

from __future__ import annotations

import copy
import difflib
import io
import os
import re
import zipfile
from pathlib import Path
from typing import Iterable, Optional, Union

import pandas as pd
from lxml import etree

from ._clean import is_missing
from .parser import TwbParser

STYLES = ("title", "snake", "lower", "keep")

DEFAULT_ACRONYMS = frozenset({"id", "url", "sku", "sql", "uk", "us", "usa", "ssn", "gps", "ip"})

RENAME_COLUMNS = ["datasource", "name", "current", "suggested", "reason", "score", "changed"]

_COPY_SUFFIX = re.compile(r"\s*\(copy(?:\s*\d+)?\)(\s*\d*)?$", re.IGNORECASE)
# Tableau's de-duplication suffix on a joined table's field: "Order ID (Orders1)".
# The text must start with a non-digit so "Sales (2020)" is not mistaken for one.
_PAREN_DEDUP_SUFFIX = re.compile(r"\s*\(\D[^()]*\d\)$")
_TRAILING_DIGIT = re.compile(r"(?<=\D)\d$")
_IDENTIFIER_SEPARATORS = re.compile(r"[_\-.\s]+")
_PHRASE_SEPARATORS = re.compile(r"[_\s]+")
_CAMEL_LOWER_UPPER = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_CAMEL_ACRONYM = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")
_NON_ALNUM = re.compile(r"[^0-9a-z]+")


def _words(name: str) -> list[str]:
    """Split a name into words. An identifier (no spaces: `orderId`,
    `ORDER_ID`) is split on `_ - .` and camelCase; a phrase that already has
    spaces (`iPhone Units`, `Country/Region`) only on spaces and `_`, so its
    own casing is not misread as camelCase."""
    if re.search(r"\s", name):
        return [w for w in _PHRASE_SEPARATORS.split(name) if w]
    name = _CAMEL_LOWER_UPPER.sub(" ", name)
    name = _CAMEL_ACRONYM.sub(" ", name)
    return [w for w in _IDENTIFIER_SEPARATORS.split(name) if w]


def _capitalize(word: str) -> str:
    """Capitalise the first letter, lowercase the rest (`(Orders1)` stays
    `(Orders1)`, which `str.capitalize` would mangle)."""
    for i, ch in enumerate(word):
        if ch.isalpha():
            return word[:i] + ch.upper() + word[i + 1:].lower()
    return word


def normalize_name(
    name: Optional[str],
    style: str = "title",
    acronyms: Iterable[str] = DEFAULT_ACRONYMS,
) -> Optional[str]:
    """Tidy one field name.

    Splits on `_`, `-`, `.` and camelCase (or, for a name that already has
    spaces, on spaces and `_` only), drops a `(copy)` suffix, and re-cases
    the words per `style`: `title` (`Order ID`), `snake` (`order_id`),
    `lower` (`order id`) or `keep` (words re-joined with spaces, case
    untouched). Digits are never split off (`CENSUS2020` stays one word).

    `title` leaves words that already look deliberate alone, so clean names
    survive: `YTD Sales`, `iPhone Units`, `Country/Region` and `1st Order`
    are unchanged. Only an all-caps name (`MUN_LABEL`, which has no lowercase
    anywhere) or an all-lowercase word is re-cased. Returns `None` for
    missing or empty input.
    """
    if is_missing(name):
        return None
    if style not in STYLES:
        raise ValueError(f"style must be one of {STYLES}, got {style!r}")
    s = _COPY_SUFFIX.sub("", str(name).strip())
    words = _words(s)
    if not words:
        return None
    if style == "keep":
        return " ".join(words)
    if style == "snake":
        return "_".join(w.lower() for w in words)
    if style == "lower":
        return " ".join(w.lower() for w in words)
    known = {a.lower() for a in acronyms}
    shouting = not any(ch.islower() for ch in s)

    def title(w: str) -> str:
        if w.lower() in known:
            return w.upper()
        if shouting or (w.islower() and w[:1].isalpha()):
            return _capitalize(w)
        return w

    return " ".join(title(w) for w in words)


def _strip_dedup_suffix(name: str) -> str:
    """Remove a possible duplicate marker: `(copy)`, `(Table1)`, trailing
    digit. Only a candidate -- callers must confirm the plain name exists
    elsewhere, because `Address Line 2` and `Q1` are legitimate names."""
    s = _COPY_SUFFIX.sub("", name.strip())
    s = _PAREN_DEDUP_SUFFIX.sub("", s)
    return _TRAILING_DIGIT.sub("", s)


def _match_key(name: str, strip_dedup: bool = False) -> str:
    """Spelling-insensitive key: `ORDER_ID`, `orderId` and `order id` all
    become `orderid`. With `strip_dedup`, `Order ID (Orders1)` does too."""
    if strip_dedup:
        name = _strip_dedup_suffix(name)
    return _NON_ALNUM.sub("", " ".join(_words(name)).lower())


def _display_name(row) -> Optional[str]:
    for col in ("caption", "field_clean", "name"):
        v = row.get(col)
        if not is_missing(v) and str(v).strip():
            return str(v).strip().strip("[]") if col == "name" else str(v).strip()
    return None


def _tableau_level(recs: list[dict]) -> list[dict]:
    """One record per field, keyed by its Tableau (bracketed) name.

    A datasource lists a field as a Tableau column (`[MUN_LABEL]`, often with
    a caption) and/or as a bare physical column (`MUN_LABEL`). The physical
    one is dropped when its Tableau column exists; otherwise (a field with
    no custom metadata, typical right after a datasource switch) it is kept
    and given the bracketed name Tableau would use, so it can be renamed too.
    """
    def internal(r):
        n = str(r.get("name") or "")
        return n if n.startswith("[") else f"[{n}]"

    bracketed = {(r.get("datasource"), r["name"]) for r in recs if str(r.get("name") or "").startswith("[")}
    out = []
    for r in recs:
        name = str(r.get("name") or "")
        if not name:
            continue
        if not name.startswith("[") and (r.get("datasource"), internal(r)) in bracketed:
            continue
        out.append({**r, "name": internal(r)})
    return out


def _reference_names(reference) -> list[str]:
    if reference is None:
        return []
    if isinstance(reference, TwbParser):
        reference = reference.get_fields()
    if isinstance(reference, pd.DataFrame):
        if "is_parameter" in reference.columns:
            reference = reference[~reference["is_parameter"].fillna(False).astype(bool)]
        names = [_display_name(r) for r in _tableau_level(reference.to_dict("records"))]
    else:
        names = [str(n) for n in reference]
    seen: dict[str, None] = {}
    for n in names:
        if n and n not in seen:
            seen[n] = None
    return list(seen)


def suggest_field_renames(
    fields: Union[pd.DataFrame, TwbParser],
    reference: Union[pd.DataFrame, TwbParser, Iterable[str], None] = None,
    style: str = "title",
    fuzzy_cutoff: float = 0.85,
    acronyms: Iterable[str] = DEFAULT_ACRONYMS,
    only_changed: bool = False,
    datasource: Union[str, Iterable[str], None] = None,
) -> pd.DataFrame:
    """Propose a clean name for every (non-parameter) field.

    `fields` is a `TwbParser` or its `get_fields()` frame. `reference`, if
    given, is the "before" schema: another `TwbParser`, a fields frame, or a
    plain list of names. A field whose spelling-insensitive key matches a
    reference name takes the reference's exact name (`reason` "matches
    reference"); failing that, the closest reference name above
    `fuzzy_cutoff` (0..1, difflib ratio) is used ("close to reference").
    Otherwise the name is normalised with `normalize_name`, additionally
    dropping Tableau's `1` / `(Table1)` de-duplication suffix when the
    un-suffixed field exists in the same datasource.

    Two fields in one datasource never get the same suggestion: the field
    that is already named that keeps it, otherwise the first wins, and the
    rest stay as they are with `reason` "conflict".

    `datasource` limits the work to one datasource name (or several), e.g.
    the newly added one when the workbook still holds the old source too.

    Returns `datasource, name, current, suggested, reason, score, changed`.
    `name` is Tableau's internal (bracketed) name, which is what a rename
    tool needs to find the column; a field that only exists as a physical
    column gets the bracketed name Tableau would give it. `score` is the
    match ratio for reference matches.

    Matching is conservative about numbers: `Address Line 2` is never turned
    into `Address Line 1`, and a trailing `1` or `(Table1)` is only treated
    as a duplicate marker when the plain name also exists.
    """
    if isinstance(fields, TwbParser):
        fields = fields.get_fields()
    if fields is None or fields.empty:
        return pd.DataFrame(columns=RENAME_COLUMNS)

    if not 0 <= fuzzy_cutoff <= 1:
        raise ValueError(f"fuzzy_cutoff must be between 0 and 1, got {fuzzy_cutoff}")
    ref_by_key: dict[str, str] = {}
    for n in _reference_names(reference):
        ref_by_key.setdefault(_match_key(n), n)
    ref_keys = list(ref_by_key)

    df = fields
    if "is_parameter" in df.columns:
        df = df[~df["is_parameter"].fillna(False).astype(bool)]

    recs = _tableau_level(df.to_dict("records"))
    if datasource is not None:
        wanted = {datasource} if isinstance(datasource, str) else set(datasource)
        recs = [r for r in recs if r.get("datasource") in wanted]

    rows = []
    for rec in recs:
        current = _display_name(rec)
        if current is None:
            continue
        rows.append({"datasource": rec.get("datasource"), "name": rec.get("name"), "current": current})

    siblings: dict = {}
    for r in rows:
        siblings.setdefault(r["datasource"], set()).add(r["current"].lower())

    for r in rows:
        current = r["current"]
        key = _match_key(current)
        stripped = _match_key(current, strip_dedup=True)
        suggested, reason, score = None, "", None
        if key in ref_by_key:
            suggested, reason, score = ref_by_key[key], "matches reference", 1.0
        elif stripped != key and stripped in ref_by_key:
            suggested, reason, score = ref_by_key[stripped], "matches reference", 1.0
        elif key and ref_keys:
            digits = re.findall(r"\d+", key)
            close = [
                k for k in difflib.get_close_matches(key, ref_keys, n=5, cutoff=fuzzy_cutoff)
                if re.findall(r"\d+", k) == digits  # `Address Line 3` is not `Address Line 1`
            ]
            if close:
                suggested = ref_by_key[close[0]]
                reason = "close to reference"
                score = round(difflib.SequenceMatcher(None, key, close[0]).ratio(), 3)
        if suggested is None:
            base = _strip_dedup_suffix(current)
            has_base = base != current and any(
                _match_key(s) == _match_key(base) and s != current.lower()
                for s in siblings[r["datasource"]]
            )
            suggested = normalize_name(base if has_base else current, style, acronyms) or current
            reason = "dedup suffix removed" if has_base else "normalized"
        r["suggested"], r["reason"], r["score"] = suggested, reason, score

    taken: dict = {}
    for r in sorted(rows, key=lambda r: r["suggested"] != r["current"]):
        slot = (r["datasource"], r["suggested"].lower())
        if slot in taken and taken[slot] is not r:
            r["suggested"], r["reason"], r["score"] = r["current"], "conflict", None
            slot = (r["datasource"], r["current"].lower())
            taken.setdefault(slot, r)
        else:
            taken[slot] = r

    for r in rows:
        r["changed"] = r["suggested"] != r["current"]
        if not r["changed"] and r["reason"] != "conflict":
            r["reason"] = "already clean"

    out = pd.DataFrame(rows, columns=RENAME_COLUMNS)
    if only_changed:
        out = out[out["changed"]].reset_index(drop=True)
    return out


def applicable_renames(renames: pd.DataFrame) -> pd.DataFrame:
    if renames is None or renames.empty:
        return pd.DataFrame(columns=RENAME_COLUMNS)
    keep = renames["changed"].astype(bool) & (renames["reason"] != "conflict")
    return renames[keep]


def _new_column(ds_el, name: str, caption: str):
    """Add a Tableau column for a field that so far only exists as a physical
    column, so it can carry a caption. Mirrors what Tableau writes for a
    renamed plain field (datatype from the physical column; numbers become
    quantitative measures, everything else a nominal dimension)."""
    datatype = ds_el.xpath(".//column[@name=$bare]/@datatype", bare=name[1:-1]) or ["string"]
    numeric = datatype[0] in ("integer", "real")
    col = etree.Element(
        "column",
        caption=caption,
        datatype=datatype[0],
        name=name,
        role="measure" if numeric else "dimension",
        type="quantitative" if numeric else "nominal",
    )
    anchor = None
    for tag in ("column", "aliases", "connection"):
        found = ds_el.findall(tag)
        if found:
            anchor = found[-1]
            break
    if anchor is None:
        ds_el.append(col)
    else:
        anchor.addnext(col)
    return col


def build_renamed_workbook(parser: TwbParser, renames: pd.DataFrame, report: Optional[dict] = None) -> bytes:
    """Bytes of a copy of `parser`'s workbook with `renames` applied.

    Each changed row of `renames` (as returned by `suggest_field_renames`;
    conflicts are skipped) sets the `caption` of the matching Tableau column
    in its datasource, which is how Tableau itself renames a field. Formulas
    and sheets refer to the internal `name`, so nothing breaks. A field that
    only exists as a physical column gets a new minimal `<column>` element.
    Captions that worksheets cache in `datasource-dependencies` are updated
    too. A `.twb` gives `.twb` bytes; a `.twbx` gives a `.twbx` with every
    other member copied across untouched.

    If `report` is a dict it receives `applied` (fields renamed) and
    `skipped` (rows whose datasource or column was not found).
    """
    doc = copy.deepcopy(parser.xml_doc)
    applied = skipped = 0
    for r in applicable_renames(renames).to_dict("records"):
        ds, name, caption = r["datasource"], r["name"], r["suggested"]
        if is_missing(name) or is_missing(ds):
            skipped += 1
            continue
        ds_els = doc.xpath("/workbook/datasources/datasource[@name=$ds]", ds=ds)
        if not ds_els:
            skipped += 1
            continue
        cols = ds_els[0].xpath("./column[@name=$n]", n=name)
        if not cols:
            cols = [_new_column(ds_els[0], name, caption)]
        for col in cols:
            col.set("caption", caption)
        for col in doc.xpath(
            "//datasource-dependencies[@datasource=$ds]/column[@name=$n and @caption]", ds=ds, n=name
        ):
            col.set("caption", caption)
        applied += 1
    if report is not None:
        report.update(applied=applied, skipped=skipped)
    twb = etree.tostring(doc, xml_declaration=True, encoding="utf-8")

    if not parser.twbx_path:
        return twb
    out = io.BytesIO()
    with zipfile.ZipFile(parser.twbx_path) as src, zipfile.ZipFile(out, "w") as dst:
        for info in src.infolist():
            data = twb if info.filename == parser.twb_name else src.read(info.filename)
            dst.writestr(info, data, compress_type=info.compress_type)
    return out.getvalue()


def default_renamed_path(parser: TwbParser) -> str:
    """`<original>_renamed.<ext>` next to the source workbook."""
    src = Path(parser.twbx_path or parser.path)
    return str(src.with_name(f"{src.stem}_renamed{src.suffix}"))


def apply_field_renames(
    parser: TwbParser,
    renames: Optional[pd.DataFrame] = None,
    output_path: Optional[str] = None,
    overwrite: bool = False,
    **kwargs,
) -> str:
    """Write a new workbook with the suggested renames applied; return its path.

    `renames` defaults to `suggest_field_renames(parser, **kwargs)`
    (`reference`, `style`, ...). The original is never modified: the output
    defaults to `<name>_renamed.<ext>` beside it, must keep the source's
    extension, and an existing file is only replaced with `overwrite=True`.
    """
    if renames is None:
        renames = suggest_field_renames(parser, **kwargs)
    source = Path(parser.twbx_path or parser.path)
    out = Path(output_path) if output_path else Path(default_renamed_path(parser))
    if out.suffix.lower() != source.suffix.lower():
        raise ValueError(f"output must end in {source.suffix}, got {out.suffix or 'no extension'}")
    if out.exists() and (out.resolve() == source.resolve() or not overwrite):
        raise FileExistsError(f"refusing to overwrite existing file: {out}")
    data = build_renamed_workbook(parser, renames)
    # "xb" refuses a file created since the exists() check, like the GUI does.
    with open(out, "wb" if overwrite else "xb") as fh:
        fh.write(data)
    return str(out)
