"""Excel (.xlsx, .xlsm) as the new data of a template."""

import datetime as dt
import shutil
import sys
import zipfile
from pathlib import Path

import pytest
from lxml import etree

openpyxl = pytest.importorskip("openpyxl")

import py_tbparse.templates as templates   # noqa: E402
from py_tbparse import TemplateError, apply_template, load_template, make_template, suggest_mapping   # noqa: E402
from py_tbparse.cli import main   # noqa: E402
from py_tbparse.templates import _excel_connection, read_answers, read_data   # noqa: E402
from schema_check import new_schema_errors, twb_bytes   # noqa: E402
from test_schema import introduced   # noqa: E402

PUBLIC = Path(__file__).parent / "fixtures" / "public"


def make_xlsx(path, sheets, hidden=()):
    """`sheets` maps a name to its rows (the first row is written where the list puts it)."""
    book = openpyxl.Workbook()
    book.remove(book.active)
    for name, rows in sheets.items():
        ws = book.create_sheet(name)
        for row in rows:
            ws.append(row)
        if name in hidden:
            ws.sheet_state = "hidden"
    book.save(str(path))
    return str(path)


ORDERS = [
    ["Category", "Number of Records", "Order Date", "Sales Target", "Segment", "Paid", "Shipped"],
    ["Furniture", 1, dt.datetime(2026, 1, 31), 10.5, "Consumer", True, dt.datetime(2026, 2, 1, 9, 30)],
    ["Office", 2, dt.datetime(2026, 2, 1), 20, "Corporate", False, dt.datetime(2026, 2, 2, 17, 0)],
]


# --- reading ----------------------------------------------------------------------------------------------


def test_a_sheet_is_described_like_a_csv(tmp_path):
    data = read_data(make_xlsx(tmp_path / "orders.xlsx", {"Orders": ORDERS}))
    assert data.kind == "excel" and data.sheet == "Orders" and data.grid == "A1:G3"
    assert {f["name"]: f["datatype"] for f in data.fields} == {
        "Category": "string", "Number of Records": "integer", "Order Date": "date", "Sales Target": "real",
        "Segment": "string", "Paid": "boolean", "Shipped": "datetime"}


def test_a_column_of_whole_numbers_is_an_integer_and_an_empty_one_has_no_type(tmp_path):
    rows = [["a", "b", "c"], [1.0, None, "x"], [2, None, 3]]
    data = read_data(make_xlsx(tmp_path / "t.xlsx", {"S": rows}))
    assert [f["datatype"] for f in data.fields] == ["integer", None, "string"]   # c mixes text and a number


def test_several_visible_sheets_must_be_chosen(tmp_path):
    path = make_xlsx(tmp_path / "two.xlsx", {"Orders": ORDERS, "People": [["Name"], ["Ann"]], "Notes": [["x"], [1]]},
                     hidden=("Notes",))
    with pytest.raises(TemplateError, match=r"2 visible sheets \(Orders, People\); pick one with sheet="):
        read_data(path)
    assert read_data(path, sheet="People").names() == ["Name"]
    assert read_data(path, sheet=0).sheet == "Orders"
    assert read_data(path, sheet=-1).sheet == "Notes"
    assert read_data(path, sheet="Notes").names() == ["x"]          # a hidden sheet, because it was named
    with pytest.raises(TemplateError, match="no sheet 'Nope'; it has: Orders, People, Notes"):
        read_data(path, sheet="Nope")
    with pytest.raises(TemplateError, match="none at index 9"):
        read_data(path, sheet=9)


def test_hidden_sheets_are_ignored_when_one_visible_sheet_is_left(tmp_path):
    path = make_xlsx(tmp_path / "one.xlsx", {"Hidden": [["x"], [1]], "Shown": ORDERS}, hidden=("Hidden",))
    assert read_data(path).sheet == "Shown"


def test_the_header_is_the_first_non_empty_row_wherever_it_starts(tmp_path):
    rows = [[], [], [None, "Region", "Sales"], [None, "East", 1], [None, "West", 2], [None, None, None]]
    data = read_data(make_xlsx(tmp_path / "offset.xlsx", {"S": rows}))
    assert data.names() == ["Region", "Sales"] and data.grid == "B3:C5"
    assert [f["datatype"] for f in data.fields] == ["string", "integer"]


def test_a_blank_header_is_named_and_a_repeated_one_is_suffixed_with_a_warning(tmp_path):
    path = make_xlsx(tmp_path / "dup.xlsx", {"S": [["id", "name", "name", None, "id"], [1, "a", "b", 5, 2]]})
    with pytest.warns(UserWarning, match="repeats the header 'name'"):
        data = read_data(path)
    assert data.names() == ["id", "name", "name1", "F4", "id1"]


