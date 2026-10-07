"""WP14e: `sheet copy` (same internal name), on small synthetic workbooks. Nothing here opens Tableau."""

import io
import json
import sys
import zipfile
from pathlib import Path

import pytest
from lxml import etree

sys.path.insert(0, str(Path(__file__).parent))

from py_tbparse import TwbParser  # noqa: E402
from py_tbparse import cli  # noqa: E402
from py_tbparse.dashboards import integrity_check  # noqa: E402
from py_tbparse.sheetcopy import (  # noqa: E402
    SheetCopyAbort, build_sheet_copy, copy_sheets, plan_sheet_copy,
)
from test_sheetcopy_core import DS, PARAMS, SHEET, datasource, workbook  # noqa: E402

OTHER = "<worksheet name='Other'><table><view><datasources/></view></table></worksheet>"


def write(tmp_path, text, name):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


@pytest.fixture
def src(tmp_path):
    return write(tmp_path, workbook(), "src.twb")


def target_text(**kw):
    return workbook(ds=kw.pop("ds", datasource(calcs=False)), sheet=kw.pop("sheet", OTHER), windows=False, **kw)


@pytest.fixture
def dst(tmp_path):
    return write(tmp_path, target_text().replace(PARAMS, ""), "dst.twb")      # no Parameters datasource at all


def out_doc(data):
    return etree.fromstring(data)


def names(doc, xp="/workbook/worksheets/worksheet/@name"):
    return doc.xpath(xp)


def test_plan_is_a_dry_run_and_reports(src, dst):
    rep = plan_sheet_copy(src, dst, ["Sheet 1"])
    assert rep["copied"] == 1 and rep["refused"] == 0
    assert {a["name"] for a in rep["added"]} == {"[Double]", "[Ratio]", "[Parameter 1]"}
    assert rep["sheets"][0]["dropped"] == [f"action filter on [{DS}].[Action (Region)]"]


def test_copy_adds_sheet_calcs_parameter_window_and_drops_action_filter(src, dst):
    data, rep = build_sheet_copy(src, dst, ["Sheet 1"])
    doc = out_doc(data)
    assert names(doc) == ["Other", "Sheet 1"]
    ws = doc.xpath("/workbook/worksheets/worksheet[@name='Sheet 1']")[0]
    assert "Action (" not in etree.tostring(ws).decode()
    assert not ws.xpath(".//simple-id[@uuid='{11111111-1111-1111-1111-111111111111}']")      # uuid renewed
    cols = doc.xpath(f"/workbook/datasources/datasource[@name='{DS}']/column/@name")
    assert "[Double]" in cols and "[Ratio]" in cols
    assert doc.xpath("//datasource[@name='Parameters']/column/@name") == ["[Parameter 1]"]
    win = doc.xpath("/workbook/windows/window[@name='Sheet 1']")
    assert len(win) == 1 and win[0].get("hidden") is None
    assert not integrity_check(doc)


def test_schema_gate_target_and_source_baseline(src, dst):
    from schema_check import schema_errors
    data, _ = build_sheet_copy(src, dst, ["Sheet 1"])
    assert not (schema_errors(data) - schema_errors(src) - schema_errors(dst))


def test_identical_calcs_in_target_are_not_added_twice(tmp_path, src):
    both = write(tmp_path, target_text(ds=datasource()), "both.twb")
    rep = plan_sheet_copy(src, both, ["Sheet 1"], on_clash="fail")
    assert rep["added"] == [] and rep["copied"] == 1
    # the parameter lives in the target already (the fixture's target has PARAMS), identical
    data, _ = build_sheet_copy(src, both, ["Sheet 1"])
    assert etree.fromstring(data).xpath(f"count(//datasource[@name='{DS}']/column[@name='[Double]'])") == 1


