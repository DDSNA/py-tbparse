"""Dashboard scaffolds (WP16a/16b): unit tests on a small workbook, then every corpus workbook.

Nothing here opens Tableau; the schema and reference checks are what we have."""

import json
import sys
import zipfile
from pathlib import Path

import pytest
from lxml import etree

sys.path.insert(0, str(Path(__file__).parent))
from schema_check import new_schema_errors  # noqa: E402

from py_tbparse import (  # noqa: E402
    ScaffoldError, TwbParser, apply_scaffold, integrity_check, load_scaffold, make_scaffold, save_scaffold,
)
from py_tbparse.cli import main  # noqa: E402
from py_tbparse.dashboards import zone_kind  # noqa: E402
from py_tbparse.scaffold import build_scaffold_workbook, scaffold_dropped, scaffold_plan, scaffold_slots  # noqa: E402

CORPUS = Path(__file__).parent / "corpus" / "files"
FILES = sorted(CORPUS.glob("*.twb")) if CORPUS.is_dir() else []

_FCP_T = "_.fcp.SetMembershipControl.true...type-v2"
_FCP_F = "_.fcp.SetMembershipControl.false...type"
STYLE = '<zone-style><format attr="margin" value="4"/></zone-style>'

SOURCE = f"""<?xml version='1.0' encoding='utf-8' ?>
<workbook version="18.1">
  <worksheets><worksheet name="Sales"/><worksheet name="Profit"/><worksheet name="Map"/></worksheets>
  <dashboards>
    <dashboard name="Overview" _.fcp.AccessibleZoneTabOrder.true...enable-sort-zone-taborder="true">
      <layout-options><title><formatted-text><run>Overview</run></formatted-text></title></layout-options>
      <style/>
      <size maxheight="800" maxwidth="1000" minheight="800" minwidth="1000" sizing-mode="fixed"/>
      <datasources><datasource name="ds"/></datasources>
      <zones>
        <zone id="10" type-v2="layout-basic" x="0" y="0" w="100000" h="100000">
          <zone id="11" type-v2="title" x="0" y="0" w="100000" h="8000">{STYLE}</zone>
          <zone id="12" {_FCP_T}="layout-flow" {_FCP_F}="layout-flow" param="horz" x="0" y="8000" w="100000" h="92000">
            <zone id="13" type-v2="layout-basic" x="0" y="8000" w="70000" h="92000">
              <zone id="14" name="Sales" x="0" y="8000" w="70000" h="50000" show-title="false">{STYLE}<layout-cache/></zone>
              <zone id="15" name="Profit" param="[ds].[set]" x="0" y="58000" w="70000" h="42000"/>
            </zone>
            <zone id="16" type-v2="layout-flow" param="vert" is-fixed="true" fixed-size="200" x="70000" y="8000" w="30000" h="92000">
              <zone id="17" name="Sales" param="[ds].[region]" type-v2="filter" x="70000" y="8000" w="30000" h="20000"/>
              <zone id="18" name="Sales" param="[ds].[c]" {_FCP_T}="color" {_FCP_F}="color" x="70000" y="28000" w="30000" h="20000"/>
              <zone id="19" type-v2="text" x="70000" y="48000" w="30000" h="10000"><formatted-text><run fontsize="12"> Notes </run></formatted-text></zone>
              <zone id="20" type-v2="empty" x="70000" y="58000" w="30000" h="5000"/>
              <zone id="21" param="C:/img/logo.png" type-v2="bitmap" x="70000" y="63000" w="30000" h="10000"/>
            </zone>
            <zone id="22" type-v2="layout-flow" param="vert" x="0" y="0" w="1" h="1">
              <zone id="23" name="Map" param="[ds].[x]" type-v2="filter" x="0" y="0" w="1" h="1"/>
            </zone>
          </zone>
        </zone>
      </zones>
      <devicelayouts><devicelayout name="Phone"><zones><zone id="30" type-v2="layout-flow"/></zones></devicelayout></devicelayouts>
      <simple-id uuid="{{11111111-1111-1111-1111-111111111111}}"/>
    </dashboard>
    <dashboard name="Floating">
      <zones><zone id="1" type-v2="layout-basic"><zone id="2" name="Sales"/></zone><zone id="3" name="Map"/></zones>
    </dashboard>
    <dashboard name="Legacy"><zones><zone id="1" name="Sales"/></zones></dashboard>
    <dashboard name="Story" type="storyboard"><zones><zone id="1" type-v2="layout-basic"/></zones></dashboard>
  </dashboards>
  <windows>
    <window class="worksheet" name="Sales"><simple-id uuid="{{22222222-2222-2222-2222-222222222222}}"/></window>
    <window class="dashboard" name="Overview"><viewpoints><viewpoint name="Sales"/></viewpoints><active id="14"/>
      <simple-id uuid="{{33333333-3333-3333-3333-333333333333}}"/></window>
  </windows>
</workbook>
"""


