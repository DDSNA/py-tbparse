"""WP14f: `dashboard copy`, on small synthetic workbooks. Nothing here opens Tableau."""

import json
import sys
from pathlib import Path

import pytest
from lxml import etree

sys.path.insert(0, str(Path(__file__).parent))

from py_tbparse import TwbParser  # noqa: E402
from py_tbparse import cli  # noqa: E402
from py_tbparse.dashboardcopy import (  # noqa: E402
    SheetCopyAbort, build_dashboard_copy, copy_dashboards, plan_dashboard_copy,
)
from py_tbparse.dashboards import integrity_check  # noqa: E402
from test_sheetcopy import OTHER, names, out_doc, target_text, write  # noqa: E402
from test_sheetcopy_core import DS, PARAMS, SHEET, datasource, workbook  # noqa: E402

SHEET2 = SHEET.replace("Sheet 1", "Sheet 2").replace("11111111-1111-1111-1111-111111111111",
                                                     "44444444-4444-4444-4444-444444444444")
DASH = f"""<dashboard name='Dash'><style/><size maxheight='800' maxwidth='1000' minheight='800' minwidth='1000'/>
<datasources><datasource name='Parameters'/><datasource caption='Orders' name='{DS}'/></datasources>
<datasource-dependencies datasource='{DS}'>
  <column name='[Region]' datatype='string' role='dimension'/>
  <column-instance column='[Region]' derivation='None' name='[none:Region:nk]' pivot='key' type='nominal'/>
</datasource-dependencies>
<datasource-dependencies datasource='Parameters'>
  <column name='[Parameter 1]' datatype='real' role='measure'><calculation class='tableau' formula='2'/></column>
</datasource-dependencies>
<zones><zone h='100000' id='4' type-v2='layout-basic' w='100000' x='0' y='0'>
  <zone h='50000' id='5' name='Sheet 1' w='50000' x='0' y='0'/>
  <zone h='50000' id='6' name='Sheet 2' w='50000' x='50000' y='0'/>
  <zone h='10000' id='7' name='Sheet 1' param='[{DS}].[none:Region:nk]' type-v2='filter' w='10000' x='0' y='50000'/>
  <zone h='10000' id='8' param='[Parameters].[Parameter 1]' type-v2='paramctrl' w='10000' x='10000' y='50000'/>
  <zone h='10000' id='9' name='Sheet 2' param='[{DS}].[none:Region:nk]' type-v2='color' w='10000' x='20000' y='50000'/>
</zone></zones>
<simple-id uuid='{{33333333-3333-3333-3333-333333333333}}'/></dashboard>"""
ACTIONS = """<actions>
<action caption='Inside' name='[Action1_AAAA]'><activation type='on-select'/>
  <source dashboard='Dash' type='sheet' worksheet='Sheet 1'/>
  <command command='tsc:tsl-filter'><param name='special-fields' value='all'/><param name='target' value='Dash'/></command>
  <link caption='Inside' expression='tsl:Dash?x=1' url-escape='true'/></action>
<action caption='Leaves' name='[Action2_BBBB]'><activation type='on-select'/>
  <source dashboard='Dash' type='sheet' worksheet='Sheet 2'/>
  <command command='tsc:brush'><param name='target' value='Elsewhere'/></command></action>
<action caption='Unrelated' name='[Action3_CCCC]'><activation type='on-select'/>
  <source dashboard='Elsewhere' type='sheet' worksheet='Zzz'/>
  <command command='tsc:tsl-filter'><param name='target' value='Elsewhere'/></command></action>
</actions>"""
WINDOWS = ("<windows><window class='worksheet' name='Sheet 1' hidden='true'><viewpoints/>"
           "<simple-id uuid='{22222222-2222-2222-2222-222222222222}'/></window>"
           "<window class='worksheet' name='Sheet 2' hidden='true'><viewpoints/>"
           "<simple-id uuid='{55555555-5555-5555-5555-555555555555}'/></window>"
           "<window class='dashboard' name='Dash'><viewpoints><viewpoint name='Sheet 1'/><viewpoint name='Sheet 2'/>"
           "</viewpoints><active id='5'/><simple-id uuid='{66666666-6666-6666-6666-666666666666}'/></window></windows>")


def source_text(actions=True):
    wb = workbook().replace("</worksheets>", SHEET2 + "</worksheets><dashboards>" + DASH + "</dashboards>")
    wb = wb.replace("<windows>" + wb.split("<windows>")[1].split("</windows>")[0] + "</windows>", WINDOWS)
    return wb.replace("<worksheets>", (ACTIONS if actions else "") + "<worksheets>", 1)


