"""WP14b: the shared core of `sheet copy`, on small synthetic workbooks. Nothing here opens Tableau."""

import copy
import sys
from pathlib import Path

import pytest
from lxml import etree

sys.path.insert(0, str(Path(__file__).parent))

from py_tbparse import TwbParser  # noqa: E402
from py_tbparse.sheetcopy_core import (  # noqa: E402
    SheetCopyError, add_window, compare_to_target, connection_signature, copy_sheet_element, copy_window,
    dependency_closure, match_datasource, new_uuid, renew_uuids, rewrite_references, sheet_datasources,
)

DS = "federated.aaa"
SALES = "<metadata-record class='column'><local-name>[Sales]</local-name><local-type>real</local-type></metadata-record>"
REGION = ("<metadata-record class='column'><local-name>[Region]</local-name>"
          "<local-type>string</local-type></metadata-record>")
CALCS = """<column name='[Double]' caption='Double' datatype='real' role='measure'>
    <calculation class='tableau' formula='{double}'/></column>
  <column name='[Ratio]' datatype='real' role='measure'>
    <calculation class='tableau' formula='[Double] / [Parameters].[Parameter 1] + "[Sales]"'/></column>"""


def datasource(name=DS, path="C:/data/orders.xlsx", calc_formula="[Sales] * 2", sales=True, calcs=True):
    return f"""<datasource name='{name}' caption='Orders'>
  <connection class='federated'><named-connections><named-connection name='x'>
    <connection class='excel-direct' filename='{path}'/></named-connection></named-connections>
    <relation name='Orders' table='[Orders$]' type='table'/>
    <metadata-records>{SALES if sales else ""}{REGION}</metadata-records></connection>
  <column name='[Region]' datatype='string' role='dimension'/>
  {CALCS.format(double=calc_formula) if calcs else ""}
  <column name='[Size]' datatype='integer' role='dimension'><calculation class='bin' decimals='0' formula='[Sales]'
    column='[Sales]' peg='0' value='10'/></column>
  <group name='[Top]' caption='Top'><groupfilter function='member' level='[Region]' member='&quot;East&quot;'/></group>
  <group name='[Action (Region)]'/>
</datasource>"""


PARAMS = """<datasource name='Parameters' hasconnection='false'>
  <column name='[Parameter 1]' caption='Rate' datatype='real' param-domain-type='any' role='measure' value='2'>
    <calculation class='tableau' formula='2'/></column></datasource>"""

SHEET = f"""<worksheet name='Sheet 1'><table><view>
  <datasources><datasource name='Parameters'/><datasource caption='Orders' name='{DS}'/></datasources>
  <datasource-dependencies datasource='{DS}'>
    <column name='[Region]' datatype='string' role='dimension'/>
    <column name='[Ratio]' datatype='real' role='measure'>
      <calculation class='tableau' formula='[Double] / [Parameters].[Parameter 1]'/></column>
    <column-instance column='[Region]' derivation='None' name='[none:Region:nk]' pivot='key' type='nominal'/>
    <column-instance column='[Ratio]' derivation='Sum' name='[sum:Ratio:qk]' pivot='key' type='quantitative'/>
  </datasource-dependencies>
  <datasource-dependencies datasource='Parameters'>
    <column name='[Parameter 1]' datatype='real' role='measure'><calculation class='tableau' formula='2'/></column>
  </datasource-dependencies>
  <filter class='categorical' column='[{DS}].[none:Region:nk]'><groupfilter function='member' level='[{DS}].[none:Region:nk]'
    member='&quot;[{DS}].[avg:Ratio:qk]&quot;'/></filter>
  <filter class='categorical' column='[{DS}].[Action (Region)]'/>
  <slices><column>[{DS}].[none:Region:nk]</column></slices>
</view>
<rows>[{DS}].[sum:Ratio:qk]</rows><cols>[{DS}].[none:Region:nk]</cols></table>
<simple-id uuid='{{11111111-1111-1111-1111-111111111111}}'/></worksheet>"""


def workbook(ds=None, sheet=SHEET, extra_ds="", windows=True):
    win = ("<windows><window class='worksheet' name='Sheet 1' hidden='true'><viewpoints/>"
           "<simple-id uuid='{22222222-2222-2222-2222-222222222222}'/></window></windows>") if windows else ""
    return (f"<?xml version='1.0' encoding='utf-8' ?><workbook version='18.1'><datasources>{PARAMS}"
            f"{ds if ds is not None else datasource()}{extra_ds}</datasources><worksheets>{sheet}</worksheets>"
            f"{win}</workbook>")


