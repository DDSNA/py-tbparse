"""`template_gui`: the JSON-ready helpers behind the GUI's Templates view (no server)."""
from __future__ import annotations

import csv
import json
import shutil
import zipfile
from pathlib import Path

import pytest
from lxml import etree

import py_tbparse.templates as templates
from py_tbparse import TemplateError, TwbParser, load_template, make_template, read_data
from py_tbparse import template_gui as gui
from py_tbparse.template_gui import (apply, column_choices, data_summary, excel_sheets, mapping_frame,
                                     output_data_path, plan, tableau_datasources, template_summary)

PUBLIC = Path(__file__).parent / "fixtures" / "public"
V1 = Path(__file__).parent / "fixtures" / "templates" / "filtering.v1.template.twbx"


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setattr(templates, "_now", lambda: "2026-10-05T00:00:00+00:00")


def _tokenised(src, out):
    root = etree.parse(str(src)).getroot()
    root.xpath("//worksheet/layout-options/title//run")[0].text = "Sales for {{customer}}"
    Path(out).write_bytes(etree.tostring(root, xml_declaration=True, encoding="utf-8"))
    return out


@pytest.fixture
def tpl(tmp_path):
    """The filtering workbook as a template: one datasource, one required field (`Burst Out Set list`)."""
    return load_template(make_template(str(PUBLIC / "filtering.twb"), output_path=str(tmp_path / "f.template.twbx"),
                                       template_id="tpl-1"))


@pytest.fixture
def tok_tpl(tmp_path):
    book = _tokenised(PUBLIC / "filtering.twb", tmp_path / "tok.twb")
    return load_template(make_template(book, output_path=str(tmp_path / "tok.template.twbx"), template_id="tpl-1"))


@pytest.fixture
def param_tpl(tmp_path):
    shutil.copy(PUBLIC / "Cache.twbx", tmp_path / "Cache.twbx")
    return load_template(make_template(str(tmp_path / "Cache.twbx"), output_path=str(tmp_path / "c.template.twbx")))


