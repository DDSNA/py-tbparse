"""Workbook loading and .twbx archive helpers.

Ports of `twbx_list`, `extract_twb_from_twbx`, `twbx_extract_files`, and the
`.twbx_classify` logic from R/utils.R.
"""

from __future__ import annotations

import datetime as _dt
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd
from lxml import etree

_WORKBOOK_EXT = {"twb"}
_EXTRACT_EXT = {"hyper", "tde"}
_IMAGE_EXT = {"png", "jpg", "jpeg", "gif", "svg"}
_TEXT_EXT = {"csv", "txt", "tsv"}
_EXCEL_EXT = {"xlsx", "xls"}


def _classify(name: str) -> str:
    """Port of `.twbx_classify`."""
    ext = Path(name).suffix.lower().lstrip(".")
    if ext in _WORKBOOK_EXT:
        return "workbook"
    if ext in _EXTRACT_EXT:
        return "extract"
    if ext in _IMAGE_EXT:
        return "image"
    if ext in _TEXT_EXT:
        return "text"
    if ext in _EXCEL_EXT:
        return "excel"
    return "other"


def twbx_list(twbx_path: str) -> pd.DataFrame:
    """Port of `twbx_list()`. Lists the contents of a .twbx archive."""
    if not twbx_path or not os.path.exists(twbx_path):
        raise FileNotFoundError(f"File not found: {twbx_path}")

    rows = []
    with zipfile.ZipFile(twbx_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            modified = _dt.datetime(*info.date_time)
            rows.append(
                {
                    "name": info.filename,
                    "size_bytes": float(info.file_size),
                    "modified": modified,
                    "type": _classify(info.filename),
                }
            )
    return pd.DataFrame(rows, columns=["name", "size_bytes", "modified", "type"])


def extract_twb_from_twbx(
    twbx_path: str,
    extract_dir: Optional[str] = None,
    extract_all: bool = False,
) -> dict:
    """Port of `extract_twb_from_twbx()`.

    Extracts the largest `.twb` member (or the whole archive) from a
    `.twbx` file. Returns a dict with `twb_path`, `exdir`, `twbx_path`,
    and `manifest`.
    """
    if not twbx_path or not os.path.exists(twbx_path):
        raise FileNotFoundError(f"File not found: {twbx_path}")

    manifest = twbx_list(twbx_path)
    twb_rows = manifest[manifest["type"] == "workbook"].sort_values(
        "size_bytes", ascending=False
    )
    if twb_rows.empty:
        raise ValueError("No .twb file found inside .twbx")

    twb_rel = twb_rows.iloc[0]["name"]

    if extract_dir is None:
        stamp = _dt.datetime.now().strftime("%Y%m%d%H%M%S")
        stem = Path(twbx_path).stem
        extract_dir = os.path.join(tempfile.gettempdir(), f"twbx_{stem}_{stamp}")

    os.makedirs(extract_dir, exist_ok=True)
    with zipfile.ZipFile(twbx_path) as zf:
        if extract_all:
            zf.extractall(extract_dir)
        # extract() sanitizes '..'/absolute segments out of `name` before
        # writing, and returns the *actual* destination path -- computing
        # it ourselves via os.path.join(extract_dir, twb_rel) would
        # silently diverge from where the file really landed for a member
        # name like "../../evil.twb". Calling it again when extract_all
        # already wrote this same member is redundant I/O but harmless
        # (identical bytes), and keeps this one code path authoritative.
        twb_path = zf.extract(twb_rel, extract_dir)

    return {
        "twb_path": twb_path,
        "exdir": extract_dir,
        "twbx_path": os.path.abspath(twbx_path),
        "manifest": manifest,
    }


def twbx_extract_files(
    twbx_path: str,
    files: Optional[Iterable[str]] = None,
    pattern: Optional[str] = None,
    types: Optional[Iterable[str]] = None,
    exdir: Optional[str] = None,
) -> pd.DataFrame:
    """Port of `twbx_extract_files()`."""
    import re as _re

    if not twbx_path or not os.path.exists(twbx_path):
        raise FileNotFoundError(f"File not found: {twbx_path}")

    man = twbx_list(twbx_path)
    sel = man
    if types is not None:
        sel = sel[sel["type"].isin(list(types))]
    if pattern is not None:
        sel = sel[sel["name"].str.contains(pattern, regex=True, na=False)]
    if files is not None:
        sel = sel[sel["name"].isin(list(files))]

    if sel.empty:
        return pd.DataFrame(columns=["name", "out_path", "type"])

    if exdir is None:
        stamp = _dt.datetime.now().strftime("%Y%m%d%H%M%S")
        exdir = os.path.join(tempfile.gettempdir(), f"twbx_extract_{stamp}")
    os.makedirs(exdir, exist_ok=True)

    with zipfile.ZipFile(twbx_path) as zf:
        # extract() returns the sanitized destination path -- see the
        # comment in extract_twb_from_twbx() for why os.path.join(exdir, n)
        # would diverge from it for a member name containing '..'.
        out_paths = [zf.extract(name, exdir) for name in sel["name"]]

    return pd.DataFrame(
        {
            "name": sel["name"].tolist(),
            "type": sel["type"].tolist(),
            "out_path": out_paths,
        }
    )


def load_workbook_xml(path: str) -> etree._ElementTree:
    """Load a .twb/.twbx path into a parsed lxml ElementTree."""
    ext = Path(path).suffix.lower().lstrip(".")
    if ext == "twbx":
        info = extract_twb_from_twbx(path, extract_all=False)
        twb_path = info["twb_path"]
    elif ext == "twb":
        twb_path = path
    else:
        raise ValueError(f"Unsupported file type: {ext}")

    if not os.path.exists(twb_path):
        raise FileNotFoundError(f"File not found: {twb_path}")

    return etree.parse(str(twb_path))
