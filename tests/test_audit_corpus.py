"""The audit and the data dictionary over the 200 real workbooks of `tests/corpus` (skipped when not fetched).

Run with `-s` to see how many findings each rule gave over the corpus."""

from collections import Counter
from pathlib import Path

import pytest

from py_tbparse import TwbParser, audit, field_usage, workbook_markdown
from py_tbparse.findings import FINDING_COLUMNS
from py_tbparse.usage import missing_references
from py_tbparse.workbook_audit import audit_rule_ids
from test_workbook_docs import table_problems

CORPUS = Path(__file__).parent / "corpus"
FILES = sorted((CORPUS / "files").glob("*.twb")) if (CORPUS / "files").is_dir() else []

pytestmark = pytest.mark.skipif(not FILES, reason="corpus not fetched: python scripts/fetch_corpus.py")


@pytest.fixture(scope="module")
def runs():
    return {p: audit(TwbParser(str(p))) for p in FILES}


def test_no_rule_crashes_and_the_counts_are_reported(runs, record_property):
    counts = Counter()
    for path, df in runs.items():
        assert list(df.columns) == FINDING_COLUMNS
        assert df.attrs["crashed"] == [], (path.name, df.attrs["tracebacks"])
        counts.update(df["rule"])
        assert set(df["rule"]) <= set(audit_rule_ids())
        assert "/home/" not in df.to_string(), path.name
    report = ", ".join(f"{r}={counts.get(r, 0)}" for r in audit_rule_ids())
    record_property("audit_rule_counts", report)
    print(f"\naudit findings over {len(FILES)} workbooks: {report}")
    # rules the corpus can prove: these have real examples in it
    for rule_id in ("A001", "A002", "A003", "A005", "A006", "A007", "A008", "A009"):
        assert counts[rule_id] > 0, rule_id


def test_ordering_is_deterministic(runs):
    for path, df in list(runs.items())[::4]:
        again = audit(TwbParser(str(path)))
        assert df.equals(again), path.name


def test_a003_and_a001_agree_with_the_engines_they_reuse(runs):
    for path, df in list(runs.items())[::3]:
        parser = TwbParser(str(path))
        assert int((df["rule"] == "A003").sum()) == len(missing_references(parser)), path.name
        usage = field_usage(parser)
        calcs = usage[(usage["kind"] == "calculated") & ~usage["used"].astype(bool)]
        assert int((df["rule"] == "A001").sum()) <= len(calcs), path.name


def test_the_dictionary_renders_for_every_workbook_with_valid_tables():
    for path in FILES:
        parser = TwbParser(str(path))
        page = workbook_markdown(parser)
        assert page.startswith("# Data dictionary: "), path.name
        assert table_problems(page) == [], path.name
        assert "\r" not in page, path.name


def test_the_dictionary_is_deterministic_for_a_sample():
    for path in FILES[::10]:
        assert workbook_markdown(TwbParser(str(path)), graph=True) == workbook_markdown(TwbParser(str(path)), graph=True)
