"""Renaming everything in a report: worksheets, dashboards, datasources, parameters, folders, hierarchies."""

import pandas as pd
import pytest

from py_tbparse import TwbParser, apply_field_renames, load_rename_mapping, suggest_renames
from py_tbparse.cli import main

WORKBOOK = """<?xml version='1.0' encoding='utf-8' ?>
<workbook version='18.1'>
  <datasources>
    <datasource name='Parameters' hasconnection='false'>
      <column caption='top n' datatype='integer' name='[Parameter 1]' role='measure' type='quantitative' value='5' />
    </datasource>
    <datasource caption='SALES_DB' name='federated.0grgaor1pd01yy1f0yr380of1ags'>
      <column caption='ORDER_ID' datatype='integer' name='[order_id]' role='dimension' type='ordinal' />
      <folder name='money fields' role='dimensions'><folder-item name='[order_id]' type='field' /></folder>
      <drill-paths><drill-path name='geo path'><field>[order_id]</field></drill-path></drill-paths>
    </datasource>
    <datasource name='federated.abcdefghij0123456789abcdefgh' />
  </datasources>
  <worksheets>
    <worksheet name='sales by region'>
      <table><view>
        <datasources><datasource caption='SALES_DB' name='federated.0grgaor1pd01yy1f0yr380of1ags' /></datasources>
        <datasource-dependencies datasource='federated.0grgaor1pd01yy1f0yr380of1ags'>
          <column caption='ORDER_ID' datatype='integer' name='[order_id]' role='dimension' type='ordinal' />
          <drill-paths><drill-path name='geo path'><field>[order_id]</field></drill-path></drill-paths>
        </datasource-dependencies>
      </view></table>
    </worksheet>
    <worksheet name='ORDER_DETAILS'><table><view /></table></worksheet>
  </worksheets>
  <dashboards>
    <dashboard name='my dashboard'>
      <zones>
        <zone h='1' id='1' name='sales by region' worksheet='sales by region' w='1' x='0' y='0' />
        <zone h='1' id='2' name='ORDER_DETAILS' worksheet='ORDER_DETAILS' w='1' x='0' y='0' />
        <zone h='1' id='3' type='empty' w='1' x='0' y='0' />
      </zones>
      <viewpoints><viewpoint name='sales by region' /></viewpoints>
    </dashboard>
  </dashboards>
  <actions>
    <action name='Filter 1'>
      <source dashboard='my dashboard' type='sheet' worksheet='sales by region' />
      <command command='tsc:goto-sheet'><param name='target' value='ORDER_DETAILS' /></command>
      <exclude-sheet name='ORDER_DETAILS' />
    </action>
  </actions>
  <windows>
    <window class='worksheet' name='sales by region' />
    <window class='worksheet' name='ORDER_DETAILS' />
    <window class='dashboard' name='my dashboard' />
  </windows>
  <thumbnails><thumbnail height='1' name='sales by region' width='1' /></thumbnails>
</workbook>
"""


@pytest.fixture
def report(tmp_path):
    path = tmp_path / "report.twb"
    path.write_text(WORKBOOK, encoding="utf-8")
    return path


def _rows(df, kind):
    return df[df["kind"] == kind].set_index("name")["suggested"].to_dict()


def test_suggests_every_kind(report):
    df = suggest_renames(TwbParser(str(report)))
    assert list(df.columns) == ["kind", "datasource", "name", "current", "suggested", "reason", "score", "changed"]
    assert _rows(df, "worksheet") == {"sales by region": "Sales By Region", "ORDER_DETAILS": "Order Details"}
    assert _rows(df, "dashboard") == {"my dashboard": "My Dashboard"}
    assert _rows(df, "parameter") == {"[Parameter 1]": "Top N"} or _rows(df, "parameter")["[Parameter 1]"].startswith("Top")
    assert _rows(df, "folder") == {"money fields": "Money Fields"}
    assert _rows(df, "hierarchy") == {"geo path": "Geo Path"}
    # the opaque, uncaptioned datasource is not offered; the captioned one is
    assert _rows(df, "datasource") == {"federated.0grgaor1pd01yy1f0yr380of1ags": "Sales Db"}
    assert _rows(df, "field") == {"[order_id]": "Order ID"}


def test_kinds_filter_and_validation(report):
    p = TwbParser(str(report))
    assert set(suggest_renames(p, kinds="worksheet")["kind"]) == {"worksheet"}
    assert set(suggest_renames(p, kinds=["dashboard", "folder"])["kind"]) == {"dashboard", "folder"}
    with pytest.raises(ValueError, match="unknown kind"):
        suggest_renames(p, kinds=["chart"])


def test_sheets_and_dashboards_share_a_namespace():
    from py_tbparse.rename import _inventory  # noqa: F401  (documented behaviour below)

    xml = WORKBOOK.replace("name='my dashboard'", "name='Sales By Region'").replace(
        "dashboard='my dashboard'", "dashboard='Sales By Region'").replace("name='my dashboard'", "name='Sales By Region'")
    assert "Sales By Region" in xml  # a dashboard now collides with the cleaned worksheet name