@pytest.fixture
def wb_path(tmp_path):
    p = tmp_path / "src.twb"
    p.write_text(SOURCE, encoding="utf-8")
    return p


@pytest.fixture
def scaffold(wb_path):
    return make_scaffold(wb_path, "Overview")


def _doc(data: bytes):
    return etree.fromstring(data).getroottree()


def _dash(doc, name):
    return doc.xpath("/workbook/dashboards/dashboard[@name=$n]", n=name)[0]


# --- make ---

def test_make_keeps_slots_and_lists_everything_dropped(scaffold):
    assert [(s["slot"], s["hint"], s["w"], s["h"]) for s in scaffold["slots"]] == [
        (1, "Sales", "70000", "50000"), (2, "Profit", "70000", "42000")]
    dropped = [(d["kind"], d["id"]) for d in scaffold["dropped"]]
    assert ("filter", "17") in dropped and ("color", "18") in dropped and ("bitmap", "21") in dropped
    assert ("filter", "23") in dropped and ("layout-flow", "22") in dropped      # the container the filter emptied
    assert ("sheet-control", "15") in dropped
    kinds = {k for k, _ in dropped}
    assert {"devicelayouts", "datasources"} <= kinds
    assert not any(k in ("text", "title", "empty") for k, _ in dropped)


def test_make_stores_dashboard_level_parts(scaffold):
    assert set(scaffold["dashboard"]) == {"layout-options", "style", "size"}
    assert scaffold["attributes"] == {"_.fcp.AccessibleZoneTabOrder.true...enable-sort-zone-taborder": "true"}
    assert scaffold["name"] == "Overview" and scaffold["source"] == {"dashboard": "Overview"}


def test_make_needs_the_dashboard_name_unless_there_is_one(wb_path):
    with pytest.raises(ScaffoldError, match="name the dashboard"):
        make_scaffold(wb_path)
    with pytest.raises(ScaffoldError, match="no dashboard named"):
        make_scaffold(wb_path, "Nope")


@pytest.mark.parametrize("name, message", [
    ("Floating", "2 top-level zones"), ("Legacy", "no tiled root"), ("Story", "storyboard")])
def test_make_refuses_what_the_first_slice_does_not_cover(wb_path, name, message):
    with pytest.raises(ScaffoldError, match=message):
        make_scaffold(wb_path, name)


def test_make_refuses_a_layout_with_no_sheet(tmp_path):
    p = tmp_path / "w.twb"
    p.write_text('<workbook><worksheets/><dashboards><dashboard name="D"><zones><zone id="1" type-v2="layout-basic">'
                 '<zone id="2" type-v2="text"/></zone></zones></dashboard></dashboards></workbook>')
    with pytest.raises(ScaffoldError, match="no sheet zone"):
        make_scaffold(p, "D")


def test_save_and_load_round_trip(tmp_path, scaffold):
    path = save_scaffold(scaffold, tmp_path / "o.scaffold.json")
    assert load_scaffold(path) == scaffold
    with pytest.raises(FileExistsError):
        save_scaffold(scaffold, path)
    save_scaffold(scaffold, path, overwrite=True)
    (tmp_path / "bad.json").write_text("{}")
    with pytest.raises(ScaffoldError, match="not a py-tbparse-scaffold"):
        load_scaffold(tmp_path / "bad.json")
    (tmp_path / "bad2.json").write_text(json.dumps({**scaffold, "version": 9}))
    with pytest.raises(ScaffoldError, match="version"):
        load_scaffold(tmp_path / "bad2.json")


