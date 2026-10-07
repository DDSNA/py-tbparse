"""Calculated-field and parameter libraries: export, import, show (py_tbparse/library.py).

The fixtures are made by hand from the shapes seen in the 200-workbook corpus. Nothing here opens a
workbook in Tableau; the schema check is structural only."""

import copy
import json
import shutil
import sys
import zipfile
from pathlib import Path

import pandas as pd
import pytest
from lxml import etree

sys.path.insert(0, str(Path(__file__).parent))
from schema_check import new_schema_errors   # noqa: E402

from py_tbparse import (
    LibraryError, TwbParser, build_imported_workbook, export_library, field_usage, import_library, library_table,
    load_library, plan_import, save_library, suggest_mapping, validate_workbook,
)
from py_tbparse import library as lib_mod
from py_tbparse.usage import missing_references

FIX = Path(__file__).parent / "fixtures" / "library"
CALC = "{http://www.tableausoftware.com/xml/user}auto-column"


@pytest.fixture
def source():
    return TwbParser(str(FIX / "source.twb"))


@pytest.fixture
def target():
    return TwbParser(str(FIX / "target.twb"))


@pytest.fixture
def noparams():
    return TwbParser(str(FIX / "target_noparams.twb"))


@pytest.fixture
def library(source):
    return export_library(source)


def entry(lib, caption):
    return next(e for e in lib["entries"] if e["caption"] == caption)


def built(parser, lib, **kw):
    """The built workbook as a parser."""
    return TwbParser_from_bytes(build_imported_workbook(parser, lib, **kw))


def TwbParser_from_bytes(data, tmp=[0]):
    import tempfile
    d = Path(tempfile.mkdtemp())
    p = d / "out.twb"
    p.write_bytes(data)
    return TwbParser(str(p))


def columns(parser, ds):
    el = parser.xml_doc.xpath("/workbook/datasources/datasource[@name=$n]", n=ds)[0]
    return {c.get("name"): c for c in el.findall("column")}


def actions(plan):
    return dict(zip(plan["caption"].fillna(plan["name"]), plan["action"]))


# ----------------------------------------------------------------- export --

def test_export_shape(library):
    assert library["format"] == "py-tbparse-library" and library["version"] == 1
    assert library["source"] == {"workbook": "source.twb", "datasource": "federated.src1", "datasource_caption": "Orders"}
    kinds = {r["name"]: r["kind"] for r in library["required"]}
    assert kinds == {"[Sales]": "field", "[Profit]": "field", "[Category]": "field",
                     "[Order Date]": "field", "[Big Orders]": "set"}
    sales = next(r for r in library["required"] if r["name"] == "[Sales]")
    assert sales["remote"] == "Sales" and sales["datatype"] == "real" and sales["role"] == "measure"
    assert len(sales["used_by"]) == 6
    names = [e["name"] for e in library["entries"]]
    assert "[Number of Records]" not in names                       # Tableau's own record count
    assert len(library["entries"]) == 12                           # 9 calcs and 3 parameters
    pr = entry(library, "Profit Ratio")
    assert pr["attrs"] == {"default-format": "p0.0%"} and pr["calc_attrs"] == {}
    assert pr["refs"] == ["[Profit]", "[Sales]"] and pr["datatype"] == "real" and pr["type"] == "quantitative"
    assert not any(k.startswith("{") or k.startswith("user:") for e in library["entries"] for k in e["attrs"])
    top = entry(library, "Top Metric")
    assert top["formula_display"] == "IF SUM([Sales]) >= [Parameters].[Top N] THEN [Parameters].[Metric] END"
    assert top["formula"].count("[Parameters].[Parameter") == 2 and len(top["depends_on"]) == 2
    assert entry(library, "Margin Gap")["formula_display"] == "[Profit Ratio] - 0.1"
    assert json.loads(json.dumps(library)) == library


