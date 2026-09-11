"""Batch/folder analysis: run a table across every workbook in a directory.

Not part of the R package, which operates on one workbook at a time --
this is a natural Python-side extension (glob + pandas.concat).
"""

from __future__ import annotations

import glob
import os
import warnings

import pandas as pd

from ._tables import TABLE_SPECS
from .parser import TwbParser

DEFAULT_PATTERNS = ("*.twb", "*.twbx")


def scan_folder(
    directory: str,
    table: str = "overview",
    patterns=DEFAULT_PATTERNS,
    **kwargs,
) -> pd.DataFrame:
    """Run `table` (see `_tables.TABLE_SPECS`) over every `.twb`/`.twbx`
    file in `directory`, concatenating the results with a `workbook`
    column identifying the source file.

    A workbook that fails to load or fails to extract `table` is skipped
    with a warning rather than aborting the whole batch -- one corrupt
    file in a folder of fifty shouldn't block the other forty-nine.
    """
    if table not in TABLE_SPECS:
        raise ValueError(f"unknown table '{table}'")
    getter = TABLE_SPECS[table]

    paths: list[str] = []
    for pattern in patterns:
        paths.extend(glob.glob(os.path.join(directory, pattern)))
    paths = sorted(set(paths))

    if not paths:
        return pd.DataFrame(columns=["workbook"])

    frames = []
    for path in paths:
        try:
            parser = TwbParser(path)
            df = getter(parser, **kwargs)
        except Exception as e:  # noqa: BLE001 - genuinely want to skip any failure
            warnings.warn(f"skipping {path}: {e}")
            continue
        df = df.copy()
        df.insert(0, "workbook", os.path.basename(path))
        frames.append(df)

    if not frames:
        return pd.DataFrame(columns=["workbook"])

    return pd.concat(frames, ignore_index=True)
