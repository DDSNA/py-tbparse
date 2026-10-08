"""`slice` (WP14d): keep selected dashboards, drop the rest. Synthetic workbook below; the corpus smoke test is
in `test_slice_corpus.py`."""

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from py_tbparse import SliceError, TwbParser, slice_doc, slice_workbook
from py_tbparse import slicer
from py_tbparse.cli import main
from py_tbparse.dashboards import integrity_check

DS1 = ("<datasource name='ds1' caption='Orders'><connection class='textscan' directory='Data' filename='a.csv'>"
       "<metadata-records><metadata-record class='column'><local-name>[Sales]</local-name></metadata-record>"
       "</metadata-records></connection>"
       "<column name='[Calc A]' datatype='integer'><calculation class='tableau' formula='[Sales] * 2'/></column>"
       "<column name='[Calc B]' datatype='integer'><calculation class='tableau' formula='[Sales] * 3'/></column></datasource>")
DS2 = ("<datasource name='ds2' caption='Other'><connection class='textscan' directory='Data' filename='b.csv'/>"
       "</datasource>")
PARAMS = ("<datasource name='Parameters' hasconnection='false'><column name='[Parameter 1]' caption='P' "
          "datatype='integer' param-domain-type='range' role='measure' value='1'><calculation class='tableau' "
          "formula='1'/></column></datasource>")


def ws(name, ds="ds1", uses="[Sales]", extra="", filt=""):
    return (f"<worksheet name='{name}'><table><view><datasources><datasource name='{ds}'/></datasources>"
            f"<datasource-dependencies datasource='{ds}'><column name='{uses}'/></datasource-dependencies>{filt}"
            f"</view></table>{extra}</worksheet>")


def dash(name, *zones):
    return (f"<dashboard name='{name}'><zones>"
            + "".join(f"<zone id='{i}' name='{z}'/>" for i, z in enumerate(zones)) + "</zones></dashboard>")


ACTION_FILTER = ("<filter class='categorical' column='[ds1].[Action (Sales)]'><groupfilter function='member' "
                 "xmlns:user='http://www.tableausoftware.com/xml/user' user:ui-action-filter='[Action_1]'/></filter>")


def build(tmp_path, name="wb.twb", actions=None):
    sheets = (ws("S1", uses="[Calc A]", filt=ACTION_FILTER) + ws("S2") + ws("S3", uses="[Calc B]")
              + ws("S4", ds="ds2", uses="[X]") + ws("Tip", extra="") + ws("Lonely", uses="[Sales]")
              + ws("HiddenOnD2", uses="[Sales]"))
    sheets = sheets.replace("<worksheet name='S2'>", "<worksheet name='S2'>", 1)
    # S2 shows the sheet Tip in its tooltip
    sheets = sheets.replace("<worksheet name='S2'><table>",
                            "<worksheet name='S2'><table>", 1).replace(
        "</view></table></worksheet><worksheet name='S3'>",
        "</view></table><layout-options><title><formatted-text><run>&lt;Sheet name=\"Tip\"&gt;</run>"
        "</formatted-text></title></layout-options></worksheet><worksheet name='S3'>", 1)
    dashes = dash("D1", "S1", "S2") + dash("D2", "S3", "S4", "HiddenOnD2") + dash("D3", "S2")
    if actions is None:
        actions = (
            "<action name='[Action_1]' caption='S1 filters S2'><source dashboard='D1' worksheet='S1' type='sheet'/>"
            "<command command='tsc:tsl-filter'><param name='target' value='D1'/><param name='exclude' value='S2,S3'/>"
            "</command></action>"
            "<action name='[Action_2]' caption='S3 filters D1'><source dashboard='D2' worksheet='S3' type='sheet'/>"
            "<command command='tsc:tsl-filter'><param name='target' value='D1'/></command></action>"
            "<action name='[Action_3]' caption='S1 to D2'><source dashboard='D1' worksheet='S1' type='sheet'/>"
            "<command command='tsc:tsl-filter'><param name='target' value='D2'/></command></action>")
    windows = "".join(f"<window class='worksheet' name='{n}'><viewpoints/></window>"
                      for n in ("S1", "S2", "S3", "S4", "Tip", "Lonely"))
    windows += ("<window class='dashboard' name='D1'><viewpoints><viewpoint name='S1'/><viewpoint name='S2'/>"
                "</viewpoints></window><window class='dashboard' name='D2'/><window class='dashboard' name='D3'/>"
                "<window class='worksheet' name='HiddenOnD2' hidden='true'/>")
    thumbs = "".join(f"<thumbnail height='1' name='{n}' width='1'>AAAA</thumbnail>" for n in ("S1", "S3", "D1", "D2"))
    xml = (f"<?xml version='1.0' encoding='utf-8'?><workbook version='18.1'><datasources>{DS1}{DS2}{PARAMS}"
           f"</datasources><actions>{actions}</actions><worksheets>{sheets}</worksheets><dashboards>{dashes}"
           f"</dashboards><windows>{windows}</windows><thumbnails>{thumbs}</thumbnails></workbook>")
    p = tmp_path / name
    p.write_text(xml, encoding="utf-8")
    return str(p)