def test_slot_and_dropped_tables(scaffold):
    assert scaffold_slots(scaffold)["hint"].tolist() == ["Sales", "Profit"]
    assert "filter" in scaffold_dropped(scaffold)["kind"].tolist()


# --- apply ---

def _apply(wb_path, scaffold, **kw):
    kw.setdefault("sheets", ["Profit", "Map"])
    report = kw.pop("report", {})
    return build_scaffold_workbook(TwbParser(str(wb_path)), scaffold, kw.pop("name", "New"), report=report, **kw)


def test_apply_makes_a_new_dashboard_and_leaves_the_rest_alone(wb_path, scaffold):
    out = _apply(wb_path, scaffold)
    doc = _doc(out)
    src = etree.parse(str(wb_path))
    new = _dash(doc, "New")
    assert [d.get("name") for d in doc.xpath("//dashboards/dashboard")] == ["Overview", "Floating", "Legacy", "Story", "New"]
    assert etree.tostring(_dash(doc, "Overview")) == etree.tostring(_dash(src, "Overview"))
    zones = new.xpath("./zones//zone")
    assert [z.get("id") for z in zones] == [str(i) for i in range(1, len(zones) + 1)]
    assert [zone_kind(z) for z in zones] == ["layout-basic", "title", "layout-flow", "layout-basic", "sheet", "sheet",
                                             "layout-flow", "text", "empty"]
    assert [z.get("name") for z in zones if zone_kind(z) == "sheet"] == ["Profit", "Map"]
    assert not new.xpath(".//zone[@slot]")


def test_apply_keeps_geometry_styles_text_and_dashboard_parts(wb_path, scaffold):
    new = _dash(_doc(_apply(wb_path, scaffold)), "New")
    assert [c.tag for c in new] == ["layout-options", "style", "size", "zones", "simple-id"]
    assert new.find("size").get("sizing-mode") == "fixed"
    assert new.get("_.fcp.AccessibleZoneTabOrder.true...enable-sort-zone-taborder") == "true"
    first = new.xpath(".//zone[@name='Profit']")[0]
    assert first.get("w") == "70000" and first.get("h") == "50000"
    assert first.get("show-title") == "false"
    assert first.find("zone-style") is not None and first.find("layout-cache") is None
    assert first.get("param") is None                        # the set control is not kept
    flow = new.xpath(".//zone[@fixed-size='200']")[0]
    assert flow.get("is-fixed") == "true" and flow.get("param") == "vert" and zone_kind(flow) == "layout-flow"
    assert new.xpath(".//zone[@type-v2='text']/formatted-text/run")[0].text == " Notes "     # text kept exactly
    assert not new.xpath(".//zone[@type-v2='filter' or @type-v2='bitmap' or @type-v2='color']")
    assert new.find("devicelayouts") is None and new.find("datasource-dependencies") is None


def test_apply_writes_window_and_fresh_uuids(wb_path, scaffold):
    report = {}
    doc = _doc(_apply(wb_path, scaffold, report=report))
    new = _dash(doc, "New")
    win = doc.xpath("//window[@class='dashboard'][@name='New']")[0]
    assert [v.get("name") for v in win.xpath("./viewpoints/viewpoint")] == ["Profit", "Map"]
    d_uuid, w_uuid = new.find("simple-id").get("uuid"), win.find("simple-id").get("uuid")
    assert d_uuid != w_uuid and (d_uuid, w_uuid) == (report["dashboard_uuid"], report["window_uuid"])
    all_uuids = doc.xpath("//simple-id/@uuid")
    assert len(all_uuids) == len(set(all_uuids))
    assert d_uuid.startswith("{") and d_uuid.endswith("}") and d_uuid == d_uuid.upper()
    assert report["zones"] == 9 and report["slots"] == {1: "Profit", 2: "Map"}
    assert integrity_check(doc, dashboard="New", require_window=True) == []
    assert integrity_check(doc) == []


def test_two_applies_give_different_uuids(wb_path, scaffold):
    a, b = (_doc(_apply(wb_path, scaffold)).xpath("//dashboard[@name='New']/simple-id/@uuid")[0] for _ in range(2))
    assert a != b