@pytest.fixture
def src(tmp_path):
    return write(tmp_path, source_text(), "src.twb")


@pytest.fixture
def dst(tmp_path):
    return write(tmp_path, target_text().replace(PARAMS, ""), "dst.twb")


def test_plan_is_a_dry_run_and_reports(src, dst):
    rep = plan_dashboard_copy(src, dst, ["Dash"])
    assert rep["copied"] == 1 and rep["refused"] == 0
    d = rep["dashboards"][0]
    assert d["sheets"] == ["Sheet 1", "Sheet 2"] and d["datasources"] == [DS]
    assert {a["name"]: a["status"] for a in rep["actions"]} == {"[Action1_AAAA]": "copy", "[Action2_BBBB]": "dropped"}
    assert any("Leaves" in x for x in d["dropped"]) and any("action filter" in x for x in d["dropped"])
    assert [s["status"] for s in rep["sheets"]] == ["copy", "copy"]


def test_copy_makes_dashboard_sheets_window_actions_and_fresh_uuids(src, dst):
    data, rep = build_dashboard_copy(src, dst, ["Dash"])
    doc = out_doc(data)
    assert names(doc) == ["Other", "Sheet 1", "Sheet 2"]
    assert names(doc, "/workbook/dashboards/dashboard/@name") == ["Dash"]
    db = doc.xpath("/workbook/dashboards/dashboard")[0]
    assert db.xpath("./simple-id/@uuid") != ["{33333333-3333-3333-3333-333333333333}"]
    assert len(db.xpath(".//zone[@param]")) == 3 and db.xpath("./datasources/datasource/@name") == ["Parameters", DS]
    win = doc.xpath("/workbook/windows/window[@class='dashboard']")
    assert len(win) == 1 and win[0].xpath("./viewpoints/viewpoint/@name") == ["Sheet 1", "Sheet 2"]
    assert win[0].xpath("./simple-id/@uuid") != ["{66666666-6666-6666-6666-666666666666}"]
    assert doc.xpath("/workbook/windows/window[@class='worksheet']/@hidden") == ["true", "true"]
    uuids = doc.xpath("//simple-id/@uuid")
    assert len(uuids) == len(set(uuids))
    acts = doc.xpath("/workbook/actions/action")
    assert [a.get("caption") for a in acts] == ["Inside"]
    assert not integrity_check(doc, require_window=True)
    assert doc.xpath("count(/workbook/actions/following-sibling::worksheets)") == 1      # schema order


def test_schema_gate_target_and_source_baseline(src, dst):
    from schema_check import schema_errors
    data, _ = build_dashboard_copy(src, dst, ["Dash"])
    assert not (schema_errors(data) - schema_errors(src) - schema_errors(dst))


def test_name_clash_policies_rename_follows_into_zones_windows_and_actions(tmp_path, src):
    t = write(tmp_path, target_text(sheet=OTHER.replace("Other", "Sheet 1")).replace(
        "</worksheets>", "</worksheets><dashboards><dashboard name='Dash'/></dashboards>"), "t.twb")
    with pytest.raises(SheetCopyAbort, match="on_clash='fail'"):
        plan_dashboard_copy(src, t, ["Dash"])
    rep = plan_dashboard_copy(src, t, ["Dash"], on_clash="skip")
    assert rep["skipped"] == 1 and rep["copied"] == 0 and rep["sheets"] == []
    data, rep = build_dashboard_copy(src, t, ["Dash"], on_clash="rename")
    doc = out_doc(data)
    assert names(doc) == ["Sheet 1", "Sheet 1 (2)", "Sheet 2"]
    assert names(doc, "/workbook/dashboards/dashboard/@name") == ["Dash", "Dash (2)"]
    new = doc.xpath("/workbook/dashboards/dashboard[@name='Dash (2)']")[0]
    assert sorted(set(new.xpath(".//zone/@name"))) == ["Sheet 1 (2)", "Sheet 2"]
    win = doc.xpath("/workbook/windows/window[@class='dashboard'][@name='Dash (2)']")[0]
    assert win.xpath("./viewpoints/viewpoint/@name") == ["Sheet 1 (2)", "Sheet 2"]
    act = doc.xpath("/workbook/actions/action")[0]
    assert act.xpath("./source/@dashboard") == ["Dash (2)"] and act.xpath("./source/@worksheet") == ["Sheet 1 (2)"]
    assert act.xpath("./command/param[@name='target']/@value") == ["Dash (2)"]
    assert act.find("link").get("expression") == "tsl:Dash%20%282%29?x=1"
    assert not [p for p in integrity_check(doc, require_window=True) if p["dashboard"] == "Dash (2)"]


