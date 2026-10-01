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

import difflib
import re
from typing import Iterable, Optional, Union

import pandas as pd

from ._clean import is_missing
from .parser import TwbParser

STYLES = ("title", "snake", "lower", "keep")

DEFAULT_ACRONYMS = frozenset({"id", "url", "sku", "sql", "uk", "us", "usa", "ssn", "gps", "ip"})

RENAME_COLUMNS = ["datasource", "name", "current", "suggested", "reason", "score", "changed"]

_COPY_SUFFIX = re.compile(r"\s*\(copy\)(\s*\d*)?$", re.IGNORECASE)
# Tableau's de-duplication suffixes: "Order ID (Orders1)" and "Order ID1".
_PAREN_DIGIT_SUFFIX = re.compile(r"\s*\([^()]*\d\)$")
_TRAILING_DIGIT = re.compile(r"(?<=\D)\d$")
_SEPARATORS = re.compile(r"[_\-.\s]+")
_CAMEL_LOWER_UPPER = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_CAMEL_ACRONYM = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")
_NON_ALNUM = re.compile(r"[^0-9a-z]+")


def _words(name: str) -> list[str]:
    name = _CAMEL_LOWER_UPPER.sub(" ", name)
    name = _CAMEL_ACRONYM.sub(" ", name)
    return [w for w in _SEPARATORS.split(name) if w]


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

    Splits on `_`, `-`, `.` and camelCase, drops a `(copy)` suffix, and
    re-cases the words per `style`: `title` (`Order ID`), `snake`
    (`order_id`), `lower` (`order id`) or `keep` (words re-joined with
    spaces, case untouched). Digits are never split off (`CENSUS2020`
    stays one word). Returns `None` for missing or empty input.
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
    return " ".join(w.upper() if w.lower() in known else _capitalize(w) for w in words)


def _strip_dedup_suffix(name: str) -> str:
    s = _COPY_SUFFIX.sub("", name.strip())
    s = _PAREN_DIGIT_SUFFIX.sub("", s)
    return _TRAILING_DIGIT.sub("", s)


def _match_key(name: str) -> str:
    """Spelling-insensitive key: `Order ID (Orders1)`, `ORDER_ID`, `orderId`
    and `order id` all become `orderid`."""
    return _NON_ALNUM.sub("", " ".join(_words(_strip_dedup_suffix(name))).lower())


def _display_name(row) -> Optional[str]:
    for col in ("caption", "field_clean", "name"):
        v = row.get(col)
        if not is_missing(v) and str(v).strip():
            return str(v).strip().strip("[]") if col == "name" else str(v).strip()
    return None


def _tableau_level(recs: list[dict]) -> list[dict]:
    """A datasource lists each field twice: the physical column
    (`MUN_LABEL`) and the Tableau column (`[MUN_LABEL]`, often with a
    caption). Only the latter is what users see and can rename, so drop the
    former wherever the datasource has any bracketed names."""
    def is_bracketed(r):
        return str(r.get("name") or "").startswith("[")

    bracketed = {r.get("datasource") for r in recs if is_bracketed(r)}
    return [r for r in recs if r.get("datasource") not in bracketed or is_bracketed(r)]


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

    Returns `datasource, name, current, suggested, reason, score, changed`.
    `name` is Tableau's internal name, which is what a rename tool needs to
    find the column. Where a datasource has bracketed (Tableau-level) column
    names, the bare physical-column entries are ignored. `score` is the match ratio for reference matches.
    """
    if isinstance(fields, TwbParser):
        fields = fields.get_fields()
    if fields is None or fields.empty:
        return pd.DataFrame(columns=RENAME_COLUMNS)

    ref_names = _reference_names(reference)
    ref_by_key: dict[str, str] = {}
    for n in ref_names:
        ref_by_key.setdefault(_match_key(n), n)
    ref_keys = list(ref_by_key)

    df = fields
    if "is_parameter" in df.columns:
        df = df[~df["is_parameter"].fillna(False).astype(bool)]

    recs = _tableau_level(df.to_dict("records"))

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
        suggested, reason, score = None, "", None
        if key in ref_by_key:
            suggested, reason, score = ref_by_key[key], "matches reference", 1.0
        elif key and ref_keys:
            close = difflib.get_close_matches(key, ref_keys, n=1, cutoff=fuzzy_cutoff)
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