def test_apply_to_the_source_sheets_reproduces_the_kept_layout(wb_path, scaffold):
    doc = _doc(_apply(wb_path, scaffold, sheets=["Sales", "Profit"], name="Copy"))

    def shape(db):
        return [(zone_kind(z), z.get("name") if zone_kind(z) == "sheet" else None, z.get("x"), z.get("y"), z.get("w"),
                 z.get("h")) for z in db.xpath("./zones//zone") if zone_kind(z) not in ("filter", "color", "bitmap")
                and z.get("id") not in ("22",)]
    assert shape(_dash(doc, "Copy")) == shape(_dash(doc, "Overview"))


def test_apply_with_a_dict_and_a_blank_slot(wb_path, scaffold):
    with pytest.raises(ScaffoldError, match="no sheet for slot 1"):
        _apply(wb_path, scaffold, sheets={2: "Map"})
    doc = _doc(_apply(wb_path, scaffold, sheets={"2": "Map"}, allow_empty=True))
    new = _dash(doc, "New")
    assert [zone_kind(z) for z in new.xpath(".//zone")][4:6] == ["empty", "sheet"]
    blank = new.xpath(".//zone[@type-v2='empty']")[0]
    assert set(blank.attrib) == {"id", "type-v2", "x", "y", "w", "h"}
    assert [v.get("name") for v in doc.xpath("//window[@name='New']//viewpoint")] == ["Map"]
    assert integrity_check(doc, dashboard="New", require_window=True) == []


@pytest.mark.parametrize("kw, message", [
    (dict(sheets=["Sales"]), "no sheet for slot 2"),
    (dict(sheets=["Sales", "Profit", "Map"]), "3 sheets given for 2"),
    (dict(sheets=["Sales", "Nope"]), "not a worksheet"),
    (dict(sheets=["Sales", "Sales"]), "only one slot"),
    (dict(sheets=["Sales", "Profit"], name="Overview"), "already the name"),
    (dict(sheets=["Sales", "Profit"], name="Sales"), "already the name"),
    (dict(sheets=["Sales", "Profit"], name="  "), "needs a name"),
    (dict(sheets={3: "Sales"}), "slot 3 does not exist"),
    (dict(sheets={"x": "Sales"}), "not a slot number"),
    (dict(sheets=[], allow_empty=True), "no sheet chosen"),
])
def test_apply_refuses_bad_requests(wb_path, scaffold, kw, message):
    with pytest.raises(ScaffoldError, match=message):
        _apply(wb_path, scaffold, **kw)


def test_apply_writes_a_new_file_and_never_over_the_input(wb_path, scaffold, tmp_path):
    out = apply_scaffold(wb_path, scaffold, "New", ["Sales", "Map"])
    assert Path(out) == tmp_path / "src_scaffold.twb"
    with pytest.raises(FileExistsError):
        apply_scaffold(wb_path, scaffold, "New", ["Sales", "Map"])
    with pytest.raises(FileExistsError):
        apply_scaffold(wb_path, scaffold, "New", ["Sales", "Map"], output_path=str(wb_path), overwrite=True)
    with pytest.raises(ScaffoldError, match="must end in"):
        apply_scaffold(wb_path, scaffold, "New", ["Sales", "Map"], output_path=str(tmp_path / "x.twbx"))
    assert wb_path.read_text(encoding="utf-8") == SOURCE
    assert TwbParser(out).xml_doc.xpath("//dashboard[@name='New']")


def test_twbx_keeps_other_members(tmp_path, scaffold):
    src = tmp_path / "p.twbx"
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("p.twb", SOURCE)
        z.writestr("Data/x.csv", "a,b\n1,2\n")
    out = apply_scaffold(str(src), scaffold, "New", ["Sales", "Map"])
    with zipfile.ZipFile(out) as z:
        assert z.read("Data/x.csv") == b"a,b\n1,2\n"
        assert b'name="New"' in z.read("p.twb")