def test_an_empty_sheet_and_the_old_formats_are_refused(tmp_path):
    with pytest.raises(TemplateError, match="empty"):
        read_data(make_xlsx(tmp_path / "e.xlsx", {"S": []}))
    old = tmp_path / "old.xls"
    old.write_bytes(b"\xd0\xcf\x11\xe0")
    with pytest.raises(TemplateError, match=r"old Excel formats \(\.xls\) are not read"):
        read_data(str(old))
    notxlsx = tmp_path / "fake.xlsx"
    notxlsx.write_text("not a zip", encoding="utf-8")
    with pytest.raises(TemplateError, match="not a readable Excel file"):
        read_data(str(notxlsx))


def test_without_openpyxl_the_error_says_what_to_install(tmp_path, monkeypatch):
    path = make_xlsx(tmp_path / "t.xlsx", {"S": ORDERS})
    monkeypatch.setitem(sys.modules, "openpyxl", None)
    with pytest.raises(TemplateError, match=r"pip install 'py-tbparse\[excel\]'"):
        read_data(path)


def test_only_a_sample_of_a_long_sheet_is_read(tmp_path):
    rows = [["n", "t"]] + [[i, "x"] for i in range(2600)]
    data = read_data(make_xlsx(tmp_path / "long.xlsx", {"S": rows}))
    assert data.grid == "A1:B2601"


# --- the connection ---------------------------------------------------------------------------------------


def _data(tmp_path, name="Orders sheet"):
    return read_data(make_xlsx(tmp_path / "orders.xlsx", {name: ORDERS}))


def _locals(data):
    return {f["name"]: f"[{f['name']}]" for f in data.fields}


def test_the_connection_has_the_shape_tableau_writes(tmp_path):
    data = _data(tmp_path)
    conn, extras = _excel_connection(data, _locals(data), model=None)
    assert extras == []
    named = conn.find("named-connections/named-connection")
    assert named.get("caption") == "orders" and named.get("name").startswith("excel-direct.")
    inner = named.find("connection")
    assert dict(inner.attrib) == {
        "class": "excel-direct", "cleaning": "no", "compat": "no", "dataRefreshTime": "",
        "filename": Path(data.path).as_posix(), "interpretationMode": "0", "password": "", "server": "", "validate": "no"}
    rel = conn.find("relation")
    assert (rel.get("name"), rel.get("table"), rel.get("type"), rel.get("connection")) == (
        "Orders sheet", "[Orders sheet$]", "table", named.get("name"))
    assert dict(rel.find("columns").attrib) == {"gridOrigin": "A1:G3:no:A1:G3:0", "header": "yes", "outcome": "2"}
    records = {r.findtext("remote-name"): r for r in conn.xpath("metadata-records/metadata-record")}
    expected = {"Category": ("130", "Count", '"WSTR"'), "Number of Records": ("20", "Sum", '"I8"'),
                "Order Date": ("7", "Year", '"DATE"'), "Sales Target": ("5", "Sum", '"R8"'),
                "Paid": ("11", "Count", '"WINBOOL"'), "Shipped": ("7", "Year", '"DATE"')}
    for name, (code, aggregation, debug) in expected.items():
        r = records[name]
        assert (r.findtext("remote-type"), r.findtext("aggregation"), r.findtext("parent-name")) == (
            code, aggregation, "[Orders sheet]")
        assert r.findtext("attributes/attribute") == debug
        assert [c.tag for c in r][-1] == "attributes"


@pytest.mark.parametrize("model", ["prefixed", "plain"])
def test_the_object_model_forms_match_the_csv_ones(tmp_path, model):
    data = _data(tmp_path)
    conn, extras = _excel_connection(data, _locals(data), model=model, object_id="Orders_sheet_ID")
    table_col, graph = extras
    assert table_col.get("name") == "[__tableau_internal_object_id__].[Orders_sheet_ID]"
    assert table_col.get("caption") == "Orders sheet" and table_col.get("datatype") == "table"
    assert graph.find("objects/object").get("id") == "Orders_sheet_ID"
    assert graph.find("objects/object/properties/relation").get("table") == "[Orders sheet$]"
    relations = [e for e in conn if e.tag.endswith("relation")]
    assert len(relations) == (2 if model == "prefixed" else 1)
    assert [e.text for e in conn.iter() if e.tag.endswith("object-id")] == ["[Orders_sheet_ID]"] * 7


# --- applying ---------------------------------------------------------------------------------------------


