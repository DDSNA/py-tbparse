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
_NON_ALNUM = re.compile(r"[\W_]+")  # keeps letters and digits of any script (赛前排名, über), drops the rest


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


def _drop_parameters(df: pd.DataFrame) -> pd.DataFrame:
    if "is_parameter" in df.columns:
        return df[~df["is_parameter"].fillna(False).astype(bool)]
    return df


def _reference_names(reference) -> list[str]:
    if reference is None:
        return []
    if isinstance(reference, (str, os.PathLike)):
        # A path to the "before" workbook. (Iterating a str would yield single
        # characters as names.)
        reference = TwbParser(str(reference))
    if isinstance(reference, TwbParser):
        reference = reference.get_fields()
    if isinstance(reference, pd.DataFrame):
        reference = _drop_parameters(reference)
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
    reference: Union[pd.DataFrame, TwbParser, str, Iterable[str], None] = None,
    style: str = "title",
    fuzzy_cutoff: float = 0.85,
    acronyms: Iterable[str] = DEFAULT_ACRONYMS,
    only_changed: bool = False,
    datasource: Union[str, Iterable[str], None] = None,
) -> pd.DataFrame:
    """Propose a clean name for every (non-parameter) field.

    `fields` is a `TwbParser` or its `get_fields()` frame. `reference`, if
    given, is the "before" schema: another `TwbParser`, a path to its workbook,
    a fields frame, or a plain list of names. A field whose spelling-insensitive key matches a
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

    df = _drop_parameters(fields)

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


KINDS = ("field", "parameter", "worksheet", "dashboard", "datasource", "folder", "hierarchy")
OBJECT_COLUMNS = ["kind"] + RENAME_COLUMNS

# A datasource Tableau names itself (`federated.0grg...`) and nobody captioned:
# not something a person sees, so not worth a suggestion.
_OPAQUE_DATASOURCE = re.compile(r"^[a-z]+\.[0-9a-z]{20,}$")
# Worksheets and dashboards share one namespace in Tableau.
_SHEET_SCOPE = ""


def _inventory(parser: TwbParser) -> dict[str, list[dict]]:
    """Every renameable object of each non-field kind, straight from the XML.

    Records are `{datasource, name, current}`: `name` is what the XML calls
    it (a sheet's name, a datasource's internal name), `current` what the
    person sees (a caption when there is one)."""
    doc = parser.xml_doc
    inv: dict[str, list[dict]] = {k: [] for k in KINDS if k != "field"}
    for kind, path in (("worksheet", "/workbook/worksheets/worksheet"), ("dashboard", "/workbook/dashboards/dashboard")):
        for el in doc.xpath(f"{path}[@name]"):
            inv[kind].append({"datasource": _SHEET_SCOPE, "name": el.get("name"), "current": el.get("name")})
    for ds in doc.xpath("/workbook/datasources/datasource[@name]"):
        dsname, caption = ds.get("name"), ds.get("caption")
        if dsname == "Parameters":
            for col in ds.xpath("./column[@name]"):
                inv["parameter"].append({
                    "datasource": dsname, "name": col.get("name"),
                    "current": col.get("caption") or col.get("name").strip("[]"),
                })
            continue
        if caption or not _OPAQUE_DATASOURCE.match(dsname):
            inv["datasource"].append({"datasource": _SHEET_SCOPE, "name": dsname, "current": caption or dsname})
        for kind, path in (
            ("folder", "./folder[@name]|./folders-common/folder[@name]"),
            ("hierarchy", "./drill-paths/drill-path[@name]"),
        ):
            seen = set()
            for el in ds.xpath(path):
                if el.get("name") not in seen:
                    seen.add(el.get("name"))
                    inv[kind].append({"datasource": dsname, "name": el.get("name"), "current": el.get("name")})
    return inv


def _reference_inventory(reference) -> Optional[dict[str, list[dict]]]:
    """Per-kind names of the reference workbook, or None when it can only
    speak for fields (a name list or a fields frame)."""
    if isinstance(reference, (str, os.PathLike)):
        reference = TwbParser(str(reference))
    return _inventory(reference) if isinstance(reference, TwbParser) else None


def suggest_renames(
    parser: TwbParser,
    reference: Union[pd.DataFrame, TwbParser, str, Iterable[str], None] = None,
    kinds: Union[str, Iterable[str]] = KINDS,
    style: str = "title",
    fuzzy_cutoff: float = 0.85,
    acronyms: Iterable[str] = DEFAULT_ACRONYMS,
    only_changed: bool = False,
    datasource: Union[str, Iterable[str], None] = None,
) -> pd.DataFrame:
    """Suggest clean names for everything in a report, not just fields.

    `kinds` picks what to cover (default all): `field`, `parameter`,
    `worksheet`, `dashboard`, `datasource`, `folder`, `hierarchy`. Each kind
    is treated like `suggest_field_renames` treats fields: a `reference`
    workbook (a `TwbParser` or a path) lends its spelling to objects of the
    same kind that match it, everything else is tidied by `normalize_name`,
    and two objects in one namespace never get the same name (worksheets and
    dashboards share one namespace; folders and hierarchies are per
    datasource). A reference that is only a name list or fields frame applies
    to fields alone.

    `datasource` limits the datasource-scoped kinds (field, folder,
    hierarchy and the datasource itself) to that internal name or names.

    Returns `kind, datasource, name, current, suggested, reason, score,
    changed`; `datasource` is blank for worksheets, dashboards and
    datasources.
    """
    wanted = (kinds,) if isinstance(kinds, str) else tuple(kinds)
    unknown = [k for k in wanted if k not in KINDS]
    if unknown:
        raise ValueError(f"unknown kind(s) {', '.join(map(repr, unknown))}; choose from {', '.join(KINDS)}")
    opts = dict(style=style, fuzzy_cutoff=fuzzy_cutoff, acronyms=acronyms)
    frames, extra = [], []
    if "field" in wanted:
        fr = suggest_field_renames(parser, reference=reference, datasource=datasource, **opts)
        # Parameters are their own kind, however the extractor flags them.
        frames.append(fr[fr["datasource"] != "Parameters"].assign(kind="field"))

    inv = _inventory(parser)
    ref_inv = _reference_inventory(reference)
    only_ds = None if datasource is None else ({datasource} if isinstance(datasource, str) else set(datasource))

    def run(kind_group: tuple, scope_of=lambda r: r["datasource"]):
        records = []
        for k in kind_group:
            for r in inv[k]:
                if only_ds is not None and k in ("folder", "hierarchy") and r["datasource"] not in only_ds:
                    continue
                if only_ds is not None and k == "datasource" and r["name"] not in only_ds:
                    continue
                records.append({**r, "kind": k})
        if not records:
            return
        frame = pd.DataFrame([
            {"datasource": scope_of(r), "name": f"[{r['name']}]", "caption": r["current"], "is_parameter": False}
            for r in records
        ])
        ref_names = None
        if ref_inv is not None:
            ref_names = [r["current"] for k in kind_group for r in ref_inv[k]]
        sugg = suggest_field_renames(frame, reference=ref_names, **opts)
        kind_of = {(scope_of(r), r["name"]): r for r in records}
        for row in sugg.to_dict("records"):
            rec = kind_of[(row["datasource"], row["name"][1:-1])]
            extra.append({**row, "kind": rec["kind"], "datasource": rec["datasource"], "name": rec["name"]})

    if "parameter" in wanted:
        run(("parameter",))
    sheets = tuple(k for k in ("worksheet", "dashboard") if k in wanted)
    if sheets:
        run(sheets, scope_of=lambda r: _SHEET_SCOPE)
    if "datasource" in wanted:
        run(("datasource",), scope_of=lambda r: _SHEET_SCOPE)
    for k in ("folder", "hierarchy"):
        if k in wanted:
            run((k,))

    if extra:
        frames.append(pd.DataFrame(extra))
    frames = [f for f in frames if not f.empty]
    out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=OBJECT_COLUMNS)
    out = out[OBJECT_COLUMNS]
    order = {k: i for i, k in enumerate(KINDS)}
    out = out.sort_values("kind", key=lambda s: s.map(order), kind="stable").reset_index(drop=True)
    if only_changed:
        out = out[out["changed"].astype(bool)].reset_index(drop=True)
    return out


def load_rename_mapping(source: Union[str, os.PathLike, pd.DataFrame]) -> pd.DataFrame:
    """Read an edited rename mapping (a CSV path or a frame) back in.

    The mapping is what `py-tbparse rename -f csv` prints, with the
    `suggested` column edited by hand. Only `datasource`, `name` and
    `suggested` are needed; a blank `suggested` means "leave this field
    alone". Your edits are taken as given, so a `conflict` row you filled in
    is applied. Two rows may not give the same name within one datasource.
    Returns a frame that `build_renamed_workbook` / `apply_field_renames`
    accept.
    """
    if isinstance(source, pd.DataFrame):
        df = source.copy()
    else:
        df = pd.read_csv(source, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    df.columns = [str(c).strip() for c in df.columns]
    missing = [c for c in ("datasource", "name", "suggested") if c not in df.columns]
    if missing:
        raise ValueError(f"mapping is missing column(s): {', '.join(missing)}")
    for col, default in (("current", ""), ("reason", ""), ("kind", "field")):
        if col not in df.columns:
            df[col] = default
    rows = []
    for rec in df.to_dict("records"):
        kind = "field" if is_missing(rec["kind"]) or not str(rec["kind"]).strip() else str(rec["kind"]).strip()
        if kind not in KINDS:
            raise ValueError(f"unknown kind {kind!r} in mapping; choose from {', '.join(KINDS)}")
        ds, name = rec["datasource"], rec["name"]
        suggested = "" if is_missing(rec["suggested"]) else str(rec["suggested"]).strip()
        if is_missing(name) or not str(name).strip():
            continue
        ds = "" if is_missing(ds) else str(ds)
        if not ds and kind in ("field", "parameter", "folder", "hierarchy"):
            continue
        current = "" if is_missing(rec["current"]) else str(rec["current"])
        changed = bool(suggested) and suggested != current
        if not suggested:
            suggested = current
        rows.append({
            "kind": kind, "datasource": ds, "name": name, "current": current, "suggested": suggested,
            "reason": "from mapping" if changed else "unchanged", "score": None, "changed": changed,
        })
    out = pd.DataFrame(rows, columns=OBJECT_COLUMNS)
    taken: dict = {}
    for r in out[out["changed"]].to_dict("records"):
        group = "sheet" if r["kind"] in ("worksheet", "dashboard") else r["kind"]
        slot = (group, r["datasource"], r["suggested"].lower())
        if slot in taken and taken[slot] != r["name"]:
            where = f" in {r['datasource']}" if r["datasource"] else ""
            raise ValueError(
                f"{r['suggested']!r} is the new name of both {taken[slot]} and {r['name']}{where}"
            )
        taken[slot] = r["name"]
    return out


SCHEMA_COLUMNS = ["side", "datasource", "name", "closest"]


def compare_field_schemas(
    fields: Union[pd.DataFrame, TwbParser],
    reference: Union[pd.DataFrame, TwbParser, str, Iterable[str]],
    datasource: Union[str, Iterable[str], None] = None,
    **kwargs,
) -> pd.DataFrame:
    """Which fields have no counterpart across a datasource switch.

    These are the ones that stay broken after Replace Data Source, because
    the new source has nothing to take the place of the old field (or the
    other way round). Fields are compared after `suggest_field_renames`, so
    `ORDER_ID` in the new source matches `Order ID` in the old.

    Returns `side, datasource, name, closest`: `side` is `old only` (a
    reference field nothing in the new source matches; `datasource` blank)
    or `new only` (a new field nothing in the reference matches). `closest`
    is the most similar name on the other side, as a hint for a typo that
    the cutoff was too strict for. Extra keyword arguments (`style`,
    `fuzzy_cutoff`, ...) go to `suggest_field_renames`.
    """
    ref_names = _reference_names(reference)
    sugg = suggest_field_renames(fields, reference=ref_names, datasource=datasource, **kwargs)
    ref_keys = {_match_key(n): n for n in ref_names}
    new_keys = {_match_key(s) for s in sugg["suggested"]}
    rows = []
    for r in sugg.to_dict("records"):
        if _match_key(r["suggested"]) not in ref_keys:
            rows.append({"side": "new only", "datasource": r["datasource"], "name": r["current"],
                         "closest": _closest(r["suggested"], ref_names)})
    new_names = list(sugg["suggested"])
    for n in ref_names:
        if _match_key(n) not in new_keys:
            rows.append({"side": "old only", "datasource": "", "name": n,
                         "closest": _closest(n, new_names)})
    return pd.DataFrame(rows, columns=SCHEMA_COLUMNS)


def _closest(name: str, candidates: list[str]) -> str:
    keys = {_match_key(c): c for c in candidates}
    hit = difflib.get_close_matches(_match_key(name), list(keys), n=1, cutoff=0.5)
    return keys[hit[0]] if hit else ""


def applicable_renames(renames: pd.DataFrame) -> pd.DataFrame:
    if renames is None or renames.empty:
        return pd.DataFrame(columns=RENAME_COLUMNS)
    keep = renames["changed"].astype(bool) & (renames["reason"] != "conflict")
    return renames[keep]


def rename_id(kind, datasource, name) -> str:
    """The id of one suggested rename, as the GUI and the server both write it: kind, datasource and
    name joined by the unit separator (U+001F), which a Tableau name never contains. A missing kind means
    a field, a missing datasource means none."""
    kind = "field" if is_missing(kind) or not kind else kind
    return "\x1f".join((str(kind), "" if is_missing(datasource) else str(datasource), "" if is_missing(name) else str(name)))


def select_renames(renames: pd.DataFrame, exclude=None) -> pd.DataFrame:
    """`renames` without the rows named in `exclude`, a list of `rename_id()` strings.

    Only a rename that would be applied (changed, not a conflict) can be left out; any other id is an error,
    so a stale or mistyped request cannot pass unnoticed. Leaving every rename out is an error too. Sheets
    and dashboards share one namespace, so the result is refused if leaving one out would make two of them
    end up with the same name. No ids (None or empty) returns `renames` unchanged.
    """
    if exclude is None:
        return renames
    if not isinstance(exclude, list) or not all(isinstance(x, str) for x in exclude):
        raise ValueError("exclude must be a list of rename ids (strings)")
    if not exclude:
        return renames
    todo = applicable_renames(renames)
    known = {rename_id(r.get("kind"), r["datasource"], r["name"]) for r in todo.to_dict("records")}
    unknown = sorted(set(exclude) - known)
    if unknown:
        shown = ", ".join(repr(u.replace("\x1f", " / ")) for u in unknown[:3])
        raise ValueError(
            f"{len(unknown)} of the excluded ids {'is' if len(unknown) == 1 else 'are'} not one of the suggested renames "
            f"({shown}). Reload the suggestions and try again."
        )
    gone = set(exclude)
    if known <= gone:
        raise ValueError("Every rename is left out, so there is nothing to apply. Tick at least one rename.")
    out = renames[[rename_id(r.get("kind"), r["datasource"], r["name"]) not in gone for r in renames.to_dict("records")]]
    _check_sheet_names(out)
    return out


def _check_sheet_names(renames: pd.DataFrame) -> None:
    final: dict[str, str] = {}
    for r in renames.to_dict("records"):
        if r.get("kind") not in ("worksheet", "dashboard"):
            continue
        new = r["suggested"] if r["changed"] and r["reason"] != "conflict" else r["name"]
        if new in final and final[new] != r["name"]:
            raise ValueError(
                f"Leaving out a rename would give two sheets or dashboards the name {new!r}. "
                "Leave out the other one as well, or keep every rename."
            )
        final[new] = r["name"]


def _insert_column(ds_el, col) -> None:
    """Put a new `<column>` after the datasource's last column (else after its aliases, else its connection)."""
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
    _insert_column(ds_el, col)
    return col