def test_export_dependencies_closed(source):
    lib = export_library(source, select=["Margin Gap", "Top Metric"])
    assert sorted(e["caption"] for e in lib["entries"]) == ["Margin Gap", "Metric", "Profit Ratio", "Top Metric", "Top N"]
    lib = export_library(source, select=["Margin Gap", "Top Metric"], with_dependencies=False)
    assert sorted(e["caption"] for e in lib["entries"]) == ["Margin Gap", "Top Metric"]
    req = {(r["kind"], r["name"]) for r in lib["required"]}
    assert ("calc", "[Calculation_1001]") in req and ("parameter", "[Parameter 1]") in req
    lib = export_library(source, select=["Top Metric"], include_parameters=False)
    assert [e["caption"] for e in lib["entries"]] == ["Top Metric"]
    assert ("parameter", "[Parameter 2]") in {(r["kind"], r["name"]) for r in lib["required"]}
    with pytest.raises(LibraryError, match="nothing named 'Nope'"):
        export_library(source, select=["Nope"])


def test_export_by_folder(source):
    lib = export_library(source, folder="KPIs")
    assert sorted(e["caption"] for e in lib["entries"]) == ["Margin Gap", "Profit Ratio"]
    with pytest.raises(LibraryError, match="folder"):
        export_library(source, folder="Missing")


def test_export_unsupported_cross_datasource(tmp_path):
    doc = etree.parse(str(FIX / "source.twb"))
    ds = doc.xpath("//datasource[@name='federated.src1']")[0]
    other = etree.fromstring("<datasource caption='Other' name='federated.other' version='18.1'><connection class='federated'/></datasource>")
    ds.addnext(other)
    calc = etree.fromstring("<column caption='Cross' datatype='real' name='[Calculation_2000]' role='measure' type='quantitative'>"
                            "<calculation class='tableau' formula='SUM([federated.other].[Amount])' /></column>")
    over = etree.fromstring("<column caption='On Cross' datatype='real' name='[Calculation_2001]' role='measure' type='quantitative'>"
                            "<calculation class='tableau' formula='[Calculation_2000] * 2' /></column>")
    ds.append(calc)
    ds.append(over)
    path = tmp_path / "cross.twb"
    doc.write(str(path), encoding="utf-8", xml_declaration=True)
    rep = {}
    lib = export_library(TwbParser(str(path)), datasource="federated.src1", report=rep)
    assert rep["unsupported"] == 2 and rep["unsupported_names"] == ["Calculation_2000", "Calculation_2001"]
    assert "Cross" not in [e["caption"] for e in lib["entries"]] and rep["exported"] == 12
    with pytest.raises(LibraryError, match="one datasource with a connection"):
        export_library(TwbParser(str(path)))


def test_report_names_what_an_export_of_everything_leaves_out(tmp_path):
    # the GUI says why the sidebar counts calculations the library list does not show (#144)
    doc = etree.parse(str(FIX / "source.twb"))
    ds = doc.xpath("//datasource[@name='federated.src1']")[0]
    ds.append(etree.fromstring("<column caption='Region (group)' datatype='string' name='[Region (group)]' role='dimension' "
                               "type='nominal'><calculation class='categorical-bin' column='[Region]' new-bin='true'/></column>"))
    path = tmp_path / "groups.twb"
    doc.write(str(path), encoding="utf-8", xml_declaration=True)
    rep = {}
    lib = export_library(TwbParser(str(path)), report=rep)
    assert rep["auto"] == 1 and rep["auto_names"] == ["Number of Records"]
    assert rep["not_formula"] == 1 and rep["not_formula_names"] == ["Region (group)"]
    assert "Number of Records" not in [e["caption"] for e in lib["entries"]]
    picked = {}
    export_library(TwbParser(str(path)), select=[lib["entries"][0]["name"]], report=picked)
    assert picked["auto"] == 0 and picked["not_formula"] == 1


def test_export_needs_a_datasource_choice(source):
    with pytest.raises(LibraryError, match="no datasource 'nope'"):
        export_library(source, datasource="nope")
    assert export_library(source, datasource="Orders")["source"]["datasource"] == "federated.src1"


# ------------------------------------------------------------ save / load --

