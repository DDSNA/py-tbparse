"""Workbook templates: field usage, make, mapping, apply."""

import json
import shutil
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from py_tbparse import (
    TemplateError,
    TwbParser,
    apply_template,
    field_usage,
    load_mapping,
    load_template,
    make_template,
    read_data,
    suggest_mapping,
)
from py_tbparse.cli import main
from py_tbparse.templates import ANSWERS_NAME, MANIFEST_NAME, broken_sheets, read_answers

PUBLIC = Path(__file__).parent / "fixtures" / "public"


@pytest.fixture
def filtering(tmp_path):
    dst = tmp_path / "filtering.twb"
    shutil.copy(PUBLIC / "filtering.twb", dst)
    return dst


@pytest.fixture
def superstore(tmp_path):
    dst = tmp_path / "Cache.twbx"
    shutil.copy(PUBLIC / "Cache.twbx", dst)
    return dst


@pytest.fixture
def q3(tmp_path):
    path = tmp_path / "q3.csv"
    path.write_text("burst_out_set_list,Amount,When\nA,1,2026-01-01\nB,2.5,2026-02-01\n", encoding="utf-8")
    return path


# --- field usage ------------------------------------------------------------


def test_field_usage_follows_calculations_and_sets(filtering):
    u = field_usage(TwbParser(str(filtering))).set_index("field")
    assert u.loc["[Burst Out Set list]", "sheets"] == ["Sheet 1", "Sheet 2"]
    assert u.loc["[BurstoutSet]", "kind"] == "group"
    # the set is used by the SHOW calculation, which Sheet 1 shows
    assert "SHOW" in u.loc["[BurstoutSet]", "calculations"]
    assert u.loc["[Burst Out Set list]", "used"]
    assert not u.loc["[Account Number]", "used"]


def test_field_usage_through_a_calculation(wenjie_path):
    u = field_usage(TwbParser(str(wenjie_path))).set_index("field")
    # [counts] is only on Sheet 1 through the "no data" calculation
    assert u.loc["[counts]", "sheets"] == ["Sheet 1"]
    assert u.loc["[counts]", "calculations"] == ["no data"]


