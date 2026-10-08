"""Dashboards table over the real workbooks of `tests/corpus` (skipped when not fetched).

Issue #84: the filter and parameter names must agree with the counts next to them."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from py_tbparse import TwbParser

CORPUS = Path(__file__).parent / "corpus"
FILES = sorted((CORPUS / "files").glob("*.twb")) if (CORPUS / "files").is_dir() else []

pytestmark = pytest.mark.skipif(not FILES, reason="corpus not fetched: python scripts/fetch_corpus.py")


@pytest.fixture(scope="module")
def summaries():
    return [TwbParser(str(p)).get_dashboard_summary() for p in FILES]


def test_counts_match_the_hand_count_over_the_corpus(summaries):
    # counted separately from the code under test: main-layout zones of type-v2/type 'filter' and 'paramctrl'
    assert sum(int(df["filters"].sum()) for df in summaries) == 92
    assert sum(int(df["parameters"].sum()) for df in summaries) == 16
    assert sum(len(df) for df in summaries) == 135


def test_names_and_counts_cannot_drift_apart(summaries):
    named_filters = named_params = 0
    for df in summaries:
        for r in df.to_dict("records"):
            fields = [f for f in r["filter_fields"].split("; ") if f]
            params = [n for n in r["parameter_names"].split("; ") if n]
            assert len(fields) <= r["filters"] and len(params) <= r["parameters"], r["name"]
            assert bool(fields) == bool(r["filters"]), r["name"]
            assert bool(params) == bool(r["parameters"]), r["name"]
            assert len(set(fields)) == len(fields)
            named_filters += len(fields)
            named_params += len(params)
    assert named_filters > 0 and named_params > 0
    assert any("Category" in df["filter_fields"].str.cat() for df in summaries)


def test_image_text_and_web_counts_match_a_separate_count_over_the_corpus(summaries):
    # counted straight from the XML (type-v2/type only), so a feature-flag-only zone is the allowed difference
    from lxml import etree
    want = {"images": 0, "texts": 0, "webs": 0}
    got = {"images": 0, "texts": 0, "webs": 0}
    for path, df in zip(FILES, summaries):
        doc = etree.parse(str(path))
        for col, kind in (("images", "bitmap"), ("texts", "text"), ("webs", "web")):
            want[col] += len(doc.xpath(f"//dashboards/dashboard/zones//zone[@type-v2='{kind}' or @type='{kind}']"))
            got[col] += int(df[col].sum())
    for col in want:
        assert got[col] >= want[col], col
        assert got[col] - want[col] <= 5, col
    assert got["images"] > 0 and got["texts"] > 0 and got["webs"] > 0, got