def test_calc_clash_fails_by_default_and_renames_on_request(tmp_path, src):
    clash = write(tmp_path, target_text(ds=datasource(calc_formula="[Sales] * 3")), "clash.twb")
    with pytest.raises(SheetCopyAbort, match="on_clash='fail'"):
        plan_sheet_copy(src, clash, ["Sheet 1"])
    data, rep = build_sheet_copy(src, clash, ["Sheet 1"], on_clash="rename")
    doc = out_doc(data)
    cols = doc.xpath(f"/workbook/datasources/datasource[@name='{DS}']/column")
    assert len(cols) > len({c.get("name") for c in cols}) - 1
    renamed = [r for r in rep["library"] if r["action"] == "add-renamed"]
    assert renamed and renamed[0]["target_name"] != renamed[0]["name"]
    ws = doc.xpath("/workbook/worksheets/worksheet[@name='Sheet 1']")[0]
    new = renamed[0]["target_name"]
    assert new[1:-1] in etree.tostring(ws).decode()          # the sheet now points at the renamed calculation


def test_refused_sheet_leaves_none_of_its_new_calculations_behind(tmp_path, monkeypatch):
    # No real input reaches the planner's "fail" rows for a sheet that passed the checks before it, so the planner
    # is made to refuse [Bad] here, as it does for a field it cannot map.
    from py_tbparse import library as lib_mod
    extra = ("<column name='[Other]' datatype='real' role='measure'><calculation class='tableau' formula='[Sales] * 7'/></column>"
             "<column name='[Bad]' datatype='real' role='measure'><calculation class='tableau' formula='[Sales] * 8'/></column>")
    ds = datasource().replace("<column name='[Size]'", extra + "<column name='[Size]'")
    sheet2 = (SHEET.replace("Sheet 1", "Sheet 2").replace("[Ratio]", "[Other]").replace(":Ratio:", ":Other:")
              .replace("11111111-1111", "99999999-9999")
              .replace("</datasource-dependencies>", "<column-instance column='[Bad]' derivation='Sum' "
                       "name='[sum:Bad:qk]' pivot='key' type='quantitative'/></datasource-dependencies>", 1)
              .replace("<rows>", "<rows>[" + DS + "].[sum:Bad:qk] ", 1))
    s = write(tmp_path, workbook(ds=ds, sheet=SHEET + sheet2), "two.twb")
    t = write(tmp_path, target_text(ds=datasource(calcs=False)), "tgt.twb")
    real = lib_mod._plan

    def plan(*a, **kw):
        table, actions, T = real(*a, **kw)
        table = table.copy()
        bad = table["name"] == "[Bad]"
        table.loc[bad, "action"] = "fail-unmapped"
        return table, [x for x in actions if x["entry"]["name"] != "[Bad]"], T

    monkeypatch.setattr(lib_mod, "_plan", plan)
    data, rep = build_sheet_copy(s, t, ["Sheet 1", "Sheet 2"])
    status = {r["sheet"]: r["status"] for r in rep["sheets"]}
    assert status == {"Sheet 1": "copy", "Sheet 2": "refused"}
    cols = out_doc(data).xpath(f"/workbook/datasources/datasource[@name='{DS}']/column/@name")
    assert "[Double]" in cols and "[Ratio]" in cols
    assert "[Other]" not in cols and "[Bad]" not in cols
    assert {a["name"] for a in rep["added"]} == {"[Double]", "[Ratio]"}

def test_group_with_other_members_is_a_clash_under_every_policy(tmp_path):
    top = SHEET.replace("<rows>", f"<rows>[{DS}].[none:Top:nk]")
    s = write(tmp_path, workbook(sheet=top), "gsrc.twb")
    same = write(tmp_path, target_text(ds=datasource()), "gsame.twb")
    assert plan_sheet_copy(s, same, ["Sheet 1"], on_clash="fail")["copied"] == 1
    west = datasource().replace("&quot;East&quot;", "&quot;West&quot;")
    t = write(tmp_path, target_text(ds=west), "gwest.twb")
    with pytest.raises(SheetCopyAbort, match=r"on_clash='fail'.*\[Top\]"):
        plan_sheet_copy(s, t, ["Sheet 1"], on_clash="fail")
    for policy in ("rename", "skip"):
        rep = plan_sheet_copy(s, t, ["Sheet 1"], on_clash=policy)
        assert rep["copied"] == 0 and rep["refused"] == 1
        assert "[Top]" in rep["sheets"][0]["reason"]