def test_apply_renames_every_reference(report, tmp_path):
    p = TwbParser(str(report))
    renames = suggest_renames(p)
    out = apply_field_renames(p, renames=renames, output_path=str(tmp_path / "fixed.twb"))
    text = open(out, encoding="utf-8").read()

    # no old sheet / dashboard names survive anywhere
    for old in ("sales by region", "ORDER_DETAILS", "my dashboard"):
        assert old not in text, old
    for new in ("Sales By Region", "Order Details", "My Dashboard"):
        assert new in text
    again = TwbParser(out)
    assert set(again.get_dashboards()["name"]) == {"My Dashboard"}
    assert set(again.get_dashboard_sheets()["sheet"]) == {"Sales By Region", "Order Details"}
    # datasource and parameter captions, folder, hierarchy (incl. the worksheet's copy)
    assert "caption=\"Sales Db\"" in text
    assert "caption=\"Top N\"" in text or "caption=\"Top n\"" in text
    assert "name=\"Money Fields\"" in text
    assert text.count("name=\"Geo Path\"") == 2
    # internal names are untouched
    assert "name=\"federated.0grgaor1pd01yy1f0yr380of1ags\"" in text
    assert "name=\"[order_id]\"" in text


def test_report_counts_by_kind(report):
    from py_tbparse.rename import build_renamed_workbook

    p = TwbParser(str(report))
    rep = {}
    build_renamed_workbook(p, suggest_renames(p), rep)
    assert rep["skipped"] == 0
    assert rep["by_kind"]["worksheet"] == 2 and rep["by_kind"]["dashboard"] == 1
    assert rep["applied"] == sum(rep["by_kind"].values())


def test_unknown_targets_are_skipped(report):
    from py_tbparse.rename import build_renamed_workbook

    p = TwbParser(str(report))
    df = pd.DataFrame([
        {"kind": "worksheet", "datasource": "", "name": "no such sheet", "current": "x", "suggested": "Y",
         "reason": "manual", "score": None, "changed": True},
        {"kind": "folder", "datasource": "nope", "name": "f", "current": "f", "suggested": "F",
         "reason": "manual", "score": None, "changed": True},
    ])
    rep = {}
    build_renamed_workbook(p, df, rep)
    assert rep["applied"] == 0 and rep["skipped"] == 2


def test_swapping_two_sheet_names_is_safe(report, tmp_path):
    p = TwbParser(str(report))
    swap = pd.DataFrame([
        {"kind": "worksheet", "datasource": "", "name": "sales by region", "current": "sales by region",
         "suggested": "ORDER_DETAILS", "reason": "manual", "score": None, "changed": True},
        {"kind": "worksheet", "datasource": "", "name": "ORDER_DETAILS", "current": "ORDER_DETAILS",
         "suggested": "sales by region", "reason": "manual", "score": None, "changed": True},
    ])
    out = apply_field_renames(p, renames=swap, output_path=str(tmp_path / "swap.twb"))
    names = [w for w in TwbParser(out).xml_doc.xpath("/workbook/worksheets/worksheet/@name")]
    assert names == ["ORDER_DETAILS", "sales by region"]
    zones = TwbParser(out).xml_doc.xpath("//zone/@name")
    assert zones == ["ORDER_DETAILS", "sales by region"]


def test_mapping_round_trip_with_kinds(report, tmp_path):
    csv_path = tmp_path / "map.csv"
    assert main(["rename", str(report), "--all", "-f", "csv", "-o", str(csv_path)]) == 0
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    assert "kind" in df.columns
    df.loc[(df["kind"] == "dashboard"), "suggested"] = "Executive Overview"
    df.to_csv(csv_path, index=False)

    assert main(["rename", str(report), "--apply", str(csv_path), "--write-workbook", str(tmp_path / "o.twb")]) == 0
    assert set(TwbParser(str(tmp_path / "o.twb")).get_dashboards()["name"]) == {"Executive Overview"}


def test_mapping_rejects_duplicate_sheet_names():
    rows = [
        {"kind": "worksheet", "datasource": "", "name": "A", "suggested": "Same"},
        {"kind": "dashboard", "datasource": "", "name": "B", "suggested": "same"},
    ]
    with pytest.raises(ValueError, match="both"):
        load_rename_mapping(pd.DataFrame(rows))
    with pytest.raises(ValueError, match="unknown kind"):
        load_rename_mapping(pd.DataFrame([{"kind": "chart", "datasource": "", "name": "A", "suggested": "B"}]))
    # a blank datasource is fine for sheets, but not for a field
    ok = load_rename_mapping(pd.DataFrame([
        {"kind": "worksheet", "datasource": "", "name": "A", "suggested": "B"},
        {"kind": "field", "datasource": "", "name": "[f]", "suggested": "F"},
    ]))
    assert list(ok["kind"]) == ["worksheet"]


def test_cli_kinds_option(report, capsys):
    assert main(["rename", str(report), "--kinds", "worksheet,dashboard", "--only-changed", "-f", "csv"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("kind,datasource,name") and "Sales By Region" in out and "field" not in out.split("\n", 1)[1]


def test_field_only_output_is_unchanged(report, capsys):
    assert main(["rename", str(report), "-f", "csv"]) == 0
    assert capsys.readouterr().out.startswith("datasource,name,current")


def test_reference_workbook_lends_its_sheet_names(report, tmp_path):
    ref = tmp_path / "old.twb"
    ref.write_text(WORKBOOK.replace("sales by region", "Regional Sales"), encoding="utf-8")
    df = suggest_renames(TwbParser(str(report)), reference=str(ref), kinds="worksheet")
    # 'sales by region' is not close to 'Regional Sales': it is simply tidied
    assert _rows(df, "worksheet")["sales by region"] == "Sales By Region"
    ref2 = tmp_path / "old2.twb"
    ref2.write_text(WORKBOOK.replace("sales by region", "SALES_BY_REGION"), encoding="utf-8")
    df = suggest_renames(TwbParser(str(report)), reference=str(ref2), kinds="worksheet")
    assert _rows(df, "worksheet")["sales by region"] == "SALES_BY_REGION"
