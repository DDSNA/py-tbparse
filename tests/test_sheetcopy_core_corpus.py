"""WP14b smoke test over the 200 real workbooks of `tests/corpus` (skipped when the corpus is not fetched; the
corpus is gitignored and never committed). Core invariants only, nothing is written and nothing is opened in
Tableau:

* the closure of every worksheet is computed without an error;
* a sheet compared with its own workbook has nothing to add, no clash and no missing field;
* renaming the datasource prefix away and back restores the sheet XML exactly;
* an identity rewrite changes nothing, and a copy of a sheet gets all-new uuids;
* two datasources with the same connection and the same internal name in two workbooks match.
"""

import sys
from pathlib import Path

import pytest
from lxml import etree

sys.path.insert(0, str(Path(__file__).parent))

from py_tbparse import TwbParser  # noqa: E402
from py_tbparse.sheetcopy_core import (  # noqa: E402
    SheetCopyError, compare_to_target, connection_signature, copy_sheet_element, dependency_closure,
    match_datasource, rewrite_references, sheet_datasources,
)
from py_tbparse.templates import _non_parameter_datasources  # noqa: E402

CORPUS = Path(__file__).parent / "corpus"
FILES = sorted((CORPUS / "files").glob("*.twb")) if (CORPUS / "files").is_dir() else []

pytestmark = pytest.mark.skipif(not FILES, reason="corpus not fetched: python scripts/fetch_corpus.py")

# Sheets whose own workbook leaves a name unresolved are reported, not failed: Tableau files are not always
# self-consistent (see the WP14a research, 15 names no datasource has).


def test_closure_self_compare_and_roundtrip():
    sheets = unresolved = 0
    for path in FILES:
        doc = TwbParser(str(path)).xml_doc
        taken = set(doc.xpath("//simple-id/@uuid"))
        for ws in doc.xpath("/workbook/worksheets/worksheet[@name]"):
            name = ws.get("name")
            used = sheet_datasources(doc, name)
            if len(used) != 1:
                continue
            ds_name = used[0]
            if not doc.xpath("/workbook/datasources/datasource[@name=$n]", n=ds_name):
                continue
            sheets += 1
            c = dependency_closure(doc, name)
            unresolved += bool(c.unresolved)
            res = compare_to_target(doc, c, doc)
            assert not res["add"] and not res["clash"] and not res["blocked"], (path.name, name, res)
            assert set(res["missing"]) <= set(), (path.name, name, res["missing"])

            original = etree.tostring(ws, with_tail=False)
            elem = copy_sheet_element(doc, name, None, set(taken))
            assert etree.tostring(elem, with_tail=False) != original or not ws.xpath(".//simple-id"), (path.name, name)
            assert rewrite_references(etree.fromstring(original)) == 0
            there = etree.fromstring(original)
            rewrite_references(there, {ds_name: "zzz.moved"}, captions={ds_name: "Moved"})
            assert ds_name not in etree.tostring(there, encoding="unicode"), (path.name, name)
            rewrite_references(there, {"zzz.moved": ds_name})
            for node in there.iter("datasource"):
                if node.get("name") == ds_name and node.get("caption") == "Moved":
                    node.set("caption", ws.xpath(".//datasource[@name=$n]/@caption", n=ds_name)[0])
            assert etree.tostring(there, with_tail=False) == original, (path.name, name)
    assert sheets > 400
    print(f"{sheets} single-datasource sheets, {unresolved} with unresolved names")


def test_same_connection_same_name_matches_across_workbooks():
    by_sig: dict = {}
    for path in FILES:
        doc = TwbParser(str(path)).xml_doc
        for ds in _non_parameter_datasources(doc):
            sig = connection_signature(ds)
            if sig[0]:
                by_sig.setdefault((sig, ds.get("name")), []).append((path, doc))
    pairs = 0
    for (sig, name), group in by_sig.items():
        for (_, a), (_, b) in zip(group, group[1:]):
            same = [d for d in _non_parameter_datasources(b) if connection_signature(d) == sig]
            if len(same) != 1:
                continue
            pairs += 1
            assert match_datasource(a, name, b) == name
    print(f"{pairs} same-connection same-name pairs")
    with pytest.raises(SheetCopyError):
        match_datasource(a, name, b, explicit="no such datasource")
