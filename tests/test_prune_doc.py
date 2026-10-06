"""`prune_doc` (a parsed document, in place) and `datasources=True` (WP14c). Synthetic workbooks come from
`test_audit.workbook`; the corpus smoke test is in `test_prune_doc_corpus.py`."""

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from test_audit import workbook

from py_tbparse import TwbParser, prune, prune_doc
from py_tbparse.cli import main

SECOND = ("<datasource name='ds2' caption='Other'><connection class='textscan' directory='Data' filename='b.csv'/>"
          "</datasource>")
EMPTY_PARAMS = "<datasource name='Parameters' hasconnection='false'></datasource>"


def two_ds(tmp_path, **kw):
    """ds1 (used by Sheet 1 on Dash) plus ds2, used only by Sheet 2, which is on no dashboard."""
    path = workbook(tmp_path, sheets={"Sheet 1": ["[Sales]"], "Sheet 2": ["[Sales]"]},
                    dashboards={"Dash": ["Sheet 1"]}, **kw)
    p = Path(path)
    t = p.read_text(encoding="utf-8")
    t = t.replace("<datasource name='Parameters'", SECOND + "<datasource name='Parameters'", 1)
    # Sheet 2 uses ds2
    i = t.index("<worksheet name='Sheet 2'")
    t = t[:i] + t[i:].replace("name='ds1'", "name='ds2'").replace("datasource='ds1'", "datasource='ds2'", 1)
    p.write_text(t, encoding="utf-8")
    return str(p)


def ds_names(doc):
    return doc.xpath("/workbook/datasources/datasource/@name")


def test_prune_doc_works_in_place_on_a_parsed_document(tmp_path):
    path = workbook(tmp_path, calcs=[("[Calculation_1]", "Margin", "[Sales] - [Profit]")])
    parser = TwbParser(path)
    doc = copy.deepcopy(parser.xml_doc)
    report = prune_doc(doc)
    assert [r["object"] for r in report["removed"]] == ["Orders: Margin"]
    assert "Calculation_1" not in str(doc.xpath("string(/workbook)")) and not doc.xpath("//column[@name='[Calculation_1]']")
    assert parser.xml_doc.xpath("//column[@name='[Calculation_1]']")          # the copy was changed, not the parser
    assert set(report) == {"removed", "kept", "counts", "traces"}
    assert "datasources" not in report["counts"]
    # the root element works too, and a second run is a no-op
    assert prune_doc(doc.getroot())["removed"] == []


def test_prune_doc_matches_prune(tmp_path):
    path = workbook(tmp_path, calcs=[("[Calculation_1]", "Margin", "[Sales] - [Profit]")], params=[("[Parameter 1]", "P")],
                    sheets={"Sheet 1": ["[Sales]"], "Sheet 2": ["[Sales]"]})
    a = prune(path, sheets=True)
    b = prune_doc(copy.deepcopy(TwbParser(path).xml_doc), sheets=True)
    for k in ("removed", "kept", "counts", "traces"):
        assert a[k] == b[k]


def test_unused_datasource_goes_after_its_sheet_is_pruned(tmp_path):
    path = two_ds(tmp_path)
    doc = copy.deepcopy(TwbParser(path).xml_doc)
    report = prune_doc(doc, sheets=True, datasources=True)
    assert [r["object"] for r in report["removed"] if r["category"] == "datasources"][0] in ("Other", "Parameters")
    assert "ds2" not in ds_names(doc) and "ds1" in ds_names(doc)
    assert report["counts"]["datasources"] == len([r for r in report["removed"] if r["category"] == "datasources"])
    assert report["counts"]["sheets"] == 1
    assert prune_doc(doc, sheets=True, datasources=True)["removed"] == []


def test_a_datasource_a_kept_sheet_uses_stays(tmp_path):
    path = two_ds(tmp_path)
    doc = copy.deepcopy(TwbParser(path).xml_doc)
    report = prune_doc(doc, datasources=True)            # no sheets=True: Sheet 2 stays, so ds2 stays
    assert "ds2" in ds_names(doc)
    assert any(k["object"] == "Other" and "still named by" in k["reason"] for k in report["kept"])


def test_a_datasource_named_by_an_action_or_dependency_stays(tmp_path):
    path = two_ds(tmp_path)
    t = Path(path).read_text(encoding="utf-8")
    t = t.replace("<windows>", "<actions><action name='A'><source datasource='ds2'/></action></actions><windows>", 1)
    Path(path).write_text(t, encoding="utf-8")
    doc = copy.deepcopy(TwbParser(path).xml_doc)
    report = prune_doc(doc, sheets=True, datasources=True)
    assert "ds2" in ds_names(doc)
    assert any(k["object"] == "Other" and "action" in k["reason"] for k in report["kept"])


def test_parameters_datasource_is_kept_unless_empty_and_unnamed(tmp_path):
    with_param = workbook(tmp_path, params=[("[Parameter 1]", "P")], name="a.twb",
                          texts=["<x>[Parameters].[Parameter 1]</x>"])
    doc = copy.deepcopy(TwbParser(with_param).xml_doc)
    report = prune_doc(doc, datasources=True)
    assert "Parameters" in ds_names(doc)
    assert any(k["object"] == "Parameters" for k in report["kept"])

    # its last parameter is unused and goes; then the empty datasource nothing names goes with it
    unused = workbook(tmp_path, params=[("[Parameter 1]", "P")], name="b.twb")
    doc = copy.deepcopy(TwbParser(unused).xml_doc)
    assert prune_doc(doc)["counts"]["parameters"] == 1
    assert "Parameters" in ds_names(doc)                                # default: stays, as before
    prune_doc(doc, datasources=True)
    assert ds_names(doc) == ["ds1"]

    # an empty Parameters datasource that a sheet still names stays
    named = workbook(tmp_path, name="c.twb", texts=["<x>[Parameters].[Parameter 9]</x>"])
    doc = copy.deepcopy(TwbParser(named).xml_doc)
    prune_doc(doc, datasources=True)
    assert "Parameters" in ds_names(doc)


def test_the_last_real_datasource_is_never_removed(tmp_path):
    path = workbook(tmp_path, sheets={"Sheet 1": []}, dashboards={})
    t = Path(path).read_text(encoding="utf-8").replace("<datasource name='ds1'/>", "")
    t = t.replace("<datasource-dependencies datasource='ds1'></datasource-dependencies>", "")
    Path(path).write_text(t, encoding="utf-8")
    doc = copy.deepcopy(TwbParser(path).xml_doc)
    report = prune_doc(doc, datasources=True)
    assert "ds1" in ds_names(doc)
    assert any("last datasource" in k["reason"] for k in report["kept"])


def test_default_prune_is_unchanged_and_datasources_is_opt_in(tmp_path):
    path = two_ds(tmp_path)
    out = tmp_path / "o.twb"
    report = prune(path, str(out), sheets=True)
    assert "datasources" not in report["counts"] and "ds2" in out.read_text(encoding="utf-8")
    out2 = tmp_path / "o2.twb"
    report = prune(path, str(out2), sheets=True, datasources=True)
    assert "datasources" in report["counts"]
    text = out2.read_text(encoding="utf-8")
    assert "ds2" not in text and "ds1" in text
    TwbParser(str(out2))


def test_cli_datasources_flag(tmp_path, capsys):
    path = two_ds(tmp_path)
    assert main(["prune", path, "--sheets", "--datasources", "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["datasources"] >= 1
    assert main(["prune", path, "--sheets"]) == 0
    assert "datasource" not in capsys.readouterr().out.splitlines()[-2]
