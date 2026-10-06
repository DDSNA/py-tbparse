"""`prune`: removes what the audit proves unused and nothing that still has a user (WP10b).

Synthetic workbooks come from `test_audit.workbook`. The 200-workbook corpus run is `test_prune_corpus.py`.
"""

import json
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from schema_check import new_schema_errors
from test_audit import workbook

from py_tbparse import TwbParser, audit, prune
from py_tbparse.cli import main
from py_tbparse.prune import PruneError

CALC = [("[Calculation_1]", "Margin", "[Sales] - [Profit]")]


def names(report, category):
    return [r["object"] for r in report["removed"] if r["category"] == category]


def kept(report):
    return {k["object"]: k["reason"] for k in report["kept"]}


def text(path):
    return Path(path).read_text(encoding="utf-8")


def test_dry_run_reports_and_writes_nothing(tmp_path):
    path = workbook(tmp_path, calcs=CALC)
    before = text(path)
    report = prune(path)
    assert report["dry_run"] and report["output"] is None
    assert names(report, "calculations") == ["Orders: Margin"]
    assert report["removed"][0]["detail"]
    assert text(path) == before
    assert [p.name for p in tmp_path.iterdir()] == ["wb.twb"]


def test_write_removes_the_calculation_and_every_trace(tmp_path):
    extra = ("<column-instance column='[Calculation_1]' derivation='None' name='[none:Calculation_1:nk]' type='nominal'/>"
             "<folders-common><folder name='F'><folder-item name='[Calculation_1]' type='field'/>"
             "<folder-item name='[Sales]' type='field'/></folder></folders-common>"
             "<drill-paths><drill-path name='H'><field>[Sales]</field><field>[Calculation_1]</field>"
             "</drill-path></drill-paths>"
             "<style><style-rule element='mark'><encoding attr='color' field='[none:Calculation_1:nk]' type='palette'/>"
             "</style-rule></style>")
    path = workbook(tmp_path, calcs=CALC, ds_extra=extra)
    out = tmp_path / "out.twb"
    report = prune(path, str(out))
    assert report["output"] == str(out) and not report["dry_run"]
    new = text(out)
    assert "Calculation_1" not in new and "Margin" not in new
    assert "[Sales]" in new and "<folder name=\"F\"" in new.replace("'", '"')
    assert report["traces"] == {"columns": 1, "column_instances": 1, "folder_items": 1, "hierarchy_fields": 1,
                                "style_entries": 1}
    assert "<style" not in new                      # emptied rule and style go; a hierarchy keeps its field
    assert "<drill-path" in new
    TwbParser(str(out))
    assert new_schema_errors(path, str(out)) == []
    assert audit(str(out), only=["A001", "A003"]).empty


def test_a_calculation_a_used_calculation_needs_is_not_removed(tmp_path):
    calcs = [("[Calculation_1]", "Base", "[Sales]"), ("[Calculation_2]", "Top", "[Calculation_1] * 2")]
    path = workbook(tmp_path, calcs=calcs, sheets={"Sheet 1": ["[Calculation_2]"]})
    assert prune(path)["removed"] == []                 # not even unused


def test_a_chain_of_unused_calculations_goes_together(tmp_path):
    calcs = [("[Calculation_1]", "Base", "[Sales]"), ("[Calculation_2]", "Top", "[Calculation_1] * 2")]
    path = workbook(tmp_path, calcs=calcs)
    report = prune(path, str(tmp_path / "o.twb"))
    assert sorted(names(report, "calculations")) == ["Orders: Base", "Orders: Top"]
    assert "Calculation_" not in text(tmp_path / "o.twb")


def test_a_set_that_names_a_calculation_keeps_it_and_what_it_needs(tmp_path):
    calcs = [("[Calculation_1]", "Base", "[Sales]"), ("[Calculation_2]", "Top", "[Calculation_1] * 2"),
             ("[Calculation_3]", "Loose", "[Profit]")]
    group = ("<group name='[Set 1]' caption='Set 1'>"
             "<groupfilter function='member' level='[Calculation_2]' member='1'/></group>")
    path = workbook(tmp_path, calcs=calcs, ds_extra=group)
    report = prune(path, str(tmp_path / "o.twb"))
    assert names(report, "calculations") == ["Orders: Loose"]
    why = kept(report)
    assert set(why) == {"Orders: Base", "Orders: Top"}
    assert "group" in why["Orders: Top"] and "Set 1" in why["Orders: Top"]
    assert "Calculation_1" in text(tmp_path / "o.twb")