@pytest.fixture
def cache_template(tmp_path, monkeypatch):
    monkeypatch.setattr(templates, "_now", lambda: "2026-10-02T00:00:00+00:00")
    book = tmp_path / "Cache.twbx"
    shutil.copy(PUBLIC / "Cache.twbx", book)
    return load_template(make_template(str(book), output_path=str(tmp_path / "cache.template.twbx"), template_id="tpl-1"))


def _connection_of(path):
    z = zipfile.ZipFile(path)
    doc = etree.fromstring(z.read(next(n for n in z.namelist() if n.endswith(".twb"))))
    return doc


def test_a_template_applies_to_a_worksheet_and_the_answers_remember_the_sheet(cache_template, tmp_path):
    xlsx = make_xlsx(tmp_path / "q3.xlsx", {"Orders": ORDERS, "Other": [["z"], [1]]})
    entry = cache_template.manifest["datasources"][0]["name"]
    with pytest.raises(TemplateError, match="2 visible sheets"):
        apply_template(cache_template, xlsx, datasource=entry, allow_missing=True)
    out = apply_template(cache_template, xlsx, datasource=entry, allow_missing=True, sheet="Orders",
                         output_path=str(tmp_path / "out.twbx"))
    doc = _connection_of(out)
    assert doc.xpath("//datasource[@name=$n]//connection[@class='excel-direct']", n=entry)
    assert doc.xpath("//relation[@table='[Orders$]']")
    answers = read_answers(out)
    assert answers["data"]["kind"] == "excel" and answers["data"]["sheet"] == "Orders"
    again = apply_template(cache_template, answers=out, allow_missing=True, output_path=str(tmp_path / "again.twbx"))
    assert zipfile.ZipFile(out).read(next(n for n in zipfile.ZipFile(out).namelist() if n.endswith(".twb"))) == \
        zipfile.ZipFile(again).read(next(n for n in zipfile.ZipFile(again).namelist() if n.endswith(".twb")))
    assert read_answers(again)["data"]["sheet"] == "Orders"


def test_mapping_works_on_excel_columns_like_on_csv(cache_template, tmp_path):
    data = read_data(make_xlsx(tmp_path / "q3.xlsx", {"Orders": ORDERS}))
    mapping = suggest_mapping(cache_template, data)
    row = mapping.set_index("field")
    assert row.loc["[Category]", "mapped_to"] == "Category"
    assert row.loc["[Order Date]", "mapped_to"] == "Order Date"


def test_a_column_with_no_values_takes_the_type_of_the_field_it_feeds(cache_template, tmp_path):
    rows = [["Category", "Segment", "Sales Target"], ["a", None, None]]
    out = apply_template(cache_template, make_xlsx(tmp_path / "e.xlsx", {"S": rows}), allow_missing=True,
                         output_path=str(tmp_path / "o.twbx"))
    doc = _connection_of(out)
    records = {r.findtext("remote-name"): r.findtext("local-type") for r in doc.xpath("//metadata-record[@class='column']")}
    assert records["Segment"] == "string" and records["Sales Target"] == "integer"


@pytest.mark.parametrize("name", ["filtering.twb", "datasource_test.twb", "Cache.twbx", "TABLEAU_10_TWBX.twbx"])
def test_an_excel_backed_output_adds_no_schema_or_reference_errors(name, tmp_path):
    book = tmp_path / name
    shutil.copy(PUBLIC / name, book)
    template = load_template(make_template(str(book)))
    entry = next(e for e in template.manifest["datasources"] if e["fields"])
    xlsx = make_xlsx(tmp_path / "data.xlsx", {"Data": [[f["remote"] for f in entry["fields"]]]})
    unfed = set(suggest_mapping(template, read_data(xlsx), datasource=entry["name"]).query("mapped_to == ''")["field"])
    out = apply_template(template, xlsx, datasource=entry["name"], allow_missing=True,
                         output_path=str(tmp_path / "out.twbx"))
    schema, refs = introduced(book, tmp_path, "apply-excel", twb_bytes(out), unfed)
    assert schema == [] and refs == []


def test_the_command_line_takes_excel_and_a_sheet(cache_template, tmp_path, capsys):
    xlsx = make_xlsx(tmp_path / "q3.xlsx", {"Orders": ORDERS, "Other": [["z"], [1]]})
    assert main(["template", "apply", cache_template.path, "--data", xlsx]) == 1
    assert "pick one with sheet=" in capsys.readouterr().err
    assert main(["template", "apply", cache_template.path, "--data", xlsx, "--sheet", "Orders"]) == 0
    assert "Category" in capsys.readouterr().out
    assert main(["template", "apply", cache_template.path, "--data", xlsx, "--sheet", "0"]) == 0