def test_action_name_is_renewed_when_the_target_has_it(tmp_path, src):
    t = write(tmp_path, target_text().replace("<worksheets>", ACTIONS.split("<action caption='Leaves'")[0]
                                              .replace("Inside", "Mine") + "</actions><worksheets>", 1), "t.twb")
    data, _ = build_dashboard_copy(src, t, ["Dash"])
    anames = out_doc(data).xpath("/workbook/actions/action/@name")
    assert len(anames) == 2 and len(set(anames)) == 2 and anames[0] == "[Action1_AAAA]"


def test_one_bad_sheet_refuses_the_dashboard_and_copies_none_of_its_sheets(tmp_path, dst):
    bad = source_text().replace("</worksheets>", SHEET.replace("Sheet 1", "Sheet 3").replace(
        "<rows>", f"<rows>[{DS}].[sum:Ghost:qk]") + "</worksheets>").replace(
        "<zone h='50000' id='6'", "<zone h='1' id='60' name='Sheet 3'/><zone h='50000' id='6'")
    s = write(tmp_path, bad, "bad.twb")
    rep = plan_dashboard_copy(s, dst, ["Dash"])
    assert rep["refused"] == 1 and rep["copied"] == 0 and rep["sheets"] == []
    assert "Sheet 3" in rep["dashboards"][0]["reason"]
    with pytest.raises(SheetCopyAbort, match="no dashboard could be copied"):
        copy_dashboards(s, dst, ["Dash"], str(tmp_path / "o.twb"))
    assert not (tmp_path / "o.twb").exists()


def test_refused_dashboard_does_not_take_a_shared_sheet_down_with_it(tmp_path, dst):
    two = source_text().replace("</dashboards>", DASH.replace("name='Dash'", "name='Dash B'").replace(
        "3333-3333-3333-3333-333333333333", "7777-7777-7777-7777-777777777777").replace(
        "name='Sheet 2'", "name='Sheet 1'") .replace("<zone h='10000' id='9' name='Sheet 1'", "<zone h='1' id='9' name='Sheet 4'")
        + "</dashboards>").replace("</worksheets>", SHEET.replace("Sheet 1", "Sheet 4").replace(
            "<rows>", f"<rows>[{DS}].[sum:Ghost:qk]") + "</worksheets>")
    rep = plan_dashboard_copy(write(tmp_path, two, "two.twb"), dst, ["Dash", "Dash B"])
    by = {d["dashboard"]: d["status"] for d in rep["dashboards"]}
    assert by == {"Dash": "copy", "Dash B": "refused"}
    assert [s["sheet"] for s in rep["sheets"]] == ["Sheet 1", "Sheet 2"]


def test_filter_zone_dependency_missing_from_the_target_is_named(tmp_path, dst):
    extra = DASH.replace("</datasource-dependencies>\n<datasource-dependencies datasource='Parameters'>",
                         "<column name='[Ghost]' datatype='string' role='dimension'/></datasource-dependencies>\n"
                         "<datasource-dependencies datasource='Parameters'>")
    s = write(tmp_path, source_text().replace(DASH, extra), "g.twb")
    rep = plan_dashboard_copy(s, dst, ["Dash"])
    assert rep["refused"] == 1 and "[Ghost]" in rep["dashboards"][0]["reason"]


def test_other_connection_and_zone_on_another_dashboard_are_refused(tmp_path, src):
    other = write(tmp_path, target_text(ds=datasource(path="C:/x/other.xlsx")), "o.twb")
    assert plan_dashboard_copy(src, other, ["Dash"])["refused"] == 1
    nested = source_text().replace("</dashboards>", "<dashboard name='Inner'/></dashboards>").replace(
        "<zone h='50000' id='6' name='Sheet 2'", "<zone h='50000' id='6' name='Inner'")
    rep = plan_dashboard_copy(write(tmp_path, nested, "n.twb"), other, ["Dash"])
    assert "another dashboard" in rep["dashboards"][0]["reason"]


def test_strict_refuses_instead_of_dropping(src, dst):
    with pytest.raises(SheetCopyAbort, match="--strict"):
        plan_dashboard_copy(src, dst, ["Dash"], strict=True)


def test_dashboard_without_actions_or_drops_passes_strict(tmp_path, dst):
    s = write(tmp_path, source_text(actions=False).replace(
        "<filter class='categorical' column='[%s].[Action (Region)]'/>" % DS, ""), "na.twb")
    # the cached action group in the datasource is not a filter; nothing else is dropped
    rep = plan_dashboard_copy(s, dst, ["Dash"], strict=True)
    assert rep["copied"] == 1 and rep["actions"] == []


