"""Read many data files as one source (WP17b): a glob or a folder of CSV, TSV and Excel files.

Not part of the R package. Each file is read with the single-file machinery (`templates.read_data`'s CSV
rules and `templates._read_excel`), so a column gets the same type here as it would in `template apply`.
What this module adds is the view across files: the merged columns and types, one fingerprint per file and
one for the merge, and the facts a drift report needs per file (encoding, separator, row count, where an
Excel header sits).

Nothing here writes a workbook. The union XML Tableau uses has not been seen in a real file (see the WP17
research), so `template apply` does not take many files yet; `template drift` (`template_drift.py`) is the
pre-flight check that already works.

Type merge rule, per column: the same type everywhere gives that type; integer and real give real; date and
datetime give datetime; a file with no values in the column (no type) agrees with anything; every other mix
gives string, and the column is listed in `MultiSource.conflicts`.
"""

from __future__ import annotations

import codecs
import glob
import os
import re
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Union

import pandas as pd

from .templates import (
    DataSource,
    SheetEmpty,
    SheetMissing,
    TemplateError,
    _SAMPLE_ROWS,
    _infer_csv_type,
    _read_excel,
)

SUPPORTED = (".csv", ".tsv", ".txt", ".xlsx", ".xlsm")
FOLDER_SUFFIXES = (".csv", ".tsv", ".xlsx", ".xlsm")      # what a folder is searched for (as `apply-folder` does)
MAX_FILES = 500
_HEAD_BYTES = 1 << 20
_SEPARATORS = (",", ";", "\t", "|")
_GLOB = re.compile(r"[*?\[]")
_GRID = re.compile(r"^([A-Z]+)(\d+):([A-Z]+)(\d+)$")


@dataclass
class FilePart:
    """One file of a multi-file source and what was read from it. `status` is `ok`, `empty` (no data rows, or
    no header at all), `no-sheet` (the Excel file lacks the sheet asked for) or `unreadable` (`error` says why)."""

    path: str
    name: str                                  # relative to the folder or the glob's fixed part, with `/`
    kind: str                                  # "csv" or "excel"
    status: str = "ok"
    error: str = ""
    data: Optional[DataSource] = None
    encoding: Optional[str] = None             # CSV: utf-8, utf-16 or cp1252 (anything that is not UTF-8 or UTF-16)
    separator: Optional[str] = None            # CSV
    rows: int = 0                              # data rows seen (at most the sample size)
    columns: list = field(default_factory=list)    # in file order
    sheet: Optional[str] = None
    origin: Optional[str] = None               # Excel: the top-left cell of the header, "A1"

    @property
    def fingerprint(self) -> Optional[str]:
        return self.data.fingerprint() if self.data is not None else None

    def types(self) -> dict:
        return {f["name"]: f["datatype"] for f in self.data.fields} if self.data is not None else {}


@dataclass
class MultiSource:
    """Many files read as one source: `parts` in name order, `merged` (a `DataSource` with every column of
    every file), `conflicts` (column -> {type: [file names]}) for the columns whose files disagree on type."""

    pattern: str
    parts: list
    merged: DataSource
    conflicts: dict = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        return self.merged.fingerprint()

    def names(self) -> list:
        return self.merged.names()

    def block(self, base_dir: Optional[str] = None) -> dict:
        """The `data` block of an answers file for this source (`kind` "union"): the pattern, the files with their
        fingerprints (paths relative to `base_dir` when they sit below it) and the merged columns. An answers
        file without it, or with the single-file block, loads as before."""
        def rel(path: str) -> str:
            if base_dir:
                try:
                    return Path(os.path.relpath(path, base_dir)).as_posix()
                except ValueError:       # another drive on Windows
                    pass
            return Path(path).as_posix()

        block = {"kind": "union", "pattern": self.pattern, "schema_fingerprint": self.fingerprint,
                 "columns": self.names(),
                 "files": [{"path": rel(p.path), "fingerprint": p.fingerprint} for p in self.parts]}
        sheets = {p.sheet for p in self.parts if p.sheet}
        if len(sheets) == 1:
            block["sheet"] = sheets.pop()
        return block


# ------------------------------------------------------------ resolving --

def _hidden(path: Path) -> bool:
    return path.name.startswith(("~$", "."))


