"""Apply one template to every data file in a folder (one workbook per file), with a summary of what happened.

The use case is one dashboard delivered to many customers, branches or months: each file gets its own workbook,
each customer its own parameter values (a sidecar CSV), and a file that does not fit the template is reported
and skipped instead of producing a half-broken workbook. Everything per file is the single-file machinery:
`resolve_apply` (mapping, saved answers, profile), `broken_sheets` and `apply_template`.
"""

from __future__ import annotations

import concurrent.futures
import glob
import os
import warnings
import zipfile
from pathlib import Path
from typing import Iterable, Optional, Union

import pandas as pd
from lxml import etree

from .connections import is_target_file
from .templates import (
    Template,
    TemplateError,
    apply_template,
    broken_sheets,
    load_mapping,
    load_template,
    resolve_apply,
)

DEFAULT_PATTERNS = ("*.csv", "*.tsv", "*.xlsx", "*.xlsm", "*.target.json")
SUMMARY_COLUMNS = ["input", "output", "status", "mapped", "missing", "broken_sheets", "warnings", "error"]
SUMMARY_NAME = "summary.csv"
_SIDECAR_RESERVED = ("file", "sheet")
# what a bad file can raise: it is reported, never allowed to stop the others
_FILE_ERRORS = (TemplateError, ValueError, OSError, KeyError, zipfile.BadZipFile, etree.XMLSyntaxError,
                pd.errors.ParserError)


def read_inputs(path: Union[str, os.PathLike], template: Template) -> dict[str, dict]:
    """The sidecar CSV: one row per data file. `file` names the file (its name, or its path below the folder),
    an optional `sheet` picks an Excel worksheet, and every other column is a parameter caption or a token name of
    the template; an empty cell leaves that parameter or token alone. Returns
    `{file: {"sheet": ..., "params": {...}, "tokens": {...}}}`."""
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    frame.columns = [str(c).strip() for c in frame.columns]
    if "file" not in frame.columns:
        raise TemplateError(f"{Path(path).name} needs a 'file' column; it has: {', '.join(frame.columns) or 'none'}")
    captions = {p["caption"] for p in template.manifest.get("parameters", [])}
    token_names = {t["name"] for t in template.manifest.get("tokens") or []}
    both = sorted(captions & token_names & set(frame.columns))
    if both:
        raise TemplateError(f"{Path(path).name}: column(s) {', '.join(both)} are both a parameter and a token of the "
                            "template, so the column is ambiguous; rename one")
    unknown = [c for c in frame.columns if c not in _SIDECAR_RESERVED and c not in captions and c not in token_names]
    if unknown:
        raise TemplateError(f"{Path(path).name}: column(s) {', '.join(unknown)} are neither parameters nor tokens of the "
                            f"template; it has parameters: {', '.join(sorted(captions)) or 'none'}; tokens: "
                            f"{', '.join(sorted(token_names)) or 'none'} (plus file, sheet)")
    out: dict[str, dict] = {}
    for row in frame.to_dict("records"):
        name = Path(row["file"].strip()).as_posix()
        if not name:
            raise TemplateError(f"{Path(path).name} has a row with no file")
        if name in out:
            raise TemplateError(f"{Path(path).name} lists {name} twice")
        out[name] = {"sheet": row.get("sheet", "").strip() or None,
                     "params": {c: row[c] for c in frame.columns if c in captions and row[c] != ""},
                     "tokens": {c: row[c] for c in frame.columns if c in token_names and row[c] != ""}}
    return out


def _find_inputs(directory: str, patterns: Iterable[str]) -> list[str]:
    """The files matching `patterns`; a `.json` file is taken only if it is a target file (a database table),
    so a stray settings file is not turned into a workbook."""
    paths: list[str] = []
    for pattern in patterns:
        paths.extend(glob.glob(os.path.join(glob.escape(directory), pattern)))
    return sorted(p for p in set(paths) if not p.lower().endswith(".json") or is_target_file(p))


