"""Workbooks for the Slice and copy view's tests (endpoints and browser): a synthetic source with three dashboards,
and a target made from it by slicing, so the copy has something real to add and to clash with."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from test_slice import build  # noqa: E402  (S1..S4, Tip, Lonely, HiddenOnD2; dashboards D1, D2, D3)

from py_tbparse import slice_workbook  # noqa: E402


def make_source(folder: Path) -> str:
    return build(folder, "source.twb")


def make_target(folder: Path, name: str = "target.twb") -> str:
    """The source sliced to D2: it keeps S3, S4 and HiddenOnD2, and Calc A is pruned (nothing uses it), so copying S1
    has to add that calculation, and copying S3 is a name clash."""
    src = build(folder, "_for_target.twb")
    out = folder / name
    slice_workbook(src, ["D2"], str(out))
    return str(out)


def make_many(folder: Path, n: int = 250, name: str = "many.twb") -> str:
    """n worksheets and n dashboards, one sheet each: more than a page of both."""
    from test_slice import DS1, PARAMS, dash, ws
    sheets = "".join(ws(f"Sheet {i:03d}") for i in range(n))
    dashes = "".join(dash(f"Dash {i:03d}", f"Sheet {i:03d}") for i in range(n))
    xml = (f"<?xml version='1.0' encoding='utf-8'?><workbook version='18.1'><datasources>{DS1}{PARAMS}"
           f"</datasources><worksheets>{sheets}</worksheets><dashboards>{dashes}</dashboards></workbook>")
    p = folder / name
    p.write_text(xml, encoding="utf-8")
    return str(p)