def resolve_files(spec: Union[str, os.PathLike, Iterable], max_files: int = MAX_FILES) -> tuple[list, str]:
    """The files `spec` names, as `(paths, root)`: `spec` is a folder (its CSV, TSV and Excel files, not its
    subfolders), a glob (`sales/sales_*.csv`, `**` reaches subfolders), one file, or a list of those. Sorted,
    without duplicates, without Excel lock files (`~$x.xlsx`) and hidden files; `root` is what a file's name is
    taken relative to."""
    specs = [spec] if isinstance(spec, (str, os.PathLike)) else list(spec)
    if not specs:
        raise TemplateError("no files given")
    found: dict[str, Path] = {}
    roots: list[Path] = []
    for item in specs:
        text = os.fspath(item)
        p = Path(text)
        if p.is_dir():
            roots.append(p)
            for q in p.iterdir():
                if q.is_file() and q.suffix.lower() in FOLDER_SUFFIXES and not _hidden(q):
                    found[str(q.resolve())] = q
        elif _GLOB.search(text):
            fixed = []
            for part in Path(text).parts:
                if _GLOB.search(part):
                    break
                fixed.append(part)
            roots.append(Path(*fixed) if fixed else Path("."))
            for m in glob.glob(text, recursive=True):
                q = Path(m)
                if q.is_file() and q.suffix.lower() in SUPPORTED and not _hidden(q):
                    found[str(q.resolve())] = q
        elif p.is_file():
            roots.append(p.parent)
            found[str(p.resolve())] = p
        else:
            raise FileNotFoundError(f"no such file or folder: {text}")
    if not found:
        raise TemplateError("no CSV, TSV or Excel file matches " + ", ".join(repr(os.fspath(s)) for s in specs))
    if len(found) > max_files:
        raise TemplateError(f"{len(found)} files match; at most {max_files} are read at once (narrow the pattern, "
                            "or raise max_files)")
    root = Path(os.path.commonpath([str(r.resolve()) for r in roots]))
    return sorted(found.values(), key=lambda q: q.resolve().as_posix()), str(root)


# -------------------------------------------------------------- reading --

def _sniff_encoding(path: Path) -> str:
    with open(path, "rb") as f:
        head = f.read(_HEAD_BYTES)
        whole = len(head) < _HEAD_BYTES
    if head.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return "utf-16"
    try:
        codecs.getincrementaldecoder("utf-8-sig")().decode(head, final=whole)
        return "utf-8"
    except UnicodeDecodeError:
        return "cp1252"


def _sniff_separator(path: Path, encoding: str, suffix: str) -> str:
    with open(path, "rb") as f:
        head = f.read(65536)
    text = head.decode({"utf-8": "utf-8-sig", "utf-16": "utf-16", "cp1252": "latin-1"}[encoding], errors="replace")
    line = next((ln for ln in text.splitlines() if ln.strip()), "")
    line = re.sub(r'"[^"]*"', "", line)
    expected = "\t" if suffix == ".tsv" else ","
    counts = {s: line.count(s) for s in _SEPARATORS}
    best = max(counts.values())
    if best == 0 or counts[expected] == best:
        return expected
    return next(s for s in _SEPARATORS if counts[s] == best)


def _read_csv_part(path: Path, name: str) -> FilePart:
    part = FilePart(path=str(path.resolve()), name=name, kind="csv")
    if path.stat().st_size == 0:
        part.status = "empty"
        part.error = "the file has no content"
        return part
    part.encoding = _sniff_encoding(path)
    part.separator = _sniff_separator(path, part.encoding, path.suffix.lower())
    codec = {"utf-8": "utf-8-sig", "utf-16": "utf-16", "cp1252": "cp1252"}[part.encoding]
    try:
        df = pd.read_csv(path, sep=part.separator, nrows=_SAMPLE_ROWS, encoding=codec)
    except pd.errors.EmptyDataError:
        part.status = "empty"
        part.error = "the file has no header row"
        return part
    except (pd.errors.ParserError, UnicodeError, ValueError) as e:
        part.status = "unreadable"
        part.error = f"not readable as a CSV: {e}"
        return part
    part.columns = [str(c) for c in df.columns]
    part.rows = len(df)
    part.data = DataSource(path=part.path, kind="csv",
                           fields=[{"name": str(c), "datatype": _infer_csv_type(df[c])} for c in df.columns])
    if part.rows == 0:
        part.status = "empty"
        part.error = "the file has a header and no data rows"
    return part