def _output_names(paths: list[str], prefix: str, output_dir: Path) -> dict[str, Path]:
    """`<prefix>_<stem>.twbx` for each input; the same stem under two extensions (a.csv, a.xlsx) gets a number."""
    taken: dict[str, int] = {}
    names: dict[str, Path] = {}
    for path in paths:
        stem = Path(path).stem
        if stem.endswith(".target"):
            stem = stem[: -len(".target")]
        taken[stem] = taken.get(stem, 0) + 1
        suffix = "" if taken[stem] == 1 else f"_{taken[stem]}"
        names[path] = output_dir / f"{prefix}_{stem}{suffix}.twbx"
    return names


_TEMPLATES: dict[tuple, Template] = {}


def _template(path: str) -> Template:
    """A worker loads the template once, not for every file (the key changes if the file does)."""
    stat = os.stat(path)
    key = (path, stat.st_mtime_ns, stat.st_size)
    if key not in _TEMPLATES:
        _TEMPLATES.clear()
        _TEMPLATES[key] = load_template(path)
    return _TEMPLATES[key]


def _apply_one(job: dict) -> dict:
    """One file: the row of the summary. Never raises for a bad file."""
    row = {"input": os.path.basename(job["path"]), "output": "", "status": "error", "mapped": 0, "missing": 0,
           "broken_sheets": "", "warnings": "", "error": ""}
    notes: list[str] = []
    try:
        template = _template(job["template"])
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            plan = resolve_apply(template, job["path"], mapping=job["mapping"], params=job["params"],
                                 datasource=job["datasource"], answers=job["answers"], profile=job["profile"],
                                 sheet=job["sheet"], experimental=job["experimental"], tokens=job["tokens"])
        notes += [str(w.message) for w in caught]
        notes += [f"saved mapping for {f} no longer fits" for f in plan.stale]
        if plan.changed:
            notes.append("columns differ from the answers' last run")
        entry = plan.entry
        required = [f for f in entry["fields"] if f["required"]]
        mapped = plan.mapping[plan.mapping["mapped_to"] != ""]["field"]
        mapped_required = [f for f in required if f["name"] in set(mapped)]
        row["mapped"] = len(mapped)
        row["missing"] = len(required) - len(mapped_required)
        broken = broken_sheets(template, plan.mapping, datasource=entry["name"])
        row["broken_sheets"] = "; ".join(sorted({s for cell in broken["sheets"] for s in cell.split("; ") if s}))
        share = len(mapped_required) / len(required) if required else 1.0
        if job["min_mapped"] is None and row["missing"]:
            raise TemplateError("no column for required field(s) " + ", ".join(
                f.get("caption") or f["name"].strip("[]") for f in required if f not in mapped_required))
        if job["min_mapped"] is not None and share < job["min_mapped"]:
            row["status"] = "skipped"
            row["error"] = (f"only {len(mapped_required)} of {len(required)} required fields map "
                            f"({share:.0%}, needs {job['min_mapped']:.0%})")
            row["warnings"] = "; ".join(notes)
            return row
        out = apply_template(template, plan.data, mapping=plan.mapping, params=plan.params,
                             output_path=job["output"], datasource=entry["name"],
                             allow_missing=job["min_mapped"] is not None, overwrite=job["overwrite"],
                             answers=job["answers"], profile=job["profile"], experimental=job["experimental"], tokens=plan.tokens)
        row.update(output=os.path.basename(out), status="ok")
    except FileExistsError as e:
        row.update(status="skipped", error=f"{e} (pass overwrite to replace it)")
    except _FILE_ERRORS as e:
        row["error"] = str(e)
    row["warnings"] = "; ".join(notes)
    return row