def test_unknown_and_no_dashboards_abort(src, dst):
    with pytest.raises(SheetCopyAbort, match="no dashboard named 'Nope'"):
        plan_dashboard_copy(src, dst, ["Nope"])
    with pytest.raises(SheetCopyAbort, match="no dashboards named"):
        plan_dashboard_copy(src, dst, [])


def test_parameter_clash_rename_reaches_the_dashboard(tmp_path, src):
    params = PARAMS.replace("value='2'", "value='5'").replace("formula='2'", "formula='5'")
    t = write(tmp_path, target_text().replace(PARAMS, params), "p.twb")
    with pytest.raises(SheetCopyAbort):
        plan_dashboard_copy(src, t, ["Dash"])
    data, _ = build_dashboard_copy(src, t, ["Dash"], on_clash="rename")
    db = out_doc(data).xpath("/workbook/dashboards/dashboard")[0]
    text = etree.tostring(db).decode()
    assert "[Parameters].[Parameter 2]" in text and "[Parameters].[Parameter 1]" not in text
    assert db.xpath("./datasource-dependencies[@datasource='Parameters']/column/@name") == ["[Parameter 2]"]


def test_copy_into_itself_with_rename_and_output_rules(src, tmp_path, dst):
    data, rep = build_dashboard_copy(src, src, ["Dash"], on_clash="rename")
    doc = out_doc(data)
    assert names(doc, "/workbook/dashboards/dashboard/@name") == ["Dash", "Dash (2)"]
    assert not integrity_check(doc)
    out = str(tmp_path / "o.twb")
    copy_dashboards(src, dst, ["Dash"], out)
    with pytest.raises(FileExistsError):
        copy_dashboards(src, dst, ["Dash"], out)
    with pytest.raises(FileExistsError, match="input"):
        copy_dashboards(src, dst, ["Dash"], dst, overwrite=True)
    with pytest.raises(SheetCopyAbort, match="must end in"):
        copy_dashboards(src, dst, ["Dash"], str(tmp_path / "o.xml"))


def test_cli_dry_run_then_write_and_exit_codes(src, dst, tmp_path, capsys):
    assert cli.main(["dashboard", "copy", src, "--dashboards", "Dash", "--to", dst]) == 0
    cap = capsys.readouterr()
    assert "to copy" in cap.out and "nothing written" in cap.err and "dropped: action Leaves" in cap.out
    assert not (tmp_path / "dst_dashcopy.twb").exists()
    o = str(tmp_path / "out.twb")
    assert cli.main(["dashboard", "copy", src, "--dashboard", "Dash", "--to", dst, "--write", "-o", o,
                     "--format", "json"]) == 0
    cap = capsys.readouterr()
    assert json.loads(cap.out)["copied"] == 1 and "wrote" in cap.err
    assert cli.main(["dashboard", "copy", src, "--dashboards", "Dash", "--to", o]) == 1
    assert "on_clash='fail'" in capsys.readouterr().err
    assert cli.main(["dashboard", "copy", src, "--dashboards", "Dash", "--to", dst, "--strict"]) == 1
    assert cli.main(["dashboard", "copy", src, "--dashboards", "Nope", "--to", dst]) == 1
    capsys.readouterr()
    other = write(tmp_path, target_text(ds=datasource(path="C:/x/o.xlsx")), "o3.twb")
    assert cli.main(["dashboard", "copy", src, "--dashboards", "Dash", "--to", other]) == 1
    with pytest.raises(SystemExit):
        cli.main(["dashboard", "copy", src, "--dashboards", "Dash", "--to", dst, "-o", o])


def test_cli_partial_refusal_is_exit_2(tmp_path, dst, capsys):
    two = source_text().replace("</dashboards>", "<dashboard name='Lone'><zones><zone id='1' name='Nope'/></zones>"
                                "</dashboard></dashboards>")
    s = write(tmp_path, two, "two.twb")
    o = str(tmp_path / "p.twb")
    assert cli.main(["dashboard", "copy", s, "--dashboards", "Dash,Lone", "--to", dst, "--write", "-o", o]) == 2
    assert "refused" in capsys.readouterr().out
    assert names(TwbParser(o).xml_doc, "/workbook/dashboards/dashboard/@name") == ["Dash"]


def test_twbx_target_keeps_format(tmp_path, src, dst):
    import zipfile
    x = tmp_path / "t.twbx"
    with zipfile.ZipFile(x, "w") as z:
        z.write(dst, "t.twb")
        z.writestr("Data/extra.txt", "keep")
    out = tmp_path / "o.twbx"
    copy_dashboards(src, str(x), ["Dash"], str(out))
    with zipfile.ZipFile(out) as z:
        assert "Data/extra.txt" in z.namelist()
