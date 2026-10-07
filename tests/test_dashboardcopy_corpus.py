"""WP14f smoke test over the real workbooks of `tests/corpus` (skipped when the corpus is not fetched; it is
gitignored and never committed). For every ordered pair of workbooks that have a datasource with the same
connection AND the same internal name, every dashboard of the first is copied into the second with
`on_clash='rename'`:

* no exception, no abort;
* the result re-parses and holds the copied dashboards, each with a window;
* no schema error that neither the source nor the target already had;
* `integrity_check` adds nothing, and A003 (missing references) does not rise;
* every action of the result names sheets and dashboards that exist.

Dashboards the copy refuses (a blend, a field the target lacks...) are counted, not failed. Nothing is opened
in Tableau.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from py_tbparse import TwbParser  # noqa: E402
from py_tbparse.dashboardcopy import build_dashboard_copy  # noqa: E402
from py_tbparse.dashboards import integrity_check  # noqa: E402
from py_tbparse.usage import missing_references  # noqa: E402
from schema_check import schema_errors  # noqa: E402
from test_sheetcopy_corpus import FILES, same_name_pairs  # noqa: E402

pytestmark = pytest.mark.skipif(not FILES, reason="corpus not fetched: python scripts/fetch_corpus.py")


def test_copy_every_dashboard_between_same_name_same_connection_pairs(tmp_path):
    pairs = same_name_pairs()
    assert pairs, "the corpus has no same-name same-connection pair"
    copied = refused = carried = 0
    for a, b in pairs:
        src, dst = TwbParser(str(a)), TwbParser(str(b))
        dashboards = src.xml_doc.xpath("/workbook/dashboards/dashboard/@name")
        if not dashboards:
            continue
        data, rep = build_dashboard_copy(src, dst, dashboards, "rename")
        copied += rep["copied"]
        refused += rep["refused"]
        if not rep["copied"]:
            continue
        out = tmp_path / "o.twb"
        out.write_bytes(data)
        res = TwbParser(str(out))
        names = {r["new_name"] for r in rep["dashboards"] if r["status"] == "copy"}
        assert names <= set(res.xml_doc.xpath("/workbook/dashboards/dashboard/@name")), (a.name, b.name)
        for n in names:
            assert res.xml_doc.xpath("/workbook/windows/window[@class='dashboard'][@name=$n]", n=n), (a.name, n)
        assert not (schema_errors(str(out)) - schema_errors(str(a)) - schema_errors(str(b))), (a.name, b.name)
        before = integrity_check(dst.xml_doc)
        assert [p for p in integrity_check(res.xml_doc) if p not in before] == [], (a.name, b.name)
        assert len(missing_references(res)) <= len(missing_references(dst)), (a.name, b.name)
        known = set(res.xml_doc.xpath("/workbook/worksheets/worksheet/@name | /workbook/dashboards/dashboard/@name"))
        for act in res.xml_doc.xpath("/workbook/actions/action"):
            for ref in act.xpath("./source/@dashboard | ./source/@worksheet | ./command/param[@name='target']/@value"):
                assert ref in known, (a.name, b.name, act.get("name"), ref)
        carried += len(res.xml_doc.xpath("/workbook/actions/action")) - len(dst.xml_doc.xpath("/workbook/actions/action"))
    assert copied > 0
    print(f"{len(pairs)} ordered pairs, {copied} dashboards copied, {refused} refused, {carried} actions carried")