def doc_of(path):
    return copy.deepcopy(TwbParser(path).xml_doc)


def names(doc, xp):
    return doc.xpath(xp)


def test_keeps_the_dashboard_its_sheets_and_the_tooltip_sheet(tmp_path):
    doc = doc_of(build(tmp_path))
    r = slice_doc(doc, "D1")
    assert r["kept_dashboards"] == ["D1"]
    assert r["kept_sheets"] == ["S1", "S2", "Tip"]            # Tip only through S2's tooltip
    assert names(doc, "/workbook/dashboards/dashboard/@name") == ["D1"]
    assert names(doc, "/workbook/worksheets/worksheet/@name") == ["S1", "S2", "Tip"]
    # windows and thumbnails of what went are gone, including the hidden sheet on the removed dashboard
    assert sorted(names(doc, "/workbook/windows/window/@name")) == ["D1", "S1", "S2", "Tip"]
    assert names(doc, "/workbook/thumbnails/thumbnail/@name") == ["S1", "D1"]
    assert r["integrity_new"] == [] and integrity_check(doc) == []


def test_unknown_names_fail_with_the_valid_ones(tmp_path):
    doc = doc_of(build(tmp_path))
    with pytest.raises(SliceError) as e:
        slice_doc(doc, "D1,Nope")
    assert "'Nope'" in str(e.value) and "'D1', 'D2', 'D3'" in str(e.value)
    with pytest.raises(SliceError):
        slice_doc(doc, [])


def test_actions_that_depend_on_removed_sheets_are_dropped_and_reported(tmp_path):
    doc = doc_of(build(tmp_path))
    r = slice_doc(doc, "D1")
    assert sorted(a["name"] for a in r["dropped_actions"]) == ["[Action_2]", "[Action_3]"]
    assert "target 'D2'" in [a for a in r["dropped_actions"] if a["name"] == "[Action_3]"][0]["reason"]
    assert names(doc, "/workbook/actions/action/@name") == ["[Action_1]"]
    # the exclude list loses S3, which is gone, and keeps S2
    assert names(doc, "//param[@name='exclude']/@value") == ["S2"]
    assert [t["name"] for t in r["trimmed_actions"]] == ["[Action_1]"]


def test_the_filter_an_action_drove_is_dropped_with_the_action(tmp_path):
    doc = doc_of(build(tmp_path, actions=(
        "<action name='[Action_1]' caption='from D2'><source dashboard='D2' worksheet='S3' type='sheet'/>"
        "<command command='tsc:tsl-filter'><param name='target' value='D1'/></command></action>")))
    r = slice_doc(doc, "D1")
    assert r["dropped_filters"] == 1 and not doc.xpath("//filter")
    r2 = slice_doc(doc_of(build(tmp_path, name="again.twb", actions="")), "D1")
    assert r2["dropped_filters"] == 0 and len(doc_of(build(tmp_path, name="x.twb", actions="")).xpath("//filter")) == 1


def test_strict_refuses_and_changes_nothing(tmp_path):
    path = build(tmp_path)
    doc = doc_of(path)
    before = len(doc.xpath("//*"))
    with pytest.raises(SliceError, match="--strict"):
        slice_doc(doc, "D1", strict=True)
    assert len(doc.xpath("//*")) == before
    assert slice_doc(doc_of(build(tmp_path, name="ok.twb", actions="")), "D1", strict=True)["dropped_actions"] == []


def test_prune_removes_what_only_removed_sheets_used(tmp_path):
    doc = doc_of(build(tmp_path))
    r = slice_doc(doc, "D1")
    assert names(doc, "/workbook/datasources/datasource/@name") == ["ds1"]       # ds2 only S4 used
    assert names(doc, "//datasource[@name='ds1']/column/@name") == ["[Calc A]"]  # Calc B only S3 used
    assert not doc.xpath("//datasource[@name='Parameters']")                     # the unused parameter went too
    assert r["prune"]["counts"]["datasources"] == 2


def test_no_prune_keeps_unused_datasources(tmp_path):
    doc = doc_of(build(tmp_path))
    r = slice_doc(doc, "D1", prune=False)
    assert r["prune"] is None
    assert "ds2" in names(doc, "/workbook/datasources/datasource/@name")