def test_dependent_of_a_clashing_calc_is_renamed_too_not_taken_as_identical(tmp_path, src):
    # the target's [Double] is x3 and its [Ratio] has the source's text; [Ratio] would use the other [Double]
    clash = write(tmp_path, target_text(ds=datasource(calc_formula="[Sales] * 3")), "dep.twb")
    with pytest.raises(SheetCopyAbort, match="on_clash='fail'"):
        plan_sheet_copy(src, clash, ["Sheet 1"])
    data, rep = build_sheet_copy(src, clash, ["Sheet 1"], on_clash="rename")
    acts = {r["name"]: r for r in rep["library"]}
    assert acts["[Double]"]["action"] == "add-renamed" and acts["[Ratio]"]["action"] == "add-renamed"
    doc = out_doc(data)
    ws = etree.tostring(doc.xpath("/workbook/worksheets/worksheet[@name='Sheet 1']")[0]).decode()
    assert acts["[Ratio]"]["target_name"][1:-1] in ws       # the sheet uses the new Ratio, not the target's
    cols = {c.get("name"): c.find("calculation").get("formula")
            for c in doc.xpath(f"/workbook/datasources/datasource[@name='{DS}']/column[calculation]")}
    assert cols[acts["[Ratio]"]["target_name"]].startswith(acts["[Double]"]["target_name"])


def test_dependent_of_a_clashing_calc_refuses_the_sheet_under_skip(tmp_path, src):
    clash = write(tmp_path, target_text(ds=datasource(calc_formula="[Sales] * 3")), "dep.twb")
    rep = plan_sheet_copy(src, clash, ["Sheet 1"], on_clash="skip")
    assert rep["copied"] == 0 and rep["refused"] == 1
    assert "[Ratio]" in rep["sheets"][0]["reason"]


def test_parameter_clash_renames_internal_name(tmp_path, src):
    params = PARAMS.replace("value='2'", "value='5'").replace("formula='2'", "formula='5'")
    wb = target_text().replace(PARAMS, params)
    clash = write(tmp_path, wb, "pclash.twb")
    with pytest.raises(SheetCopyAbort):
        plan_sheet_copy(src, clash, ["Sheet 1"])
    data, rep = build_sheet_copy(src, clash, ["Sheet 1"], on_clash="rename")
    pnames = out_doc(data).xpath("//datasource[@name='Parameters']/column/@name")
    assert len(pnames) == 2 and "[Parameter 2]" in pnames
    ws = out_doc(data).xpath("/workbook/worksheets/worksheet[@name='Sheet 1']")[0]
    assert "[Parameters].[Parameter 2]" in etree.tostring(ws).decode()


def test_sheet_name_clash_policies(tmp_path, src):
    t = write(tmp_path, target_text(sheet=OTHER.replace("Other", "Sheet 1")), "t.twb")
    with pytest.raises(SheetCopyAbort, match="already a sheet"):
        plan_sheet_copy(src, t, ["Sheet 1"])
    data, rep = build_sheet_copy(src, t, ["Sheet 1"], on_clash="rename")
    doc = out_doc(data)
    assert names(doc) == ["Sheet 1", "Sheet 1 (2)"]
    assert doc.xpath("/workbook/windows/window/@name") == ["Sheet 1 (2)"]
    rep = plan_sheet_copy(src, t, ["Sheet 1"], on_clash="skip")
    assert rep["skipped"] == 1 and rep["copied"] == 0


def test_sheet_name_clash_with_a_dashboard(tmp_path, src):
    wb = target_text().replace("</worksheets>", "</worksheets><dashboards><dashboard name='Sheet 1'/></dashboards>")
    t = write(tmp_path, wb, "d.twb")
    data, _ = build_sheet_copy(src, t, ["Sheet 1"], on_clash="rename")
    assert "Sheet 1 (2)" in names(out_doc(data))


