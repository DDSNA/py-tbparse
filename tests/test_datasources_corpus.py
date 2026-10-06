"""Datasources table over the real workbooks of `tests/corpus` (skipped when not fetched).

Issue #79: tables of one datasource used to share the datasource's whole field count."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from py_tbparse import TwbParser

CORPUS = Path(__file__).parent / "corpus"
FILES = sorted((CORPUS / "files").glob("*.twb")) if (CORPUS / "files").is_dir() else []

pytestmark = pytest.mark.skipif(not FILES, reason="corpus not fetched: python scripts/fetch_corpus.py")


def _tables():
    for p in FILES:
        ds = TwbParser(str(p)).get_datasources()
        for name, grp in ds.groupby("datasource_name"):
            if len(grp) > 1:
                yield p.name, name, grp


def test_tables_of_one_datasource_no_longer_share_one_field_count():
    multi = list(_tables())
    assert len(multi) >= 15
    differing = 0
    for fname, name, grp in multi:
        assert (grp["field_count"] >= 0).all(), (fname, name)
        if grp["field_count"].nunique() > 1:
            differing += 1
    # before the fix this was 0 of 21 (every table showed the datasource's total)
    assert differing >= 15, differing


def test_superstore_tables_have_their_own_counts():
    p = next(p for p in FILES if p.name.startswith("1230harry__TeamOne_MSc_Group_Project__Brushing_Superstore"))
    ds = TwbParser(str(p)).get_datasources().set_index("datasource")
    assert dict(ds["field_count"]) == {"Orders": 21, "People": 2, "Returns": 2}