def load(tmp_path, text, name="wb.twb"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return TwbParser(str(p)).xml_doc


# --------------------------------------------------------------- closure --

def test_closure_follows_calcs_parameters_bins_groups_from_the_datasource(tmp_path):
    doc = load(tmp_path, workbook())
    c = dependency_closure(doc, "Sheet 1")
    assert c.datasource == DS
    # [Double] and [Sales] are not in the sheet's cached copy, only the datasource knows them
    assert c.calcs == ["[Double]", "[Ratio]"]
    assert c.parameters == ["[Parameter 1]"]
    assert "[Sales]" in c.fields and "[Region]" in c.fields
    assert c.action_groups == ["[Action (Region)]"]
    assert c.unresolved == [] and c.cross_datasource == []


def test_closure_of_bins_and_groups(tmp_path):
    sheet = SHEET.replace("<rows>", f"<rows>[{DS}].[none:Size:ok] [{DS}].[none:Top:nk]")
    c = dependency_closure(load(tmp_path, workbook(sheet=sheet)), "Sheet 1")
    assert c.bins == ["[Size]"] and c.groups == ["[Top]"]
    assert "[Sales]" in c.fields       # through the bin's column


def test_string_literals_do_not_count_as_references(tmp_path):
    c = dependency_closure(load(tmp_path, workbook()), "Sheet 1")
    assert c.fields.count("[Sales]") == 1     # `"[Sales]"` in [Ratio]'s formula is text, [Double] uses it for real
    only_text = datasource(calc_formula="1").replace("[Sales]\"", "[Sales]\"")
    assert "[Sales]" not in dependency_closure(load(tmp_path, workbook(ds=only_text)), "Sheet 1").fields


def test_unresolved_name_and_blend_and_missing_sheet(tmp_path):
    sheet = SHEET.replace("<rows>", f"<rows>[{DS}].[sum:Ghost:qk]")
    assert dependency_closure(load(tmp_path, workbook(sheet=sheet)), "Sheet 1").unresolved == ["[Ghost]"]
    blend = SHEET.replace("</datasources>", "<datasource name='federated.bbb'/></datasources>")
    doc = load(tmp_path, workbook(sheet=blend), "b.twb")
    assert sheet_datasources(doc, "Sheet 1") == [DS, "federated.bbb"]
    with pytest.raises(SheetCopyError, match="blends"):
        dependency_closure(doc, "Sheet 1")
    assert dependency_closure(doc, "Sheet 1", datasource=DS).datasource == DS
    with pytest.raises(SheetCopyError, match="no worksheet"):
        dependency_closure(doc, "Nope")


def test_cross_datasource_reference_is_reported(tmp_path):
    ds = datasource(calc_formula="[Sales] + [other].[X]")
    c = dependency_closure(load(tmp_path, workbook(ds=ds)), "Sheet 1")
    assert c.cross_datasource == ["[other].[X]"]


# --------------------------------------------------------- compare to target --

def test_compare_to_target(tmp_path):
    src = load(tmp_path, workbook())
    c = dependency_closure(src, "Sheet 1")
    same = compare_to_target(src, c, src)
    assert same["identical"].count("[Double]") == 1 and not same["add"] and not same["clash"] and not same["missing"]
    dst = load(tmp_path, workbook(ds=datasource(calcs=False), sheet="<worksheet name='Other'/>"), "t.twb")
    res = compare_to_target(src, c, dst)
    assert "[Double]" in res["add"] and "[Ratio]" in res["add"] and "[Sales]" in res["present"]
    # a clash: same name, other formula
    other = load(tmp_path, workbook(ds=datasource(calc_formula="[Sales] * 3"), sheet="<worksheet name='O'/>"), "c.twb")
    res = compare_to_target(src, c, other)
    assert "[Double]" in res["clash"]
    assert "[Ratio]" in res["blocked"]      # same formula as the target's, but it would use the target's other [Double]


def test_compare_groups_by_members_not_by_name(tmp_path):
    sheet = SHEET.replace("<rows>", f"<rows>[{DS}].[none:Top:nk]")
    src = load(tmp_path, workbook(sheet=sheet))
    c = dependency_closure(src, "Sheet 1")
    assert "[Top]" in compare_to_target(src, c, src)["identical"]
    west = datasource().replace("&quot;East&quot;", "&quot;West&quot;")
    res = compare_to_target(src, c, load(tmp_path, workbook(ds=west, sheet="<worksheet name='O'/>"), "w.twb"))
    assert "[Top]" in res["clash"] and "[Top]" not in res["identical"]
    # a union lists its operands in any order
    union = ("<group name='[Top]' caption='Top'><groupfilter function='union'>"
             "<groupfilter function='member' level='[Region]' member='&quot;{a}&quot;'/>"
             "<groupfilter function='member' level='[Region]' member='&quot;{b}&quot;'/></groupfilter></group>")
    old = datasource().split("<group name='[Top]'")[1].split("</group>")[0]
    def with_union(a, b):
        return datasource().replace("<group name='[Top]'" + old + "</group>", union.format(a=a, b=b))
    u = load(tmp_path, workbook(ds=with_union("East", "West"), sheet=sheet), "u.twb")
    cu = dependency_closure(u, "Sheet 1")
    same = load(tmp_path, workbook(ds=with_union("West", "East"), sheet="<worksheet name='O'/>"), "u2.twb")
    assert "[Top]" in compare_to_target(u, cu, same)["identical"]
    other = load(tmp_path, workbook(ds=with_union("West", "North"), sheet="<worksheet name='O'/>"), "u3.twb")
    assert "[Top]" in compare_to_target(u, cu, other)["clash"]


def test_compare_missing_field(tmp_path):
    src = load(tmp_path, workbook())
    c = dependency_closure(src, "Sheet 1")
    dst = load(tmp_path, workbook(ds=datasource(sales=False), sheet="<worksheet name='O'/>"), "m.twb")
    res = compare_to_target(src, c, dst)
    assert "[Sales]" in res["missing"] and "[Double]" in res["blocked"]


# ---------------------------------------------------------- datasource match --

def test_signature_ignores_the_folder_and_credentials(tmp_path):
    a = load(tmp_path, workbook(ds=datasource(path="C:/one/orders.xlsx")))
    b = load(tmp_path, workbook(ds=datasource(path="/home/x/orders.xlsx")), "b.twb")
    other = load(tmp_path, workbook(ds=datasource(path="C:/one/people.xlsx")), "c.twb")
    sig = lambda d: connection_signature(d.xpath(f"/workbook/datasources/datasource[@name='{DS}']")[0])  # noqa: E731
    assert sig(a) == sig(b) != sig(other)
    assert sig(a)[1] == ("[Orders$]",)


def test_match_same_name_only(tmp_path):
    src = load(tmp_path, workbook())
    same = load(tmp_path, workbook(ds=datasource(path="/else/orders.xlsx")), "s.twb")
    assert match_datasource(src, DS, same) == DS
    renamed = load(tmp_path, workbook(ds=datasource(name="federated.zzz")), "r.twb")
    with pytest.raises(SheetCopyError, match="only the same internal name"):
        match_datasource(src, DS, renamed)
    assert match_datasource(src, DS, renamed, allow_rename=True) == "federated.zzz"
    nomatch = load(tmp_path, workbook(ds=datasource(path="people.xlsx")), "n.twb")
    with pytest.raises(SheetCopyError, match="no datasource with the connection"):
        match_datasource(src, DS, nomatch)
    two = load(tmp_path, workbook(extra_ds=datasource(name="federated.bbb")), "two.twb")
    with pytest.raises(SheetCopyError, match="2 datasources"):
        match_datasource(src, DS, two, allow_rename=True)
    assert match_datasource(src, DS, two, explicit=DS) == DS
    with pytest.raises(SheetCopyError, match="has no datasource 'nope'"):
        match_datasource(src, DS, two, explicit="nope")


def test_datasource_without_connection_never_matches_by_itself(tmp_path):
    bare = "<datasource name='federated.aaa'><column name='[A]' datatype='string'/></datasource>"
    doc = load(tmp_path, workbook(ds=bare))
    with pytest.raises(SheetCopyError, match="no connection"):
        match_datasource(doc, DS, doc)


# ------------------------------------------------------------------- rewriter --

def test_rewrite_prefix_names_instances_and_cached_copies(tmp_path):
    doc = load(tmp_path, workbook())
    ws = copy.deepcopy(doc.xpath("//worksheet")[0])
    n = rewrite_references(ws, {DS: "federated.new"}, {"[Region]": "[Area]", "[Ratio]": "[Rate]"},
                           {"[Parameter 1]": "[Parameter 3]"}, {DS: "Orders (2)"})
    assert n > 0
    text = etree.tostring(ws, encoding="unicode")
    assert DS not in text
    assert "[federated.new].[none:Area:nk]" in text and "[federated.new].[sum:Rate:qk]" in text
    assert "<rows>[federated.new].[sum:Rate:qk]</rows>" in text
    dep = ws.xpath("//datasource-dependencies[@datasource='federated.new']")[0]
    assert dep.xpath("column/@name") == ["[Area]", "[Rate]"]
    assert dep.xpath("column-instance/@column") == ["[Area]", "[Rate]"]
    assert dep.xpath("column-instance/@name") == ["[none:Area:nk]", "[sum:Rate:qk]"]
    assert "[Double] / [Parameters].[Parameter 3]" in text
    assert ws.xpath("//datasources/datasource[@name='federated.new']/@caption") == ["Orders (2)"]
    # the parameter copy: its own name is renamed through `params`
    assert ws.xpath("//datasource-dependencies[@datasource='Parameters']/column/@name") == ["[Parameter 3]"]
    # a reference inside a filter member's quotes (Measure Names members look like this) is a real one
    assert ws.xpath("//groupfilter/@member") == ['"[federated.new].[avg:Rate:qk]"']


def test_rewrite_formula_inside_dependency_copy_and_strings(tmp_path):
    ws = etree.fromstring(
        "<worksheet><view><datasource-dependencies datasource='d1'><column name='[C]'>"
        "<calculation class='tableau' formula='[A] + [d1].[A] + [Parameters].[P] + &quot;[A]&quot; + [other].[A]'/>"
        "</column></datasource-dependencies></view></worksheet>")
    rewrite_references(ws, {"d1": "d2"}, {"[A]": "[B]"}, {"[P]": "[Q]"})
    f = ws.xpath("//calculation/@formula")[0]
    assert f == '[B] + [d2].[B] + [Parameters].[Q] + "[A]" + [other].[A]'


def test_rewrite_only_touches_the_mapped_prefix(tmp_path):
    ws = etree.fromstring("<w><a x='[other].[none:Region:nk] [d1].[none:Region:nk]'>[other].[Region]</a>"
                          "<datasource-dependencies datasource='other'><column name='[Region]'/>"
                          "</datasource-dependencies></w>")
    rewrite_references(ws, {"d1": "d2"}, {"[Region]": "[Area]"})
    assert ws.find("a").get("x") == "[other].[none:Region:nk] [d2].[none:Area:nk]"
    assert ws.find("a").text == "[other].[Region]"
    assert ws.xpath("//column/@name") == ["[Region]"]


def test_identity_rewrite_changes_nothing(tmp_path):
    ws = copy.deepcopy(load(tmp_path, workbook()).xpath("//worksheet")[0])
    before = etree.tostring(ws)
    assert rewrite_references(ws) == 0
    assert etree.tostring(ws) == before


# ------------------------------------------------------- uuids and windows --

def test_new_uuid_and_renew(tmp_path):
    taken = {"{A}"}
    u = new_uuid(taken)
    assert u in taken and u.startswith("{") and u.endswith("}") and u == u.upper()
    el = etree.fromstring("<a><simple-id uuid='{X}'/><b><simple-id uuid='{Y}'/></b></a>")
    assert renew_uuids(el, taken) == 2
    assert not set(el.xpath("//@uuid")) & {"{X}", "{Y}"}


def test_copy_sheet_element_and_window(tmp_path):
    src = load(tmp_path, workbook())
    dst = load(tmp_path, workbook(sheet="<worksheet name='Keep'/>", windows=False), "d.twb")
    taken = set(src.xpath("//simple-id/@uuid"))
    ws = copy_sheet_element(src, "Sheet 1", "Sheet 1 (2)", taken, {DS: "federated.new"})
    assert ws.get("name") == "Sheet 1 (2)"
    assert ws.find("simple-id").get("uuid") != "{11111111-1111-1111-1111-111111111111}"
    assert "federated.aaa" not in etree.tostring(ws, encoding="unicode")
    win = copy_window(src, dst, "Sheet 1", "Sheet 1 (2)", taken)
    assert win.get("name") == "Sheet 1 (2)" and "hidden" not in win.attrib       # source was hidden
    assert win.find("simple-id").get("uuid") != "{22222222-2222-2222-2222-222222222222}"
    assert dst.xpath("/workbook/windows/window/@name") == ["Sheet 1 (2)"]
    hidden = copy_window(src, dst, "Sheet 1", "H", taken, hidden=True)
    assert hidden.get("hidden") == "true"
    assert copy_window(src, dst, "Nope", "X", taken) is None
    # the source is untouched
    assert src.xpath("/workbook/windows/window/@hidden") == ["true"]


def test_add_window_creates_windows_after_dashboards():
    doc = etree.fromstring("<workbook><worksheets/><dashboards/></workbook>")
    add_window(doc, "dashboard", "D", ["A", "B"], "{U}")
    assert [c.tag for c in doc] == ["worksheets", "dashboards", "windows"]
    assert doc.xpath("//window/viewpoints/viewpoint/@name") == ["A", "B"]
    assert doc.xpath("//window/active/@id") == ["-1"]