def test_field_usage_table_and_cli(filtering, capsys):
    assert main([str(filtering), "field-usage", "-f", "csv"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("datasource,field,caption,kind")
    assert "Sheet 1; Sheet 2" in out


# --- make -------------------------------------------------------------------


def test_make_template_manifest_and_scrubbing(filtering):
    out = make_template(str(filtering))
    assert out.endswith("filtering.template.twbx")
    with zipfile.ZipFile(out) as z:
        assert set(z.namelist()) == {"filtering.twb", MANIFEST_NAME}
        manifest = json.loads(z.read(MANIFEST_NAME))
        twb = z.read("filtering.twb").decode("utf-8")
    assert manifest["format"] == "py-tbparse-template" and manifest["version"] == 2
    [ds] = manifest["datasources"]
    required = [f["name"] for f in ds["fields"] if f["required"]]
    assert required == ["[Burst Out Set list]"]
    assert all(f["name"] != "[Number of Records]" for f in ds["fields"])  # Tableau's own
    assert ds["connections"][0]["class"] == "sqlserver"
    assert 'username="ctest"' not in twb and "username='ctest'" not in twb
    assert "ctest" in filtering.read_text(encoding="utf-8")  # source untouched


def test_make_template_strips_data_unless_asked(superstore, tmp_path):
    out = make_template(str(superstore))
    names = zipfile.ZipFile(out).namelist()
    assert not any(n.startswith(("Data/", "TwbxExternalCache/")) for n in names)
    kept = make_template(str(superstore), output_path=str(tmp_path / "with_data.twbx"), keep_data=True)
    assert any(n.startswith("Data/") for n in zipfile.ZipFile(kept).namelist())


def test_make_template_strips_extracts(wenjie_path, tmp_path):
    src = tmp_path / "w.twb"
    shutil.copy(wenjie_path, src)
    out = make_template(str(src))
    doc = load_template(out).parser.xml_doc
    assert not [e for e in doc.iter() if isinstance(e.tag, str) and e.tag.endswith("extract")]


def test_make_template_refuses_overwrite_and_bad_extension(filtering, tmp_path):
    make_template(str(filtering))
    with pytest.raises(FileExistsError):
        make_template(str(filtering))
    with pytest.raises(TemplateError, match="twbx"):
        make_template(str(filtering), output_path=str(tmp_path / "t.twb"))


def test_template_parameters(superstore):
    t = load_template(make_template(str(superstore)))
    params = t.parameters().set_index("parameter")
    assert params.loc["New Quota", "datatype"] == "integer"
    assert params.loc["Sort by", "allowed"]  # a list parameter


def test_load_template_rejects_plain_workbooks(superstore):
    with pytest.raises(TemplateError, match="template.json"):
        load_template(str(superstore))
    with pytest.raises(TemplateError, match="twbx"):
        load_template(str(PUBLIC / "filtering.twb"))


# --- mapping ----------------------------------------------------------------


def test_suggest_mapping_matches_and_checks_types(filtering, q3):
    t = load_template(make_template(str(filtering)))
    m = suggest_mapping(t, read_data(str(q3))).set_index("field")
    assert m.loc["[Burst Out Set list]", "mapped_to"] == "burst_out_set_list"
    assert m.loc["[Burst Out Set list]", "status"] == "matched"
    # the template's [Amount] is a string; a real column is not offered
    assert m.loc["[Amount]", "mapped_to"] == ""
    assert m.loc["[Amount]", "status"].startswith("type mismatch")
    assert m.loc["[Account Number]", "status"] == "unused"
    assert broken_sheets(t, m.reset_index()).empty


def test_missing_required_field_is_reported(filtering, tmp_path):
    t = load_template(make_template(str(filtering)))
    other = tmp_path / "other.csv"
    other.write_text("Region,Sales\nEast,1\n", encoding="utf-8")
    m = suggest_mapping(t, read_data(str(other)))
    assert m.set_index("field").loc["[Burst Out Set list]", "status"] == "missing"
    broken = broken_sheets(t, m)
    assert list(broken["sheets"]) == ["Sheet 1; Sheet 2"]
    with pytest.raises(TemplateError, match="Sheet 1, Sheet 2"):
        apply_template(t, str(other))
    out = apply_template(t, str(other), allow_missing=True)
    assert read_answers(out)["missing"] == ["[Burst Out Set list]"]


def test_close_matches_and_numbers():
    from py_tbparse.templates import DataSource, Template

    manifest = {"datasources": [{"name": "ds", "caption": None, "fields": [
        {"name": "[Order Date]", "caption": None, "remote": "Order Date", "datatype": "date", "required": True},
        {"name": "[Address Line 2]", "caption": None, "remote": "a2", "datatype": "string", "required": True},
        {"name": "[Sales]", "caption": None, "remote": "Sales", "datatype": "real", "required": True},
    ]}]}
    t = Template(path="t.twbx", parser=None, manifest=manifest)
    data = DataSource(path="d.csv", kind="csv", fields=[
        {"name": "Order Dates", "datatype": "datetime"},
        {"name": "Address Line 1", "datatype": "string"},
        {"name": "SALES", "datatype": "integer"},
    ])
    m = suggest_mapping(t, data).set_index("field")
    assert m.loc["[Order Date]", "mapped_to"] == "Order Dates"
    assert m.loc["[Order Date]", "status"] == "date type differs"
    assert m.loc["[Address Line 2]", "mapped_to"] == ""  # never Line 1
    assert m.loc["[Sales]", "status"] == "numeric type differs"


def test_load_mapping_validates(tmp_path):
    with pytest.raises(ValueError, match="missing column"):
        load_mapping(pd.DataFrame({"field": ["[a]"]}))
    with pytest.raises(ValueError, match="more than one"):
        load_mapping(pd.DataFrame({"field": ["[a]", "[b]"], "mapped_to": ["x", "x"]}))


# --- apply ------------------------------------------------------------------


def test_apply_to_csv_keeps_sheets_working(filtering, q3):
    t = load_template(make_template(str(filtering)))
    report = {}
    out = apply_template(t, str(q3), report=report)
    assert out.endswith("filtering_q3.twbx") and report["mapped"] == 1
    with zipfile.ZipFile(out) as z:
        assert set(z.namelist()) == {"filtering.twb", ANSWERS_NAME}
    p = TwbParser(out)
    ds = p.get_datasources()
    assert list(ds["connection_class"]) == ["textscan"]
    [rec] = p.xml_doc.xpath("//metadata-record[local-name='[Burst Out Set list]']")
    assert rec.findtext("remote-name") == "burst_out_set_list"
    u = field_usage(p).set_index("field")
    assert u.loc["[Burst Out Set list]", "sheets"] == ["Sheet 1", "Sheet 2"]
    # the old SQL Server connection, extract and object graph are gone, a new graph is in
    text = Path(out).read_bytes()
    assert b"sqlserver" not in zipfile.ZipFile(out).read("filtering.twb")
    graphs = [e for e in p.xml_doc.iter() if isinstance(e.tag, str) and e.tag.endswith("object-graph")]
    assert len(graphs) == 1 and graphs[0].xpath(".//relation[@connection]")
    answers = read_answers(out)
    assert answers["mapping"] == {"[Burst Out Set list]": "burst_out_set_list"}
    assert answers["template"]["manifest_sha256"] == t.manifest_sha256
    assert text  # written
    with pytest.raises(FileExistsError):
        apply_template(t, str(q3))


def test_apply_with_edited_mapping_and_unknown_column(filtering, q3):
    t = load_template(make_template(str(filtering)))
    m = suggest_mapping(t, read_data(str(q3)))
    m.loc[m["field"] == "[Burst Out Set list]", "mapped_to"] = "When"
    out = apply_template(t, str(q3), mapping=m, output_path=str(Path(q3).with_name("edited.twbx")))
    p = TwbParser(out)
    [rec] = p.xml_doc.xpath("//metadata-record[local-name='[Burst Out Set list]']")
    assert rec.findtext("remote-name") == "When"
    # the author set this field's type by hand (datatype-customized), so it stays a
    # string and Tableau converts the date column
    [col] = p.xml_doc.xpath("//datasource/column[@name='[Burst Out Set list]']")
    assert col.get("datatype") == "string" and col.get("datatype-customized") == "true"
    m.loc[m["field"] == "[Burst Out Set list]", "mapped_to"] = "nope"
    with pytest.raises(TemplateError, match="nope"):
        apply_template(t, str(q3), mapping=m, output_path=str(Path(q3).with_name("x.twbx")))


def test_apply_with_a_tableau_workbook_as_data(filtering, tmp_path):
    t = load_template(make_template(str(filtering)))
    # the "new" data: the same table, but the column is called BURST_OUT_SET_LIST
    data = tmp_path / "newdata.twb"
    data.write_text(
        filtering.read_text(encoding="utf-8")
        .replace("<remote-name>Burst Out Set list</remote-name>", "<remote-name>BURST_OUT_SET_LIST</remote-name>")
        .replace("<local-name>[Burst Out Set list]</local-name>", "<local-name>[BURST_OUT_SET_LIST]</local-name>"),
        encoding="utf-8",
    )
    m = suggest_mapping(t, read_data(str(data))).set_index("field")
    assert m.loc["[Burst Out Set list]", "mapped_to"] == "BURST_OUT_SET_LIST"
    out = apply_template(t, str(data))
    p = TwbParser(out)
    [rec] = p.xml_doc.xpath("//metadata-record[remote-name='BURST_OUT_SET_LIST']")
    assert rec.findtext("local-name") == "[Burst Out Set list]"


def test_apply_sets_parameters(superstore, tmp_path):
    t = load_template(make_template(str(superstore)))
    ds = t.datasource(t.manifest["datasources"][0]["name"])
    cols = [f["remote"] for f in ds["fields"]]
    csv = tmp_path / "d.csv"
    csv.write_text(",".join(c.replace(",", " ") for c in cols) + "\n", encoding="utf-8")
    sort_by = next(p for p in t.manifest["parameters"] if p["caption"] == "Sort by")
    allowed = sort_by["allowed"][-1].strip('"')
    out = apply_template(t, str(csv), datasource=ds["name"], allow_missing=True,
                         params={"New Quota": "750000", "Sort by": allowed})
    doc = TwbParser(out).xml_doc
    [quota] = doc.xpath("//datasource[@name='Parameters']/column[@caption='New Quota']")
    assert quota.get("value") == "750000" and quota.find("calculation").get("formula") == "750000"
    with pytest.raises(TemplateError, match="allowed"):
        apply_template(t, str(csv), datasource=ds["name"], allow_missing=True, params={"Sort by": "zzz"},
                       output_path=str(tmp_path / "a.twbx"))
    with pytest.raises(TemplateError, match="whole number"):
        apply_template(t, str(csv), datasource=ds["name"], allow_missing=True, params={"New Quota": "1.5"},
                       output_path=str(tmp_path / "b.twbx"))
    with pytest.raises(TemplateError, match="no parameter"):
        apply_template(t, str(csv), datasource=ds["name"], allow_missing=True, params={"Nope": "1"},
                       output_path=str(tmp_path / "c.twbx"))


def test_param_literals():
    from py_tbparse.templates import _param_literal

    assert _param_literal("string", 'say "hi"') == '"say ""hi"""'
    assert _param_literal("real", "0.5") == "0.5"
    assert _param_literal("real", "2") == "2.0"
    assert _param_literal("date", "2026-01-31") == "#2026-01-31#"
    assert _param_literal("boolean", "TRUE") == "true"
    with pytest.raises(TemplateError):
        _param_literal("date", "soon")


def test_several_datasources_need_a_choice(superstore, tmp_path):
    t = load_template(make_template(str(superstore)))
    if len([d for d in t.manifest["datasources"] if any(f["required"] for f in d["fields"])]) > 1:
        with pytest.raises(TemplateError, match="several datasources"):
            t.datasource()
    with pytest.raises(TemplateError, match="no datasource"):
        t.datasource("nope")


# --- CLI --------------------------------------------------------------------


def test_cli_make_show_apply(filtering, q3, capsys, tmp_path):
    assert main(["template", "make", str(filtering), "--name", "Burst report"]) == 0
    assert "1 required field" in capsys.readouterr().err
    tpl = str(filtering.with_name("filtering.template.twbx"))

    assert main(["template", "show", tpl, "-f", "csv"]) == 0
    assert "[Burst Out Set list]" in capsys.readouterr().out

    mapping = tmp_path / "map.csv"
    assert main(["template", "apply", tpl, "--data", str(q3), "--mapping-out", str(mapping)]) == 0
    captured = capsys.readouterr()
    assert "burst_out_set_list" in captured.out and mapping.exists()
    assert not filtering.with_name("filtering_q3.twbx").exists()  # dry run by default

    assert main(["template", "apply", tpl, "--data", str(q3), "--mapping", str(mapping), "--write"]) == 0
    assert "wrote" in capsys.readouterr().err
    assert filtering.with_name("filtering_q3.twbx").exists()


def test_cli_apply_errors(filtering, tmp_path, capsys):
    assert main(["template", "make", str(filtering)]) == 0
    tpl = str(filtering.with_name("filtering.template.twbx"))
    other = tmp_path / "other.csv"
    other.write_text("Region\nEast\n", encoding="utf-8")
    capsys.readouterr()
    assert main(["template", "apply", tpl, "--data", str(other)]) == 0
    assert "missing: Burst Out Set list" in capsys.readouterr().err
    assert main(["template", "apply", tpl, "--data", str(other), "--write"]) == 1
    assert "would break" in capsys.readouterr().err
    assert main(["template", "apply", tpl, "--data", str(tmp_path / "none.csv")]) == 1
    assert main(["template", "show", str(filtering)]) == 1
    with pytest.raises(SystemExit):
        main(["template", "apply", tpl, "--data", str(other), "-p", "novalue"])


def test_empty_csv_columns_take_the_fields_type(filtering, tmp_path):
    t = load_template(make_template(str(filtering)))
    headers_only = tmp_path / "headers.csv"
    headers_only.write_text("Burst Out Set list,Account Number\n", encoding="utf-8")
    data = read_data(str(headers_only))
    assert all(f["datatype"] is None for f in data.fields)  # nothing to judge by
    m = suggest_mapping(t, data).set_index("field")
    assert m.loc["[Burst Out Set list]", "status"] == "matched"
    out = apply_template(t, data)
    p = TwbParser(out)
    [rec] = p.xml_doc.xpath("//metadata-record[remote-name='Burst Out Set list']")
    assert rec.findtext("local-type") == "real"  # the type the template was built on
    [rec] = p.xml_doc.xpath("//metadata-record[remote-name='Account Number']")
    assert rec.findtext("local-type")  # a type is always written


def test_make_and_apply_every_public_workbook(tmp_path):
    for src in sorted(PUBLIC.glob("*.tw*")):
        work = tmp_path / src.stem
        work.mkdir()
        book = work / src.name
        shutil.copy(src, book)
        t = load_template(make_template(str(book)))
        for entry in t.manifest["datasources"]:
            if not entry["fields"]:
                continue
            csv = work / "data.csv"
            csv.write_text(",".join('"' + f["remote"].replace('"', '""') + '"' for f in entry["fields"]) + "\n",
                           encoding="utf-8")
            out = apply_template(t, str(csv), datasource=entry["name"], allow_missing=True,
                                 output_path=str(work / f"out_{len(list(work.iterdir()))}.twbx"))
            p = TwbParser(out)
            assert len(p.xml_doc.xpath("/workbook/worksheets/worksheet")) == len(t.manifest["worksheets"])
            assert read_answers(out)["datasource"] == entry["name"]


def test_names_in_any_script_match():
    from py_tbparse.rename import _match_key, suggest_field_renames

    assert _match_key("赛前排名") == "赛前排名"
    assert _match_key("赛前排名") != _match_key("赛后排名")
    assert _match_key("Über Größe") == "übergröße"
    # a respelled non-Latin name takes the reference's spelling (it used to match nothing)
    fields = pd.DataFrame([{"datasource": "d", "name": "[用户 人数]", "caption": None, "is_parameter": False}])
    out = suggest_field_renames(fields, reference=["用户人数"])
    assert out.loc[0, "reason"] == "matches reference" and out.loc[0, "suggested"] == "用户人数"


def test_template_mapping_with_non_latin_columns(tmp_path):
    from py_tbparse.templates import DataSource, Template

    manifest = {"datasources": [{"name": "ds", "caption": None, "fields": [
        {"name": "[赛前排名]", "caption": None, "remote": "赛前排名", "datatype": "integer", "required": True},
        {"name": "[赛后排名]", "caption": None, "remote": "赛后排名", "datatype": "integer", "required": True},
    ]}]}
    t = Template(path="t.twbx", parser=None, manifest=manifest)
    data = DataSource(path="d.csv", kind="csv", fields=[
        {"name": "赛后排名", "datatype": "integer"}, {"name": "赛前排名", "datatype": "integer"}])
    m = suggest_mapping(t, data).set_index("field")
    assert m.loc["[赛前排名]", "mapped_to"] == "赛前排名"
    assert m.loc["[赛后排名]", "mapped_to"] == "赛后排名"


def test_a_column_two_fields_want_says_who_took_it():
    from py_tbparse.templates import DataSource, Template

    # a joined source: the same column name in two tables
    manifest = {"datasources": [{"name": "ds", "caption": None, "fields": [
        {"name": "[Order ID]", "caption": None, "remote": "Order ID", "datatype": "string", "required": True},
        {"name": "[Order ID (Returns)]", "caption": None, "remote": "Order ID", "datatype": "string", "required": True},
    ]}]}
    t = Template(path="t.twbx", parser=None, manifest=manifest)
    data = DataSource(path="d.csv", kind="csv", fields=[{"name": "Order ID", "datatype": "string"}])
    m = suggest_mapping(t, data).set_index("field")
    assert m.loc["[Order ID]", "mapped_to"] == "Order ID"
    assert m.loc["[Order ID (Returns)]", "mapped_to"] == ""
    assert "already used by [Order ID]" in m.loc["[Order ID (Returns)]", "status"]