def _caption_column(doc, ds: str, name: str, caption: str) -> bool:
    """Set the caption of a field or parameter, creating the column when the
    field only exists physically, and update the captions worksheets cache."""
    ds_els = doc.xpath("/workbook/datasources/datasource[@name=$ds]", ds=ds)
    if not ds_els:
        return False
    cols = ds_els[0].xpath("./column[@name=$n]", n=name)
    if not cols:
        cols = [_new_column(ds_els[0], name, caption)]
    for col in cols:
        col.set("caption", caption)
    for col in doc.xpath(
        "//datasource-dependencies[@datasource=$ds]/column[@name=$n and @caption]", ds=ds, n=name
    ):
        col.set("caption", caption)
    return True


def _rename_datasource(doc, name: str, caption: str) -> bool:
    """A datasource is renamed by its caption; the internal name that fields,
    sheets and dependencies refer to stays."""
    els = doc.xpath("/workbook/datasources/datasource[@name=$n]", n=name)
    if not els:
        return False
    els[0].set("caption", caption)
    # Sheets list the datasources they use, with the caption once it has one.
    for el in doc.xpath("/workbook/worksheets//datasources/datasource[@name=$n]", n=name):
        el.set("caption", caption)
    return True


def _rename_in_datasource(doc, kind: str, ds: str, name: str, new: str) -> bool:
    """Rename a folder or hierarchy (drill path) of one datasource, including
    the copies of a hierarchy that worksheets keep in their dependencies."""
    if kind == "folder":
        paths = ["./folder[@name=$n]", "./folders-common/folder[@name=$n]"]
    else:
        paths = ["./drill-paths/drill-path[@name=$n]"]
    ds_els = doc.xpath("/workbook/datasources/datasource[@name=$ds]", ds=ds)
    if not ds_els:
        return False
    hits = [el for p in paths for el in ds_els[0].xpath(p, n=name)]
    if kind == "hierarchy":
        hits += doc.xpath(
            "//datasource-dependencies[@datasource=$ds]/drill-paths/drill-path[@name=$n]", ds=ds, n=name
        )
    for el in hits:
        el.set("name", new)
    return bool(hits)