def test_save_load_roundtrip(library, tmp_path):
    p = tmp_path / "x.library.json"
    assert save_library(library, p) == str(p)
    assert load_library(p) == library
    text = p.read_text(encoding="utf-8")
    assert text.startswith('{\n  "created"') and text.endswith("}\n")       # sorted keys, indent 2
    assert "\\r\\n" in text and "\r" not in text                            # the line endings stay escaped
    with pytest.raises(FileExistsError):
        save_library(library, p)
    save_library({**library, "name": "again"}, p, overwrite=True)
    assert load_library(p)["name"] == "again"
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({**library, "format": "other"}))
    with pytest.raises(LibraryError, match="not a py-tbparse library"):
        load_library(bad)
    bad.write_text(json.dumps({**library, "version": 2}))
    with pytest.raises(LibraryError, match="newer"):
        load_library(bad)
    bad.write_text("not json")
    with pytest.raises(LibraryError):
        load_library(bad)


# ------------------------------------------------------------------ order --

def test_dependency_order(library):
    order = [e["caption"] for e in lib_mod._order(library["entries"])]
    assert order.index("Top N") < order.index("Top Metric") and order.index("Metric") < order.index("Top Metric")
    assert order.index("Profit Ratio") < order.index("Margin Gap")
    assert order[:3] == ["Top N", "Metric", "Free text"]       # parameters first among the ready ones, by name
    a, b = copy.deepcopy(entry(library, "Profit Ratio")), copy.deepcopy(entry(library, "Margin Gap"))
    a["depends_on"] = [b["uid"]]
    cyc = {**library, "entries": [a, b]}
    with pytest.raises(LibraryError, match="circle"):
        lib_mod._order(cyc["entries"])
    with pytest.raises(LibraryError, match="circle"):
        plan_import(TwbParser(str(FIX / "target.twb")), cyc)


# ----------------------------------------------------------------- import --

def test_self_import_all_identical(source, library):
    plan = plan_import(source, library)
    rows = plan[plan["uid"] != ""]
    assert set(rows["action"]) == {"skip-identical"} and len(rows) == 12
    out = lib_mod.build_imported_workbook(source, library)
    assert etree.tostring(etree.fromstring(out)) == etree.tostring(source.xml_doc)


def test_import_maps_fields(target, library):
    plan = plan_import(target, library)
    sales = plan[(plan["name"] == "[Sales]")].iloc[0]
    assert sales["action"] == "mapped" and sales["target_name"] == "[Revenue]" and "matched" in sales["reason"]
    out = built(target, library)
    cols = columns(out, "federated.tgt1")
    new = {c.get("caption"): c for c in cols.values() if c.get("caption")}
    assert new["Profit Ratio (2)"].find("calculation").get("formula") == "SUM([Profit])/SUM([Revenue])"
    assert new["Label"].find("calculation").get("formula") == '"[Sales] is " + STR(SUM([Revenue]))'   # the string stays
    assert new["Sales by Category"].find("calculation").get("formula") == "{ FIXED [Category]:SUM([Revenue])}"
    assert new["In Big Orders"].find("calculation").get("formula") == "IF [Big Orders] THEN 1 ELSE 0 END"


def test_import_explicit_mapping(target, library):
    other = TwbParser(str(FIX / "target.twb"))
    lib = copy.deepcopy(library)
    for r in lib["required"]:
        if r["name"] == "[Sales]":
            r["caption"], r["remote"] = None, "Sales"       # nothing for the matcher to go on
    assert plan_import(other, lib).query("name == '[Sales]'").iloc[0]["action"] == "unmapped"
    p = plan_import(other, lib, mapping={"[Sales]": "Revenue"})
    assert p.query("name == '[Sales]'").iloc[0]["target_name"] == "[Revenue]"
    p = plan_import(other, lib, mapping=pd.DataFrame({"field": ["[Sales]"], "mapped_to": ["Revenue"]}))
    assert p.query("name == '[Sales]'").iloc[0]["target_name"] == "[Revenue]"
    p = plan_import(other, lib, mapping={"[Sales]": "Nothing"})
    assert "does not have" in p.query("name == '[Sales]'").iloc[0]["reason"]