def test_second_slice_is_a_no_op(tmp_path):
    doc = doc_of(build(tmp_path))
    slice_doc(doc, "D1")
    snap = copy.deepcopy(doc)
    r = slice_doc(doc, "D1")
    assert r["removed_dashboards"] == [] and r["removed_sheets"] == [] and r["dropped_actions"] == []
    assert r["prune"]["removed"] == []
    from lxml import etree
    assert etree.tostring(doc) == etree.tostring(snap)


def test_two_dashboards_and_comma_names(tmp_path):
    doc = doc_of(build(tmp_path))
    r = slice_doc(doc, ["D1, D2"])
    assert r["kept_dashboards"] == ["D1", "D2"] and "D3" in r["removed_dashboards"]
    assert "HiddenOnD2" in r["kept_sheets"] and "Lonely" in r["removed_sheets"]


def test_a_story_keeps_the_sheets_it_captured(tmp_path):
    path = Path(build(tmp_path))
    t = path.read_text(encoding="utf-8").replace(
        "<dashboard name='D3'><zones><zone id='0' name='S2'/></zones></dashboard>",
        "<dashboard name='D3'><zones><zone id='0' type-v2='flipboard'><flipboard><story-points>"
        "<story-point caption='x' captured-sheet='D2' id='1'/></story-points></flipboard></zone></zones></dashboard>")
    path.write_text(t, encoding="utf-8")
    r = slice_doc(doc_of(str(path)), "D3")
    assert r["kept_dashboards"] == ["D2", "D3"] and "S3" in r["kept_sheets"]


def test_write_dry_run_overwrite_and_input_untouched(tmp_path):
    path = build(tmp_path)
    original = Path(path).read_bytes()
    dry = slice_workbook(path, "D1")
    assert dry["dry_run"] and dry["output"] is None
    out = tmp_path / "out.twb"
    rep = slice_workbook(path, "D1", str(out))
    assert rep["output"] == str(out) and Path(path).read_bytes() == original
    assert TwbParser(str(out)).xml_doc.xpath("/workbook/dashboards/dashboard/@name") == ["D1"]
    with pytest.raises(FileExistsError):
        slice_workbook(path, "D1", str(out))
    with pytest.raises(FileExistsError):
        slice_workbook(path, "D1", path)
    with pytest.raises(SliceError, match="must end in"):
        slice_workbook(path, "D1", str(tmp_path / "out.twbx"))


def test_cli_dry_run_write_json_and_errors(tmp_path, capsys):
    path = build(tmp_path)
    out = tmp_path / "cli.twb"
    assert main(["slice", path, "--dashboards", "D1"]) == 0
    assert "dry run" in capsys.readouterr().out and not out.exists()
    assert main(["slice", path, "-d", "D1", "--write", "-o", str(out), "--format", "json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["kept_dashboards"] == ["D1"] and out.exists()
    assert main(["slice", path, "-d", "Nope"]) == 2
    assert "valid dashboards: 'D1', 'D2', 'D3'" in capsys.readouterr().err
    assert main(["slice", path, "-d", "D1", "--strict"]) == 2
    assert "--strict" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        main(["slice", path, "-d", "D1", "-o", str(out)])


def test_dry_run_and_write_exit_the_same_when_integrity_is_new(tmp_path, capsys, monkeypatch):
    path = build(tmp_path)
    out = tmp_path / "bad.twb"
    real = slicer.integrity_check
    calls = []

    def fake(doc):                      # the first call is the input, the second the sliced result
        calls.append(1)
        found = real(doc)
        if len(calls) % 2 == 0:
            found = found + [{"check": "X", "dashboard": "D1", "detail": "made up", "element": None}]
        return found

    monkeypatch.setattr(slicer, "integrity_check", fake)
    assert main(["slice", path, "-d", "D1"]) == 2
    cap = capsys.readouterr()
    assert "INTEGRITY  X: made up" in cap.out and "would refuse" in cap.err
    assert main(["slice", path, "-d", "D1", "--write", "-o", str(out)]) == 2
    assert not out.exists()


def test_a_selection_with_no_worksheet_is_refused(tmp_path):
    path = Path(build(tmp_path))
    path.write_text(path.read_text(encoding="utf-8").replace(
        "<dashboard name='D3'><zones><zone id='0' name='S2'/></zones></dashboard>",
        "<dashboard name='D3' type='storyboard'><zones/></dashboard>"), encoding="utf-8")
    with pytest.raises(SliceError, match="no worksheet"):
        slice_doc(doc_of(str(path)), "D3")