def test_a_dashboard_action_or_window_entry_keeps_a_calculation(tmp_path):
    path = workbook(tmp_path, calcs=CALC)
    doc = text(path).replace("<windows>", "<windows><window class='worksheet' name='Sheet 1'><cards>"
                             "<card type='filter' column='[ds1].[Calculation_1]'/></cards></window>")
    Path(path).write_text(doc, encoding="utf-8")
    # A001 only reads dashboards, actions and worksheets, the window entry is found by prune's own check
    report = prune(path)
    assert report["removed"] == [] and "window" in kept(report)["Orders: Margin"]


def test_a_calculation_stored_in_an_extract_is_kept(tmp_path):
    conn = ("<connection class='federated'><extract><connection class='hyper' dbname='x.hyper'>"
            "<cols><map key='[Calculation_1]' value='[Extract].[Calculation_1]'/></cols></connection></extract>"
            "</connection>")
    path = workbook(tmp_path, calcs=CALC, conn=conn)
    report = prune(path)
    assert report["removed"] == [] and list(kept(report)) == ["Orders: Margin"]


def test_hidden_and_used_calculations_are_not_candidates(tmp_path):
    path = workbook(tmp_path, calcs=[("[Calculation_1]", "Margin", "[Sales]", True)])
    assert prune(path)["removed"] == [] and prune(path)["kept"] == []


def test_parameters(tmp_path):
    params = [("[Parameter 1]", "Spare"), ("[Parameter 2]", "Feeds a calc"), ("[Parameter 3]", "Feeds a set")]
    calcs = [("[Calculation_1]", "Scaled", "[Sales] * [Parameters].[Parameter 2]")]
    group = ("<group name='[Set 1]' caption='Set 1'><groupfilter count='[Parameters].[Parameter 3]' "
             "function='end' end='top'/></group>")
    path = workbook(tmp_path, calcs=calcs, params=params, ds_extra=group)
    out = tmp_path / "o.twb"
    report = prune(path, str(out))
    assert sorted(names(report, "parameters")) == ["Parameters: Feeds a calc", "Parameters: Spare"]
    assert names(report, "calculations") == ["Orders: Scaled"]
    assert list(kept(report)) == ["Parameters: Feeds a set"]
    new = text(out)
    assert "Parameter 1" not in new and "Parameter 2" not in new and "Parameter 3" in new
    assert "name='Parameters'" in new.replace('"', "'")          # the datasource stays, empty or not
    assert new_schema_errors(path, str(out)) == []


def test_no_calculations_and_no_parameters_options(tmp_path):
    path = workbook(tmp_path, calcs=CALC, params=[("[Parameter 1]", "Spare")])
    assert names(prune(path, calculations=False), "calculations") == []
    assert names(prune(path, parameters=False), "parameters") == []
    assert prune(path, calculations=False, parameters=False)["removed"] == []


SHEETS = {"Sheet 1": ["[Sales]"], "Loose": ["[Calculation_1]"], "Hidden": []}


def test_sheets_are_not_touched_without_the_flag(tmp_path):
    path = workbook(tmp_path, calcs=CALC, sheets=SHEETS, hidden=["Hidden"])
    assert prune(path)["removed"] == []                  # Calculation_1 is used by the sheet "Loose"


def test_sheets_flag_removes_the_sheet_its_window_and_then_what_only_it_used(tmp_path):
    path = workbook(tmp_path, calcs=CALC, sheets=SHEETS, hidden=["Hidden"])
    doc = text(path).replace("</windows>", "<window class='worksheet' name='Loose'/></windows>")
    doc = doc.replace("</workbook>", "<thumbnails><thumbnail name='Loose' height='1' width='1'/></thumbnails></workbook>")
    Path(path).write_text(doc, encoding="utf-8")
    out = tmp_path / "o.twb"
    report = prune(path, str(out), sheets=True)
    assert names(report, "sheets") == ["Loose"]
    assert names(report, "calculations") == ["Orders: Margin"]          # only "Loose" used it
    assert report["traces"]["windows"] == 1 and report["traces"]["thumbnails"] == 1
    new = text(out)
    assert "Loose" not in new and "Calculation_1" not in new
    assert "name='Hidden'" in new.replace('"', "'") and "Sheet 1" in new
    assert new_schema_errors(path, str(out)) == []
    assert prune(str(out), sheets=True)["removed"] == []