def test_parameter_internal_clash(target, library):
    out = built(target, library)
    params = columns(out, "Parameters")
    assert params["[Parameter 1]"].get("caption") == "Threshold"          # untouched
    assert params["[Parameter 2]"].get("caption") == "Top N"
    assert params["[Parameter 3]"].get("caption") == "Metric"
    formula = next(c for c in columns(out, "federated.tgt1").values() if c.get("caption") == "Top Metric")
    assert formula.find("calculation").get("formula") == \
        "IF SUM([Revenue]) >= [Parameters].[Parameter 2] THEN [Parameters].[Parameter 3] END"


def test_clash_rename(target, library):
    plan = plan_import(target, library)
    assert actions(plan)["Profit Ratio"] == "add-renamed"
    row = plan[plan["caption"] == "Profit Ratio"].iloc[0]
    assert row["target_caption"] == "Profit Ratio (2)" and row["target_name"] == "[Calculation_1001]"
    out = built(target, library)
    assert columns(out, "federated.tgt1")["[Calculation_9001]"].get("caption") == "Profit Ratio"   # the target's own
    rep = {}
    build_imported_workbook(target, library, report=rep)
    assert rep["renamed"] == 1 and rep["renamed_names"] == ["Profit Ratio"] and rep["added"] == 12
    assert rep["renamed_internal"] == 3 and rep["failed"] == 0


def test_clash_skip(target, library):
    plan = plan_import(target, library, on_clash="skip")
    assert actions(plan)["Profit Ratio"] == "skip-clash"
    rep = {}
    out = built(target, library, on_clash="skip", report=rep)
    assert rep["skipped"] == 1 and rep["added"] == 11
    # Margin Gap used Profit Ratio: it now points at the target's own calculation
    gap = next(c for c in columns(out, "federated.tgt1").values() if c.get("caption") == "Margin Gap")
    assert gap.find("calculation").get("formula") == "[Calculation_9001] - 0.1"
    assert "(2)" not in " ".join(c.get("caption") or "" for c in columns(out, "federated.tgt1").values())


def test_clash_fail(target, library, tmp_path):
    with pytest.raises(LibraryError, match="Profit Ratio"):
        plan_import(target, library, on_clash="fail")
    out = tmp_path / "t_library.twb"
    shutil.copy(FIX / "target.twb", tmp_path / "t.twb")
    with pytest.raises(LibraryError):
        import_library(TwbParser(str(tmp_path / "t.twb")), library, on_clash="fail", output_path=str(out))
    assert not out.exists()
    with pytest.raises(LibraryError, match="on_clash"):
        plan_import(target, library, on_clash="whatever")


def test_identical_under_other_name(source, library):
    # the same calculation exists in the target with another internal name
    doc = copy.deepcopy(source.xml_doc)
    ds = doc.xpath("//datasource[@name='federated.src1']")[0]
    ds.xpath("./column[@name='[Calculation_1001]']")[0].set("name", "[Calculation_7777]")
    for c in ds.xpath("./column"):
        calc = c.find("calculation")
        if calc is not None and "[Calculation_1001]" in calc.get("formula"):
            calc.set("formula", calc.get("formula").replace("[Calculation_1001]", "[Calculation_7777]"))
    for it in ds.xpath("./folder/folder-item"):
        if it.get("name") == "[Calculation_1001]":
            it.set("name", "[Calculation_7777]")
    renamed = TwbParser_from_bytes(etree.tostring(doc))
    plan = plan_import(renamed, library)
    acts = actions(plan)
    assert acts["Profit Ratio"] == "skip-identical" and acts["Margin Gap"] == "skip-identical"
    row = plan[plan["caption"] == "Profit Ratio"].iloc[0]
    assert row["target_name"] == "[Calculation_7777]" and "another name" in row["reason"]
    # a dependent that is not identical points to the existing name
    lib = copy.deepcopy(library)
    entry(lib, "Margin Gap")["formula"] = "[Calculation_1001] - 0.2"
    out = built(renamed, lib)
    gap = [c for c in columns(out, "federated.src1").values() if (c.get("caption") or "").startswith("Margin Gap")]
    assert any(c.find("calculation").get("formula") == "[Calculation_7777] - 0.2" for c in gap)