def test_different_internal_name_is_refused_with_the_core_message(tmp_path, src):
    t = write(tmp_path, target_text(ds=datasource(name="federated.zzz")).replace(DS, "federated.zzz"), "n.twb")
    rep = plan_sheet_copy(src, t, ["Sheet 1"])
    assert rep["refused"] == 1 and "only the same internal name is supported" in rep["sheets"][0]["reason"]
    assert "federated.zzz" in rep["sheets"][0]["reason"]


def test_other_connection_blend_and_missing_field_are_refused(tmp_path, src):
    other = write(tmp_path, target_text(ds=datasource(path="C:/x/other.xlsx")), "o.twb")
    assert "no datasource with the connection" in plan_sheet_copy(src, other, ["Sheet 1"])["sheets"][0]["reason"]
    nosales = write(tmp_path, target_text(ds=datasource(sales=False, calcs=False)), "ns.twb")
    assert "lacks" in plan_sheet_copy(src, nosales, ["Sheet 1"])["sheets"][0]["reason"]
    blend = SHEET.replace("</datasources>", "<datasource name='federated.bbb'/></datasources>")
    b = write(tmp_path, workbook(sheet=blend), "b.twb")
    assert "blend" in plan_sheet_copy(b, src, ["Sheet 1"])["sheets"][0]["reason"]


def test_target_without_worksheets_and_datasources_aborts_cleanly(tmp_path, src):
    empty = write(tmp_path, "<?xml version='1.0' encoding='utf-8' ?><workbook version='18.1'/>", "empty.twb")
    with pytest.raises(SheetCopyAbort, match="neither worksheets nor datasources"):
        plan_sheet_copy(src, empty, ["Sheet 1"])


def test_unknown_sheet_and_no_sheets_abort(src, dst):
    with pytest.raises(SheetCopyAbort, match="no worksheet named 'Nope'"):
        plan_sheet_copy(src, dst, ["Nope"])
    with pytest.raises(SheetCopyAbort, match="no sheets named"):
        plan_sheet_copy(src, dst, [])


def test_strict_refuses_instead_of_dropping(src, dst):
    with pytest.raises(SheetCopyAbort, match="--strict"):
        plan_sheet_copy(src, dst, ["Sheet 1"], strict=True)


def test_tooltip_sheet_not_copied_is_dropped_and_copied_one_follows_rename(tmp_path, dst):
    tip = ("<customized-tooltip><formatted-text><run>a &lt;Sheet name=\"Other\" maxwidth=\"300\"/&gt;"
           "b &lt;Sheet name=\"Sheet 1\" maxwidth=\"3\"/&gt;</run></formatted-text></customized-tooltip>")
    sheet = SHEET.replace("<rows>", tip + "<rows>")
    # an unescaped version: the run text holds the markup text
    s = write(tmp_path, workbook(sheet=sheet.replace("&lt;", "&lt;")), "s.twb")
    t = write(tmp_path, target_text(sheet=OTHER.replace("Other", "Sheet 1")), "t2.twb")
    data, rep = build_sheet_copy(s, t, ["Sheet 1"], on_clash="rename")
    text = etree.tostring(out_doc(data).xpath("//worksheet[@name='Sheet 1 (2)']")[0]).decode()
    assert 'name="Sheet 1 (2)"' in text.replace("&quot;", '"') and "Other" not in text
    assert any("tooltip" not in d for d in rep["sheets"][0]["dropped"])


def test_twbx_target_keeps_members_and_format(tmp_path, src, dst):
    tx = tmp_path / "t.twbx"
    with zipfile.ZipFile(tx, "w") as z:
        z.writestr("t.twb", target_text())
        z.writestr("Data/a.csv", "x\n1\n")
    out, rep = copy_sheets(src, str(tx), ["Sheet 1"], str(tmp_path / "o.twbx"))
    with zipfile.ZipFile(out) as z:
        assert set(z.namelist()) == {"t.twb", "Data/a.csv"} and z.read("Data/a.csv") == b"x\n1\n"
    assert "Sheet 1" in names(TwbParser(out).xml_doc)