def test_a_sheet_that_an_action_names_is_kept(tmp_path):
    path = workbook(tmp_path, sheets={"Sheet 1": ["[Sales]"], "Loose": ["[Sales]"]})
    doc = text(path).replace("<dashboards>", "<actions><action name='A'><source dashboard='Dash' "
                             "worksheet='Loose' type='sheet'/></action></actions><dashboards>")
    Path(path).write_text(doc, encoding="utf-8")
    report = prune(path, sheets=True)
    assert report["removed"] == [] and "action" in kept(report)["Loose"]


def test_the_last_worksheets_are_never_all_removed(tmp_path):
    path = workbook(tmp_path, sheets={"One": ["[Sales]"], "Two": ["[Sales]"]}, dashboards={"Dash": []})
    report = prune(path, sheets=True)
    assert report["removed"] == [] and set(kept(report)) == {"One", "Two"}


def test_a_workbook_without_dashboards_keeps_its_sheets(tmp_path):
    path = workbook(tmp_path, sheets={"One": ["[Sales]"], "Two": ["[Sales]"]}, dashboards={})
    assert prune(path, sheets=True)["removed"] == []


def test_second_prune_is_a_no_op(tmp_path):
    path = workbook(tmp_path, calcs=CALC, params=[("[Parameter 1]", "Spare")], sheets=SHEETS, hidden=["Hidden"])
    out, again = tmp_path / "o.twb", tmp_path / "o2.twb"
    prune(path, str(out), sheets=True)
    report = prune(str(out), str(again), sheets=True)
    assert report["removed"] == [] and report["kept"] == []
    assert out.read_bytes() == again.read_bytes()


def test_never_writes_the_input_or_an_existing_file(tmp_path):
    path = workbook(tmp_path, calcs=CALC)
    before = Path(path).read_bytes()
    with pytest.raises(FileExistsError, match="input"):
        prune(path, path, overwrite=True)
    assert Path(path).read_bytes() == before
    out = tmp_path / "o.twb"
    out.write_text("keep me")
    with pytest.raises(FileExistsError):
        prune(path, str(out))
    assert out.read_text() == "keep me"
    prune(path, str(out), overwrite=True)
    assert "Calculation_1" not in out.read_text(encoding="utf-8")
    with pytest.raises(PruneError, match=r"\.twb"):
        prune(path, str(tmp_path / "o.twbx"))


def test_twbx_other_members_are_copied(tmp_path):
    path = workbook(tmp_path, calcs=CALC)
    packed = tmp_path / "in.twbx"
    with zipfile.ZipFile(packed, "w") as z:
        z.write(path, "wb.twb")
        z.writestr("Data/sales.csv", "a,b\n1,2\n")
    out = tmp_path / "out.twbx"
    report = prune(str(packed), str(out))
    assert names(report, "calculations") == ["Orders: Margin"]
    with zipfile.ZipFile(out) as z:
        assert sorted(z.namelist()) == ["Data/sales.csv", "wb.twb"]
        assert b"Calculation_1" not in z.read("wb.twb") and z.read("Data/sales.csv") == b"a,b\n1,2\n"
    TwbParser(str(out))


# ------------------------------------------------------------------ CLI --

def test_cli_dry_run_prints_what_and_why(tmp_path, capsys):
    path = workbook(tmp_path, calcs=CALC, params=[("[Parameter 1]", "Spare")])
    assert main(["prune", path]) == 0
    out = capsys.readouterr().out
    assert "would remove" in out and "Orders: Margin" in out and "why:" in out and "dry run" in out
    assert "1 calculation(s), 1 parameter(s), 0 sheet(s)" in out
    assert [p.name for p in tmp_path.iterdir()] == ["wb.twb"]


def test_cli_write_and_json(tmp_path, capsys):
    path = workbook(tmp_path, calcs=CALC)
    out = tmp_path / "o.twb"
    assert main(["prune", path, "--write", "-o", str(out), "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"] == {"calculations": 1, "parameters": 0, "sheets": 0} and payload["output"] == str(out)
    assert out.exists()
    assert main(["prune", path, "--write", "-o", str(out)]) == 2          # exists
    assert "refusing to overwrite" in capsys.readouterr().err


def test_cli_option_errors(tmp_path, capsys):
    path = workbook(tmp_path, calcs=CALC)
    for argv in (["prune", path, "--write"], ["prune", path, "-o", str(tmp_path / "x.twb")],
                 ["prune", path, "--overwrite"]):
        with pytest.raises(SystemExit) as e:
            main(argv)
        assert e.value.code == 2
    assert main(["prune", str(tmp_path / "missing.twb")]) == 2