def test_a_workbook_without_dashboards_or_windows_gets_both(tmp_path, scaffold):
    p = tmp_path / "bare.twb"
    p.write_text('<workbook><worksheets><worksheet name="A"/><worksheet name="B"/></worksheets><windows/></workbook>')
    doc = _doc(_apply(p, scaffold, sheets=["A", "B"]))
    assert [c.tag for c in doc.getroot()] == ["worksheets", "dashboards", "windows"]
    assert integrity_check(doc, require_window=True) == []


def test_plan_lists_each_slot(wb_path, scaffold):
    plan = scaffold_plan(wb_path, scaffold, "New", {2: "Map"}, allow_empty=True)
    assert plan.to_dict("records") == [{"slot": 1, "hint": "Sales", "sheet": "(blank)"},
                                       {"slot": 2, "hint": "Profit", "sheet": "Map"}]


def test_schema_check_on_a_small_workbook(wb_path, scaffold):
    out = _apply(wb_path, scaffold)
    assert new_schema_errors(wb_path, out) == []


# --- command line ---

def test_cli_make_show_apply(wb_path, tmp_path, capsys):
    sc = tmp_path / "o.scaffold.json"
    assert main(["scaffold", "make", str(wb_path), "-d", "Overview", "-o", str(sc)]) == 0
    assert main(["scaffold", "make", str(wb_path), "-d", "Overview", "-o", str(sc)]) == 1      # exists
    capsys.readouterr()
    assert main(["scaffold", "show", str(sc)]) == 0
    shown = capsys.readouterr().out
    assert "Sales" in shown and "bitmap" in shown and "devicelayouts" in shown
    assert main(["scaffold", "show", str(sc), "--format", "json"]) == 0
    assert len(json.loads(capsys.readouterr().out)["slots"]) == 2
    out = tmp_path / "out.twb"
    assert main(["scaffold", "apply", str(wb_path), str(sc), "--name", "N", "--sheets", "Sales,Map"]) == 0
    assert not out.exists() and not (tmp_path / "src_scaffold.twb").exists()                   # plan only
    assert main(["scaffold", "apply", str(wb_path), str(sc), "--name", "N", "--sheet", "Sales", "--sheet", "Map",
                 "-o", str(out), "--write"]) == 0
    assert TwbParser(str(out)).xml_doc.xpath("//dashboard[@name='N']")
    capsys.readouterr()
    assert main(["scaffold", "apply", str(wb_path), str(sc), "--name", "N", "--sheets", "Sales"]) == 1
    assert "no sheet for slot 2" in capsys.readouterr().err
    assert main(["scaffold", "make", str(wb_path), "-d", "Floating", "-o", str(tmp_path / "f.json")]) == 1


# --- the corpus ---

@pytest.mark.skipif(not FILES, reason="corpus not fetched: python scripts/fetch_corpus.py")
def test_corpus_make_and_apply_never_raise_and_pass_the_checks():
    made = refused = 0
    schema_checked = 0
    for f in FILES:
        parser = TwbParser(str(f))
        before = None
        sheets = list(dict.fromkeys(parser.xml_doc.xpath("/workbook/worksheets/worksheet/@name")))
        for name in parser.xml_doc.xpath("/workbook/dashboards/dashboard/@name"):
            try:
                sc = make_scaffold(parser, name)
            except ScaffoldError:
                refused += 1
                continue
            made += 1
            chosen = sheets[:len(sc["slots"])]
            data = build_scaffold_workbook(parser, sc, "Scaffold Test", chosen, allow_empty=True)
            doc = _doc(data)
            assert integrity_check(doc, dashboard="Scaffold Test", require_window=True) == [], (f.name, name)
            if chosen:
                before = before or f.read_bytes()
                # a source with no <windows> at all had "expected: windows" as its root error; ours now has a
                # window, so the same gap reads "expected: thumbnails ..." (the file stays as incomplete as it was)
                new = [e for e in new_schema_errors(before, data)
                       if not (e[0] == "/workbook" and e[1].startswith("Element 'workbook': Missing child"))]
                assert new == [], (f.name, name)
                schema_checked += 1
            ids = [int(z.get("id")) for z in _dash(doc, "Scaffold Test").xpath("./zones//zone")]
            assert ids == list(range(1, len(ids) + 1))
    assert made > 50 and refused > 20 and schema_checked == made