def test_identical_calc_is_skipped_even_when_it_names_a_field_the_target_lacks(source, library):
    # self-import of a workbook whose metadata no longer lists [Profit]: the calculations are the
    # target's own, so they are identical, not "unmapped" (a regression from comparing rewritten formulas late)
    doc = source.xml_doc
    for rec in doc.xpath("//metadata-record[local-name='[Profit]']"):
        rec.getparent().remove(rec)
    t = TwbParser_from_bytes(etree.tostring(doc))
    rows = plan_import(t, library)
    rows = rows[rows["uid"] != ""]
    assert set(rows["action"]) == {"skip-identical"}


def test_unmapped_chain_skipped(library):
    # a target without Profit: everything that uses it fails, and what depends on those is skipped
    doc = TwbParser(str(FIX / "target.twb")).xml_doc
    for rec in doc.xpath("//metadata-record[local-name='[Profit]']"):
        rec.getparent().remove(rec)
    t = TwbParser_from_bytes(etree.tostring(doc))
    rep = {}
    out = built(t, library, report=rep)
    assert sorted(rep["failed_names"]) == ["Gain or Loss", "Profit Ratio"]
    assert rep["skipped_dependents"] == 1 and rep["skipped_dependents_names"] == ["Margin Gap"]
    assert rep["added"] == 12 - 3
    caps = [c.get("caption") for c in columns(out, "federated.tgt1").values()]
    assert "Sales by Category" in caps and "Margin Gap" not in caps and "Gain or Loss" not in caps
    plan = plan_import(t, library)
    assert "no match for [Profit]" in plan[plan["caption"] == "Profit Ratio"].iloc[0]["reason"]
    assert "Profit Ratio" in plan[plan["caption"] == "Margin Gap"].iloc[0]["reason"]


def test_parameter_roundtrip(library, target, noparams):
    for t in (target, noparams):
        out = built(t, library)
        by_cap = {c.get("caption"): c for c in columns(out, "Parameters").values()}
        top, metric, free = by_cap["Top N"], by_cap["Metric"], by_cap["Free text"]
        assert dict(top.find("range").attrib) == {"granularity": "5", "max": "20", "min": "5"}
        assert top.get("param-domain-type") == "range" and top.get("value") == "10"
        assert [m.get("value") for m in metric.find("members")] == ['"Sales"', '"Profit"']
        assert metric.find("members")[1].get("alias") == "Profit amount"
        assert dict(metric.find("aliases")[0].attrib) == {"key": '"Profit"', "value": "Profit amount"}
        assert [c.tag for c in metric] == ["calculation", "aliases", "members"]
        assert free.get("param-domain-type") == "any" and free.find("range") is None and free.find("members") is None
        assert list(top.attrib) == ["caption", "datatype", "name", "param-domain-type", "role", "type", "value"]
    out = built(noparams, library)
    first = out.xml_doc.xpath("/workbook/datasources/datasource")[0]
    assert first.get("name") == "Parameters" and dict(first.attrib) == {
        "hasconnection": "false", "inline": "true", "name": "Parameters", "version": "18.1"}
    assert first[0].tag == "aliases" and first[0].get("enabled") == "yes"
    assert list(columns(out, "Parameters")) == ["[Parameter 1]", "[Parameter 2]", "[Parameter 3]"]    # no clash here


def test_table_calc_and_lod_preserved(target, library):
    out = built(target, library)
    cols = {c.get("caption"): c for c in columns(out, "federated.tgt1").values()}
    run = cols["Running Sales"].find("calculation")
    assert dict(run.find("table-calc").attrib) == {"ordering-type": "Rows"}
    assert dict(cols["Sales Rank"].find("calculation").find("table-calc").attrib) == {
        "ordering-field": "[federated.tgt1].[tdy:Order Date:qk]", "ordering-type": "Field"}
    gl = cols["Gain or Loss"].find("calculation")
    assert gl.get("scope-isolation") == "false" and list(gl.attrib) == ["class", "formula", "scope-isolation"]
    assert gl.get("formula") == 'IF SUM([Profit]) > 0\r\nTHEN "gain"\r\nELSE "loss"\r\nEND'
    assert cols["Profit Ratio (2)"].get("default-format") == "p0.0%"


