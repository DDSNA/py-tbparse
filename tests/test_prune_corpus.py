"""Prune over the 200 real workbooks of `tests/corpus` (skipped when not fetched): with every option on it must
not raise, the output must re-parse, schema errors must not increase, nothing it removed may still be an A001,
A005 or A006 finding, no field it removed may still be named anywhere, no missing reference may appear, and
a second prune must be a no-op."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from schema_check import new_schema_errors

from py_tbparse import TwbParser, audit, prune

CORPUS = Path(__file__).parent / "corpus"
FILES = sorted((CORPUS / "files").glob("*.twb")) if (CORPUS / "files").is_dir() else []

pytestmark = pytest.mark.skipif(not FILES, reason="corpus not fetched: python scripts/fetch_corpus.py")


def test_every_workbook_prunes_cleanly_and_a_second_prune_does_nothing(tmp_path):
    total = {"calculations": 0, "parameters": 0, "sheets": 0}
    for i, path in enumerate(FILES):
        out, again = tmp_path / f"{i}.twb", tmp_path / f"{i}b.twb"
        report = prune(str(path), str(out), sheets=True)
        for k, v in report["counts"].items():
            total[k] += v
        TwbParser(str(out))
        assert new_schema_errors(str(path), str(out)) == [], path.name
        after = audit(str(out), only=["A001", "A003", "A005", "A006"])
        gone = {r["object"] for r in report["removed"]}
        assert not gone & set(after["object"]), path.name
        before_a003 = audit(str(path), only=["A003"])
        assert len(after[after["rule"] == "A003"]) <= len(before_a003), path.name
        new = out.read_text(encoding="utf-8")
        for r in report["removed"]:
            if r["category"] != "sheets":
                assert "columns" in r["traces"], path.name
                assert f"[{r['name'][1:-1]}]" not in new, (path.name, r["name"])
        second = prune(str(out), str(again), sheets=True)
        assert second["removed"] == [], path.name
        assert out.read_bytes() == again.read_bytes(), path.name
    assert total["calculations"] > 100 and total["parameters"] > 0 and total["sheets"] > 0, total