def _read_excel_part(path: Path, name: str, sheet: Union[str, int, None]) -> FilePart:
    part = FilePart(path=str(path.resolve()), name=name, kind="excel")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")        # a repeated header is a warning of the single-file reader
            part.data = _read_excel(path, sheet)
    except SheetMissing as e:
        part.status, part.error = "no-sheet", str(e)
        return part
    except SheetEmpty as e:
        part.status, part.error = "empty", str(e)
        return part
    except TemplateError as e:
        part.status, part.error = "unreadable", str(e)
        return part
    data = part.data
    part.columns = data.names()
    part.sheet = data.sheet
    m = _GRID.match(data.grid or "")
    if m:
        part.origin = f"{m.group(1)}{m.group(2)}"
        part.rows = int(m.group(4)) - int(m.group(2))
    if part.rows <= 0:
        part.rows = 0
        part.status, part.error = "empty", "the sheet has a header and no data rows"
    return part


def read_part(path: Union[str, os.PathLike], name: Optional[str] = None, sheet: Union[str, int, None] = None) -> FilePart:
    """One file of a multi-file source. A file that cannot be read becomes a part with `status` `unreadable`; it
    never raises."""
    p = Path(path)
    name = name or p.name
    try:
        if p.suffix.lower() in (".xlsx", ".xlsm"):
            return _read_excel_part(p, name, sheet)
        return _read_csv_part(p, name)
    except OSError as e:
        return FilePart(path=str(p), name=name, kind="excel" if p.suffix.lower() in (".xlsx", ".xlsm") else "csv",
                        status="unreadable", error=f"cannot read the file: {e.strerror or e}")


# -------------------------------------------------------------- merging --

def merge_types(types: Iterable[Optional[str]]) -> Optional[str]:
    """The type of a column that several files hold (see the module docstring); None when none has values."""
    seen = {t for t in types if t}
    if not seen:
        return None
    if len(seen) == 1:
        return next(iter(seen))
    if seen <= {"integer", "real"}:
        return "real"
    if seen <= {"date", "datetime"}:
        return "datetime"
    return "string"


def merge_parts(parts: list, pattern: str = "") -> MultiSource:
    """Merge the columns and types of already-read parts (the columns in order of first appearance)."""
    order: list[str] = []
    seen: dict[str, list] = {}
    for part in parts:
        if part.data is None:
            continue
        for f in part.data.fields:
            if f["name"] not in seen:
                order.append(f["name"])
                seen[f["name"]] = []
            seen[f["name"]].append((part.name, f["datatype"]))
    conflicts = {}
    fields = []
    for col in order:
        merged = merge_types(t for _, t in seen[col])
        fields.append({"name": col, "datatype": merged})
        by_type: dict[str, list] = {}
        for fname, t in seen[col]:
            if t:
                by_type.setdefault(t, []).append(fname)
        if len(by_type) > 1:
            conflicts[col] = by_type
    kinds = {p.kind for p in parts if p.data is not None}
    kind = next(iter(kinds)) if len(kinds) == 1 else "mixed"
    return MultiSource(pattern=pattern, parts=parts, conflicts=conflicts,
                       merged=DataSource(path=pattern, kind=kind, fields=fields))


def read_many(spec: Union[str, os.PathLike, Iterable], sheet: Union[str, int, None] = None,
              max_files: int = MAX_FILES) -> MultiSource:
    """Read a glob, a folder or a list of CSV, TSV and Excel files as one source: `MultiSource.merged` holds every
    column with its merged type, each part its own fingerprint, `MultiSource.fingerprint` the merged one.
    `sheet` picks the worksheet of every Excel file (a name, or an index from 0)."""
    paths, root = resolve_files(spec, max_files=max_files)
    parts = []
    for p in paths:
        try:
            name = Path(os.path.relpath(p.resolve(), root)).as_posix()
        except ValueError:
            name = p.name
        parts.append(read_part(p, name, sheet))
    text = [os.fspath(spec)] if isinstance(spec, (str, os.PathLike)) else [os.fspath(x) for x in spec]
    return merge_parts(parts, ", ".join(Path(t).as_posix() for t in text))