def test_ordering_field_follows_mapped_field(target, library):
    lib = copy.deepcopy(library)
    e = entry(lib, "Sales Rank")
    e["table_calc"]["ordering-field"] = "[federated.src1].[tdy:Sales:qk]"
    e["refs"].append("[Sales]")
    out = built(target, lib)
    rank = next(c for c in columns(out, "federated.tgt1").values() if c.get("caption") == "Sales Rank")
    assert rank.find("calculation/table-calc").get("ordering-field") == "[federated.tgt1].[tdy:Revenue:qk]"


def test_output_reparses(target, library):
    data = build_imported_workbook(target, library)
    out = TwbParser_from_bytes(data)
    before = {(r.datasource, r.field) for r in field_usage(target).itertuples()}
    usage = field_usage(out)
    added = usage[~usage.apply(lambda r: (r.datasource, r.field) in before, axis=1)]
    assert len(added) == 12
    margin = usage[usage["caption"] == "Margin Gap"]
    assert len(margin) == 1
    assert "Margin Gap" in usage[usage["caption"] == "Profit Ratio (2)"]["calculations"].iloc[0]
    assert len(missing_references(out)) == len(missing_references(target)) == 0
    errs = validate_workbook(out)
    errs0 = validate_workbook(target)
    assert len(errs[errs["severity"] == "error"]) <= len(errs0[errs0["severity"] == "error"])
    assert new_schema_errors(str(FIX / "target.twb"), data) == []


def test_import_never_overwrites(tmp_path, library):
    src = tmp_path / "t.twb"
    shutil.copy(FIX / "target.twb", src)
    parser = TwbParser(str(src))
    before = src.read_bytes()
    with pytest.raises(FileExistsError):
        import_library(parser, library, output_path=str(src), overwrite=True)
    with pytest.raises(LibraryError, match="must end in .twb"):
        import_library(parser, library, output_path=str(tmp_path / "o.twbx"))
    existing = tmp_path / "o.twb"
    existing.write_text("keep me")
    with pytest.raises(FileExistsError):
        import_library(parser, library, output_path=str(existing))
    assert existing.read_text() == "keep me"
    default = import_library(parser, library)
    assert Path(default).name == "t_library.twb" and Path(default).exists()
    assert src.read_bytes() == before


def test_twbx_members_copied(tmp_path, library):
    twbx = tmp_path / "t.twbx"
    with zipfile.ZipFile(twbx, "w") as z:
        z.write(FIX / "target.twb", "t.twb")
        z.writestr("Data/extra.csv", "a,b\n1,2\n")
    out = import_library(TwbParser(str(twbx)), library)
    assert out.endswith("t_library.twbx")
    with zipfile.ZipFile(out) as z:
        assert z.read("Data/extra.csv") == b"a,b\n1,2\n"
        assert b"Margin Gap" in z.read("t.twb")


# ---------------------------------------------------------------- names ----

def test_non_latin_names_and_caption_suffix(tmp_path, library):
    lib = copy.deepcopy(library)
    p = entry(lib, "Top N")
    p["name"], p["caption"] = "[参数 1]", "参数"
    top = entry(lib, "Top Metric")
    top["formula"] = top["formula"].replace("[Parameter 1]", "[参数 1]")
    plan_target = TwbParser(str(FIX / "target.twb"))
    doc = plan_target.xml_doc
    pds = doc.xpath("//datasource[@name='Parameters']")[0]
    pds.append(etree.fromstring("<column caption='参数' datatype='integer' name='[参数 1]' param-domain-type='any' role='measure' type='quantitative' value='3'>"
                                "<calculation class='tableau' formula='3' /></column>"))
    t = TwbParser_from_bytes(etree.tostring(doc))
    out = built(t, lib)
    params = columns(out, "Parameters")
    assert params["[参数 2]"].get("caption") == "参数 (2)" and params["[参数 1]"].get("caption") == "参数"
    f = next(c for c in columns(out, "federated.tgt1").values() if c.get("caption") == "Top Metric")
    assert "[Parameters].[参数 2]" in f.find("calculation").get("formula")
    # a caption that already ends in (2) gets another suffix
    doc = TwbParser(str(FIX / "target.twb")).xml_doc
    ds = doc.xpath("//datasource[@name='federated.tgt1']")[0]
    ds.append(etree.fromstring("<column caption='Profit Ratio (2)' datatype='real' name='[Calculation_9002]' role='measure' type='quantitative'>"
                               "<calculation class='tableau' formula='1' /></column>"))
    t2 = TwbParser_from_bytes(etree.tostring(doc))
    row = plan_import(t2, library).query("caption == 'Profit Ratio'").iloc[0]
    assert row["target_caption"] == "Profit Ratio (3)"
    assert lib_mod._suffixed("A (2)", {"A (2)"}) == "A (2) (2)"