# Every place a worksheet or dashboard name is written. Sheet names are unique
# across both kinds, so matching on the value is safe.
_SHEET_REFERENCES = (
    ("worksheet", "name"), ("dashboard", "name"), ("window", "name"), ("thumbnail", "name"),
    ("zone", "name"), ("zone", "worksheet"), ("viewpoint", "name"), ("exclude-sheet", "name"),
    ("source", "worksheet"), ("source", "dashboard"), ("story-point", "captured-sheet"),
)
_SHEET_PARAMS = ("target", "sheet", "worksheet")  # <param name=...> of goto-sheet actions


def _rename_sheet_references(doc, sheet_map: dict[str, str]) -> None:
    if not sheet_map:
        return
    for el in doc.iter():
        if not isinstance(el.tag, str):
            continue
        for attr in [a for t, a in _SHEET_REFERENCES if t == el.tag]:
            value = el.get(attr)
            if value in sheet_map:
                el.set(attr, sheet_map[value])
        if el.tag == "param" and el.get("name") in _SHEET_PARAMS and el.get("value") in sheet_map:
            el.set("value", sheet_map[el.get("value")])


def build_renamed_workbook(parser: TwbParser, renames: pd.DataFrame, report: Optional[dict] = None) -> bytes:
    """Bytes of a copy of `parser`'s workbook with `renames` applied.

    Each changed row of `renames` (as returned by `suggest_field_renames` or
    `suggest_renames`; conflicts are skipped) is applied by its `kind`
    (default `field`). A field or parameter gets the `caption` of its Tableau
    column, which is how Tableau itself renames one; a datasource gets a
    caption too; a worksheet or dashboard is renamed everywhere it is
    written (the sheet, its window, thumbnail, dashboard zones, actions and
    story points); a folder or hierarchy gets its new name. Formulas
    and sheets refer to the internal `name`, so nothing breaks. A field that
    only exists as a physical column gets a new minimal `<column>` element.
    Captions that worksheets cache in `datasource-dependencies` are updated
    too. A `.twb` gives `.twb` bytes; a `.twbx` gives a `.twbx` with every
    other member copied across untouched.

    If `report` is a dict it receives `applied` (objects renamed, with
    `by_kind` counts) and `skipped` (rows whose target was not found).
    """
    doc = copy.deepcopy(parser.xml_doc)
    applied = skipped = 0
    by_kind: dict[str, int] = {}
    sheet_map: dict[str, str] = {}
    for r in applicable_renames(renames).to_dict("records"):
        kind = r.get("kind")
        kind = "field" if is_missing(kind) or not kind else kind
        ds, name, new = r["datasource"], r["name"], r["suggested"]
        ds = "" if is_missing(ds) else ds
        if is_missing(name):
            ok = False
        elif kind in ("worksheet", "dashboard"):
            tag = "worksheets/worksheet" if kind == "worksheet" else "dashboards/dashboard"
            ok = bool(doc.xpath(f"/workbook/{tag}[@name=$n]", n=name))
            if ok:
                sheet_map[name] = new
        elif kind == "datasource":
            ok = _rename_datasource(doc, name, new)
        elif kind in ("folder", "hierarchy"):
            ok = _rename_in_datasource(doc, kind, ds, name, new)
        else:  # field, parameter
            ok = bool(ds) and _caption_column(doc, ds, name, new)
        if ok:
            applied += 1
            by_kind[kind] = by_kind.get(kind, 0) + 1
        else:
            skipped += 1
    _rename_sheet_references(doc, sheet_map)
    if report is not None:
        report.update(applied=applied, skipped=skipped, by_kind=by_kind)
    return _serialize_workbook(parser, doc)


def _serialize_workbook(parser: TwbParser, doc) -> bytes:
    """Bytes of `doc` in the source's format: `.twb` bytes, or a `.twbx` with every other member copied
    across untouched."""
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
    (`reference`, `style`, ...), or to `suggest_renames` when `kinds` is given. The original is never modified: the output
    defaults to `<name>_renamed.<ext>` beside it, must keep the source's
    extension, and an existing file is only replaced with `overwrite=True`.
    """
    if renames is None:
        # `kinds=` widens the rename from fields to everything in the report.
        suggest = suggest_renames if "kinds" in kwargs else suggest_field_renames
        renames = suggest(parser, **kwargs)
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