def _csv(t, folder, name="data.csv", skip=(), extra=()):
    entry = next(e for e in t.manifest["datasources"] if e["fields"])
    cols = [f["remote"] for f in entry["fields"] if f["name"] not in skip] + list(extra)
    path = Path(folder) / name
    with open(path, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerow(cols)
    return path


def _entry(t):
    return next(e for e in t.manifest["datasources"] if e["fields"])


# --- summaries ----------------------------------------------------------------------------------------------

def test_summary_of_a_v2_template(tpl):
    s = template_summary(tpl, label="f.template.twbx")
    assert s["name"] == "filtering" and s["id"] == "tpl-1" and s["revision"] == 1 and s["label"] == "f.template.twbx"
    [ds] = s["datasources"]
    assert ds["fields"] == 39 and ds["required"] == 1
    json.dumps(s)


def test_summary_of_a_version_1_template():
    s = template_summary(load_template(str(V1)), label=V1.name)
    assert s["id"] is None and s["revision"] == 1
    json.dumps(s)


def test_summary_never_holds_a_server_path_and_a_crashing_check_becomes_a_finding(tpl, tmp_path, monkeypatch):
    assert str(tmp_path) not in json.dumps(template_summary(tpl, label="f.template.twbx"))
    monkeypatch.setattr(gui, "check_template", lambda t: 1 / 0)
    [finding] = template_summary(tpl, label="x")["findings"]
    assert finding["severity"] == "error" and "failed" in finding["detail"]


def test_data_summary_lists_columns_and_types(tpl, tmp_path):
    d = read_data(str(_csv(tpl, tmp_path)))
    s = data_summary(d, label="data.csv")
    assert s["kind"] == "csv" and s["label"] == "data.csv" and len(s["columns"]) == 39
    assert str(tmp_path) not in json.dumps(s)


# --- column choices -----------------------------------------------------------------------------------------

def test_type_status_outcomes_are_pinned():
    assert templates._type_status("integer", "integer") is None
    assert templates._type_status("integer", "real") == "numeric type differs"
    assert templates._type_status("date", "datetime") == "date type differs"
    assert templates._type_status("string", "integer") == "type mismatch"


def test_column_choices_name_each_outcome():
    entry = {"fields": [{"datatype": "integer"}, {"datatype": "date"}, {"datatype": "string"}]}
    data = templates.DataSource(path="x.csv", kind="csv", fields=[
        {"name": "i", "datatype": "integer"}, {"name": "r", "datatype": "real"}, {"name": "dt", "datatype": "datetime"}])
    c = column_choices(entry, data)
    assert {x["column"]: x["status"] for x in c["integer"]} == {"i": "ok", "r": "numeric-differs", "dt": "mismatch"}
    assert {x["column"]: x["status"] for x in c["date"]}["dt"] == "date-differs"
    assert {x["column"]: x["status"] for x in c["string"]}["i"] == "mismatch"
    assert set(c) == {"integer", "date", "string"}


# --- plan ---------------------------------------------------------------------------------------------------

def test_plan_with_no_mapping_is_the_suggestion(tpl, tmp_path):
    d = read_data(str(_csv(tpl, tmp_path)))
    p = plan(tpl, d)
    assert p["ready"] and p["problems"] == []
    assert p["mapping"]["total"] == 39 and p["mapping"]["truncated"] == 0
    json.dumps(p)


def test_plan_with_an_edited_mapping(tpl, tmp_path):
    d = read_data(str(_csv(tpl, tmp_path, extra=["Other"])))
    p = plan(tpl, d, mapping={"[Burst Out Set list]": "Other"})
    row = next(r for r in p["mapping"]["rows"] if r["field"] == "[Burst Out Set list]")
    assert row["mapped_to"] == "Other" and row["status"] == "chosen"


def test_a_column_mapped_twice_is_a_problem_not_an_exception(tpl, tmp_path):
    d = read_data(str(_csv(tpl, tmp_path)))
    p = plan(tpl, d, mapping={"[Burst Out Set list]": "Burst Out", "[Burst Out]": "Burst Out"})
    assert not p["ready"] and any("more than one field" in m for m in p["problems"])


def test_a_column_the_data_lacks_is_a_problem(tpl, tmp_path):
    d = read_data(str(_csv(tpl, tmp_path)))
    p = plan(tpl, d, mapping={"[Burst Out Set list]": "Nope"})
    assert not p["ready"] and any("no column 'Nope'" in m for m in p["problems"])


def test_a_missing_required_field_blocks_but_lists_what_breaks(tpl, tmp_path):
    d = read_data(str(_csv(tpl, tmp_path, skip=["[Burst Out Set list]"])))
    p = plan(tpl, d)
    assert not p["ready"] and any("Burst Out Set list" in m for m in p["problems"])
    assert p["broken"]["total"] >= 1
    assert plan(tpl, d, allow_missing=True)["ready"]


# --- parameters and tokens ----------------------------------------------------------------------------------

def test_parameter_values_are_checked(param_tpl, tmp_path):
    d = read_data(str(_csv(param_tpl, tmp_path)))
    sort_by = next(p for p in param_tpl.manifest["parameters"] if p["caption"] == "Sort by")
    good = sort_by["allowed"][-1].strip('"')
    assert plan(param_tpl, d, params={"New Quota": "750000", "Sort by": good}, allow_missing=True)["ready"]
    for params, text in (({"New Quota": "1.5"}, "whole number"), ({"New Quota": "abc"}, "not a number"),
                         ({"Sort by": "zzz"}, "allowed values"), ({"Nope": "1"}, "no parameter")):
        p = plan(param_tpl, d, params=params, allow_missing=True)
        assert not p["ready"] and any(text in m for m in p["problems"]), (params, p["problems"])


def test_a_token_in_an_allowed_list_is_not_checked(param_tpl, tmp_path):
    for p in param_tpl.manifest["parameters"]:
        if p["caption"] == "Sort by":
            p["allowed"] = list(p["allowed"]) + ['"{{customer}}"']
    d = read_data(str(_csv(param_tpl, tmp_path)))
    assert plan(param_tpl, d, params={"Sort by": "anything"}, allow_missing=True)["ready"]


def test_a_missing_token_value_is_named(tok_tpl, tmp_path):
    d = read_data(str(_csv(tok_tpl, tmp_path)))
    p = plan(tok_tpl, d)
    assert not p["ready"] and any("'customer'" in m for m in p["problems"])
    assert p["tokens"][0]["missing"] is True
    ok = plan(tok_tpl, d, tokens={"customer": "ACME"})
    assert ok["ready"] and ok["tokens"][0]["given"] == "ACME"
    assert any("no token 'x'" in m for m in plan(tok_tpl, d, tokens={"customer": "a", "x": "b"})["problems"])


def test_a_token_default_is_used_when_empty(tmp_path):
    book = _tokenised(PUBLIC / "filtering.twb", tmp_path / "tok.twb")
    t = load_template(make_template(book, output_path=str(tmp_path / "d.template.twbx"), template_id="tpl-1",
                                    tokens={"customer": "Default Co"}))
    d = read_data(str(_csv(t, tmp_path)))
    assert plan(t, d)["ready"]


def test_the_plan_is_deterministic(tpl, tmp_path):
    d = read_data(str(_csv(tpl, tmp_path)))
    assert plan(tpl, d) == plan(tpl, d)


# --- sources ------------------------------------------------------------------------------------------------

def test_excel_sheets_lists_visible_sheets_only(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    book.active.title = "One"
    book.create_sheet("Hidden").sheet_state = "hidden"
    book.create_sheet("Two")
    path = tmp_path / "b.xlsx"
    book.save(path)
    assert excel_sheets(str(path)) == ["One", "Two"]
    (tmp_path / "bad.xlsx").write_text("no")
    with pytest.raises(TemplateError):
        excel_sheets(str(tmp_path / "bad.xlsx"))


def test_tableau_datasources_lists_those_with_a_connection():
    names = tableau_datasources(str(PUBLIC / "filtering.twb"))
    assert len(names) == 1
    with pytest.raises(TemplateError):
        tableau_datasources(__file__)


def test_mapping_frame_rejects_unknown_fields_and_double_use(tpl, tmp_path):
    d = read_data(str(_csv(tpl, tmp_path)))
    base = templates.suggest_mapping(tpl, d)
    with pytest.raises(ValueError, match="no field"):
        mapping_frame({"[Nope]": "Burst Out"}, base, d)
    with pytest.raises(ValueError, match="more than one"):
        mapping_frame({"[Burst Out Set list]": "Burst Out", "[Burst Out]": "Burst Out"}, base, d)
    cleared = mapping_frame({"[Burst Out]": ""}, base, d)
    assert cleared.loc[cleared["field"] == "[Burst Out]", "mapped_to"].iloc[0] == ""


# --- output path and apply ----------------------------------------------------------------------------------

def _data(tmp_path, name="sales.csv"):
    p = tmp_path / name
    p.write_text("a,b\n1,2\n")
    return templates.DataSource(path=str(p), kind="csv", fields=[{"name": "a", "datatype": "integer"}])


def test_output_data_path(tmp_path):
    d = _data(tmp_path)
    assert output_data_path("", d) == "sales.csv"
    assert output_data_path(r"C:\Users\me\sales.csv", d) == "C:/Users/me/sales.csv"
    assert output_data_path(r"C:\Users\me", d) == "C:/Users/me/sales.csv"
    assert output_data_path("/home/me/sales.csv", d) == "/home/me/sales.csv"
    assert output_data_path("/home/me/", d) == "/home/me/sales.csv"
    with pytest.raises(TemplateError, match="other.csv"):
        output_data_path(r"C:\Users\me\other.csv", d)


def _twb_text(path):
    with zipfile.ZipFile(path) as z:
        return z.read(next(n for n in z.namelist() if n.endswith(".twb"))).decode("utf-8")


def test_apply_writes_the_given_folder_and_no_temp_path(tpl, tmp_path):
    up = tmp_path / "upload"
    up.mkdir()
    d = read_data(str(_csv(tpl, up, name="sales.csv")))
    out = tmp_path / "out"
    out.mkdir()
    res = apply(tpl, d, str(out), data_path=output_data_path(r"C:\Users\me\Downloads", d))
    assert res["name"].endswith(".twbx") and res["size"] > 0 and res["report"]["mapped"] >= 1
    twb = _twb_text(res["path"])
    assert "C:/Users/me/Downloads" in twb and "sales.csv" in twb
    with zipfile.ZipFile(res["path"]) as z:
        answers = z.read("template-answers.json").decode("utf-8")
    assert str(up) not in twb and str(up) not in answers
    json.dumps(res["report"])


def test_apply_never_overwrites(tpl, tmp_path):
    d = read_data(str(_csv(tpl, tmp_path)))
    out = tmp_path / "out"
    out.mkdir()
    first = apply(tpl, d, str(out))
    second = apply(tpl, d, str(out))
    assert first["name"] != second["name"] and second["name"].endswith("_2.twbx")
    assert Path(first["path"]).exists() and Path(second["path"]).exists()


def test_apply_with_a_missing_required_field_needs_allow_missing(tpl, tmp_path):
    d = read_data(str(_csv(tpl, tmp_path, skip=["[Burst Out Set list]"])))
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(TemplateError, match="required"):
        apply(tpl, d, str(out))
    assert apply(tpl, d, str(out), allow_missing=True)["report"]["missing"] == 1
