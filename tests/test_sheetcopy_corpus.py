"""WP14e smoke test over the real workbooks of `tests/corpus` (skipped when the corpus is not fetched; it is
gitignored and never committed). For every ordered pair of workbooks that have a datasource with the same
connection AND the same internal name, every worksheet is copied with `on_clash='rename'`:

* no exception, no abort;
* the result re-parses and holds the copied sheets;
* no schema error that neither the source nor the target already had;
* `integrity_check` adds nothing, and A003 (missing references) does not rise.

Sheets the slice refuses (a blend, a field the target lacks...) are counted, not failed. Nothing is opened in
Tableau.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from py_tbparse import TwbParser  # noqa: E402
from py_tbparse.dashboards import integrity_check  # noqa: E402
from py_tbparse.sheetcopy import build_sheet_copy  # noqa: E402
from py_tbparse.sheetcopy_core import connection_signature  # noqa: E402
from py_tbparse.templates import _non_parameter_datasources  # noqa: E402
from py_tbparse.usage import missing_references  # noqa: E402
from schema_check import schema_errors  # noqa: E402

CORPUS = Path(__file__).parent / "corpus"
FILES = sorted((CORPUS / "files").glob("*.twb")) if (CORPUS / "files").is_dir() else []

pytestmark = pytest.mark.skipif(not FILES, reason="corpus not fetched: python scripts/fetch_corpus.py")


def same_name_pairs():
    index: dict = {}
    for f in FILES:
        for ds in _non_parameter_datasources(TwbParser(str(f)).xml_doc):
            sig = connection_signature(ds)
            if sig[0]:
                index.setdefault((ds.get("name"), sig), set()).add(f)
    return sorted({(a, b) for v in index.values() for a in v for b in v if a != b})


def test_copy_every_sheet_between_same_name_same_connection_pairs(tmp_path):
    pairs = same_name_pairs()
    assert pairs, "the corpus has no same-name same-connection pair"
    copied = refused = 0
    for a, b in pairs:
        src, dst = TwbParser(str(a)), TwbParser(str(b))
        sheets = src.xml_doc.xpath("/workbook/worksheets/worksheet/@name")
        data, rep = build_sheet_copy(src, dst, sheets, "rename")
        copied += rep["copied"]
        refused += rep["refused"]
        if not rep["copied"]:
            continue
        out = tmp_path / "o.twb"
        out.write_bytes(data)
        res = TwbParser(str(out))
        names = set(res.xml_doc.xpath("/workbook/worksheets/worksheet/@name"))
        assert {r["new_name"] for r in rep["sheets"] if r["status"] == "copy"} <= names, (a.name, b.name)
        assert not (schema_errors(str(out)) - schema_errors(str(a)) - schema_errors(str(b))), (a.name, b.name)
        before = integrity_check(dst.xml_doc)
        assert [p for p in integrity_check(res.xml_doc) if p not in before] == [], (a.name, b.name)
        assert len(missing_references(res)) <= len(missing_references(dst)), (a.name, b.name)
    assert copied > 0
    print(f"{len(pairs)} ordered pairs, {copied} sheets copied, {refused} refused")