def test_generated_calc_name_is_stable(target, library):
    doc = target.xml_doc
    ds = doc.xpath("//datasource[@name='federated.tgt1']")[0]
    ds.append(etree.fromstring("<column caption='Else' datatype='real' name='[Calculation_1001]' role='measure' type='quantitative'>"
                               "<calculation class='tableau' formula='2' /></column>"))
    t = TwbParser_from_bytes(etree.tostring(doc))
    one = plan_import(t, library).query("caption == 'Profit Ratio'").iloc[0]["target_name"]
    two = plan_import(t, library).query("caption == 'Profit Ratio'").iloc[0]["target_name"]
    assert one == two and one.startswith("[Calculation_") and len(one) == len("[Calculation_]") + 18


# -------------------------------------------------------- shared pieces ----

def test_rewrite_formula_skips_strings_and_pairs():
    f = 'IF [A] > [Parameters].[P 1] THEN "[A] and [Parameters].[P 1]" ELSE [other].[A] END + [B]]x]'
    out = lib_mod.rewrite_formula(f, {"[A]": "[Z]", "[B]]x]": "[Y]]w]"}, {"[P 1]": "[P 9]"}, ["other", "Parameters"])
    assert out == 'IF [Z] > [Parameters].[P 9] THEN "[A] and [Parameters].[P 1]" ELSE [other].[A] END + [Y]]w]'


def test_match_fields_refactor(source):
    """suggest_mapping goes through _match_fields and still gives what it gave."""
    from py_tbparse import templates as T
    path = Path(__file__).parent / "fixtures" / "templates" / "filtering.v1.template.twbx"
    t = T.load_template(str(path))
    data = T.DataSource(path="x.csv", kind="csv", fields=[{"name": f["caption"] or f["name"].strip("[]"), "datatype": f["datatype"]}
                                                           for f in t.datasource()["fields"][::-1]])
    direct = T._match_fields(t.datasource()["fields"], data, t.datasource()["name"], 0.85)
    assert direct.equals(suggest_mapping(t, data))
    assert set(direct["status"]) <= {"matched", "close match"} or len(direct)


def test_library_table(library):
    t = library_table(library)
    assert list(t.columns) == ["kind", "name", "caption", "datatype", "depends_on", "required_by"]
    assert len(t) == len(library["entries"]) + len(library["required"])
    gap = t[t["caption"] == "Margin Gap"].iloc[0]
    assert gap["depends_on"] == "Profit Ratio"
    assert "Margin Gap" in t[t["caption"] == "Profit Ratio"].iloc[0]["required_by"]
    assert "Profit Ratio" in t[t["name"] == "[Sales]"].iloc[0]["required_by"]


def test_dependent_of_a_renamed_calc_is_not_skipped_as_identical(tmp_path):
    from test_sheetcopy import write
    from test_sheetcopy_core import datasource, workbook
    src = TwbParser(write(tmp_path, workbook(), "s.twb"))
    tgt = TwbParser(write(tmp_path, workbook(ds=datasource(calc_formula="[Sales] * 3")), "t.twb"))
    plan = plan_import(tgt, export_library(src, datasource="federated.aaa"), on_clash="rename")
    acts = dict(zip(plan["name"], plan["action"]))
    assert acts["[Double]"] == "add-renamed" and acts["[Ratio]"] == "add-renamed"
