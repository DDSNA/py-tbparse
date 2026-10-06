"""`slice` over the corpus (skipped when `tests/corpus/files` is missing): for every workbook with two or more
dashboards, keep the first one. No exception, the result re-parses, schema errors and A003 do not rise, no new
integrity problem, every kept dashboard's zones resolve, and a second slice is a no-op. The corpus is never
committed."""

import copy
import sys
from pathlib import Path

import pytest
from lxml import etree

sys.path.insert(0, str(Path(__file__).parent))

from schema_check import new_schema_errors

from py_tbparse import SliceError, TwbParser, audit, slice_doc

CORPUS = Path(__file__).parent / "corpus"
FILES = sorted((CORPUS / "files").glob("*.twb")) if (CORPUS / "files").is_dir() else []

pytestmark = pytest.mark.skipif(not FILES, reason="corpus not fetched: python scripts/fetch_corpus.py")


def test_corpus_slice(tmp_path):
    done = dropped_actions = removed_sheets = 0
    for i, path in enumerate(FILES):
        parser = TwbParser(str(path))
        dashboards = parser.xml_doc.xpath("/workbook/dashboards/dashboard/@name")
        if len(dashboards) < 2:
            continue
        doc = copy.deepcopy(parser.xml_doc)
        try:
            r = slice_doc(doc, [dashboards[0]])
        except SliceError:                              # an empty story shows no worksheet
            continue
        done += 1
        dropped_actions += len(r["dropped_actions"])
        removed_sheets += len(r["removed_sheets"])
        assert r["integrity_new"] == [], (path.name, r["integrity_new"])
        assert r["kept_dashboards"] and dashboards[0] in r["kept_dashboards"]
        out = tmp_path / f"{i}.twb"
        out.write_bytes(etree.tostring(doc, encoding="utf-8", xml_declaration=True))
        TwbParser(str(out))
        assert new_schema_errors(str(path), str(out)) == [], path.name
        assert len(audit(str(out), only=["A003"])) <= len(audit(str(path), only=["A003"])), path.name
        again = slice_doc(copy.deepcopy(doc), r["kept_dashboards"])
        assert again["removed_dashboards"] == [] and again["removed_sheets"] == [], path.name
        assert again["dropped_actions"] == [] and again["prune"]["removed"] == [], path.name
    assert done > 0
    print(f"sliced {done} workbooks; {removed_sheets} sheets and {dropped_actions} actions dropped")