def test_copy_into_itself_with_rename(src, tmp_path):
    out, rep = copy_sheets(src, src, ["Sheet 1"], str(tmp_path / "self.twb"), on_clash="rename")
    doc = TwbParser(out).xml_doc
    assert names(doc) == ["Sheet 1", "Sheet 1 (2)"] and rep["added"] == []
    # twice with skip adds nothing new
    rep2 = plan_sheet_copy(out, out, ["Sheet 1"], on_clash="skip")
    assert rep2["skipped"] == 1 and rep2["added"] == []
    with pytest.raises(SheetCopyAbort, match="nothing written"):      # nothing to write when every sheet is skipped
        copy_sheets(out, out, ["Sheet 1"], str(tmp_path / "self2.twb"), on_clash="skip")


def test_output_rules(src, dst, tmp_path):
    o = tmp_path / "o.twb"
    copy_sheets(src, dst, ["Sheet 1"], str(o))
    with pytest.raises(FileExistsError):
        copy_sheets(src, dst, ["Sheet 1"], str(o))
    with pytest.raises(FileExistsError, match="input"):
        copy_sheets(src, dst, ["Sheet 1"], dst, overwrite=True)
    with pytest.raises(SheetCopyAbort, match="must end in"):
        copy_sheets(src, dst, ["Sheet 1"], str(tmp_path / "o.twbx"))
    copy_sheets(src, dst, ["Sheet 1"])
    assert (tmp_path / "dst_sheetcopy.twb").exists()


def test_nothing_copyable_writes_nothing(src, tmp_path):
    other = write(tmp_path, target_text(ds=datasource(path="C:/x/other.xlsx")), "o2.twb")
    with pytest.raises(SheetCopyAbort, match="nothing written"):
        copy_sheets(src, other, ["Sheet 1"], str(tmp_path / "x.twb"))
    assert not (tmp_path / "x.twb").exists()


# ------------------------------------------------------------------- CLI --

def test_cli_dry_run_then_write_and_exit_codes(src, dst, tmp_path, capsys):
    assert cli.main(["sheet", "copy", src, "--sheets", "Sheet 1", "--to", dst]) == 0
    cap = capsys.readouterr()
    assert "to copy" in cap.out and "nothing written" in cap.err and "dropped: action filter" in cap.out
    assert not (tmp_path / "dst_sheetcopy.twb").exists()
    o = str(tmp_path / "out.twb")
    assert cli.main(["sheet", "copy", src, "--sheet", "Sheet 1", "--to", dst, "--write", "-o", o, "--format", "json"]) == 0
    cap = capsys.readouterr()
    assert json.loads(cap.out)["copied"] == 1 and "wrote" in cap.err
    # a clash under the default policy stops the run (1); a refused sheet next to a copied one is 2
    assert cli.main(["sheet", "copy", src, "--sheets", "Sheet 1", "--to", o]) == 1
    assert "on_clash='fail'" in capsys.readouterr().err
    assert cli.main(["sheet", "copy", src, "--sheets", "Sheet 1", "--to", dst, "--strict"]) == 1
    assert cli.main(["sheet", "copy", src, "--sheets", "Nope", "--to", dst]) == 1
    capsys.readouterr()
    other = write(tmp_path, target_text(ds=datasource(path="C:/x/other.xlsx")), "o3.twb")
    assert cli.main(["sheet", "copy", src, "--sheets", "Sheet 1", "--to", other]) == 1
    with pytest.raises(SystemExit):
        cli.main(["sheet", "copy", src, "--sheets", "Sheet 1", "--to", dst, "-o", o])


def test_cli_partial_refusal_is_exit_2(tmp_path, capsys):
    two = workbook().replace("</worksheets>", SHEET.replace("Sheet 1", "Sheet 2").replace(
        "<rows>", f"<rows>[{DS}].[sum:Ghost:qk]") + "</worksheets>")
    s = write(tmp_path, two, "two.twb")
    d = write(tmp_path, target_text(), "d.twb")
    assert cli.main(["sheet", "copy", s, "--sheets", "Sheet 1,Sheet 2", "--to", d, "--write",
                     "-o", str(tmp_path / "p.twb")]) == 2
    assert "refused" in capsys.readouterr().out
    assert names(TwbParser(str(tmp_path / "p.twb")).xml_doc) == ["Other", "Sheet 1"]