def apply_template_folder(
    template: Union[Template, str],
    directory: str,
    output_dir: Optional[str] = None,
    patterns: Iterable[str] = DEFAULT_PATTERNS,
    mapping: Union[str, os.PathLike, pd.DataFrame, None] = None,
    params: Optional[dict[str, str]] = None,
    answers: Union[str, os.PathLike, dict, None] = None,
    profile: Optional[str] = None,
    sheet: Union[str, int, None] = None,
    inputs: Union[str, os.PathLike, None] = None,
    datasource: Optional[str] = None,
    min_mapped: Optional[float] = None,
    on_error: str = "skip",
    overwrite: bool = False,
    workers: int = 1,
    summary_path: Union[str, os.PathLike, bool, None] = None,
    experimental: bool = False,
    tokens: Optional[dict[str, str]] = None,
) -> pd.DataFrame:
    """Make one workbook per data file in `directory` from `template`; return the summary, one row per file.

    Columns: `input`, `output`, `status` (`ok`, `skipped` or `error`), `mapped` (columns matched), `missing`
    (required fields with no column), `broken_sheets` (sheets that would break), `warnings`, `error`. The
    same table is written as `summary.csv` beside the outputs (`summary_path=False` to skip, or a path).

    Each file is matched on its own (`mapping=` applies one edited mapping to all; `answers=` uses saved
    choices as the prior and suggests only for the rest). By default a file whose required fields do not all
    find a column is skipped: no half-broken workbook. `min_mapped=0.9` instead writes any file where at least
    that share of required fields map, and reports the sheets that break. `params` apply to every file; the
    `inputs` sidecar CSV (see `read_inputs`) gives each file its own parameter values, token values and Excel sheet.
    `tokens` fills the template's `{{tokens}}` for every file.
    Outputs are `<template>_<file stem>.twbx` in `output_dir` (default `DIR/out`), never overwritten unless
    `overwrite`. `on_error="stop"` raises `TemplateError` at the first file that is not `ok`. `workers` above 1
    uses that many processes (at most the CPU count); files are independent, so the result is the same.
    A `*.target.json` file (see `connections.load_target`) is a database table: one workbook per target, so one
    template serves many customers on one database (a different `dbname` or `schema` in each file).
    """
    if on_error not in ("skip", "stop"):
        raise ValueError("on_error must be 'skip' or 'stop'")
    if min_mapped is not None and not 0 <= min_mapped <= 1:
        raise ValueError("min_mapped is a share between 0 and 1")
    if not Path(directory).is_dir():
        raise FileNotFoundError(f"no such folder: {directory}")
    template_path = template.path if isinstance(template, Template) else str(template)
    loaded = template if isinstance(template, Template) else load_template(template_path)
    sidecar = read_inputs(inputs, loaded) if inputs else {}
    out_dir = Path(output_dir) if output_dir else Path(directory) / "out"
    summary = (out_dir / SUMMARY_NAME) if summary_path in (None, True) else (Path(summary_path) if summary_path else None)
    if summary is not None and summary.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite {summary} (pass overwrite)")
    paths = _find_inputs(directory, patterns)
    frame_mapping = load_mapping(mapping) if mapping is not None else None
    prefix = Path(template_path).name
    for suffix in (".template.twbx", ".twbx"):
        if prefix.lower().endswith(suffix):
            prefix = prefix[: -len(suffix)]
            break
    names = _output_names(paths, prefix, out_dir)
    known = {Path(p).name for p in paths} | {Path(os.path.relpath(p, directory)).as_posix() for p in paths}
    rows: list[dict] = [{"input": name, "output": "", "status": "skipped", "mapped": 0, "missing": 0, "broken_sheets": "",
                         "warnings": "", "error": "listed in the inputs file but not in the folder"}
                        for name in sidecar if name not in known]
    out_dir.mkdir(parents=True, exist_ok=True)
    jobs = []
    for path in paths:
        extra = sidecar.get(Path(path).name) or sidecar.get(Path(os.path.relpath(path, directory)).as_posix()) or {}
        jobs.append({
            "path": path, "template": template_path, "output": str(names[path]), "mapping": frame_mapping,
            "params": {**(params or {}), **extra.get("params", {})}, "datasource": datasource, "answers": answers,
            "tokens": {**(tokens or {}), **extra.get("tokens", {})},
            "profile": profile, "sheet": extra.get("sheet") or sheet, "min_mapped": min_mapped, "overwrite": overwrite,
            "experimental": experimental,
        })
    workers = max(1, min(int(workers), os.cpu_count() or 1, len(jobs) or 1))
    if workers > 1 and on_error == "skip":
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(_apply_one, jobs))
    else:
        results = []
        for job in jobs:
            result = _apply_one(job)
            results.append(result)
            if on_error == "stop" and result["status"] != "ok":
                rows += results
                if summary is not None:
                    pd.DataFrame(rows, columns=SUMMARY_COLUMNS).to_csv(summary, index=False)
                raise TemplateError(f"{result['input']}: {result['error']}")
    rows += results
    table = pd.DataFrame(rows, columns=SUMMARY_COLUMNS)
    if summary is not None:
        table.to_csv(summary, index=False)
    return table
