"""WP17b/17c: many files as one source (`multifile.py`) and `template drift` (`template_drift.py`).

Every fixture is made in a temp folder; nothing here is checked in Tableau Desktop."""

import datetime as dt
import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from py_tbparse import TemplateError, findings, make_template, read_many, resolve_apply
from py_tbparse.cli import main
from py_tbparse.findings import FINDING_COLUMNS
from py_tbparse.multifile import MAX_FILES, merge_types, read_part, resolve_files
from py_tbparse.template_drift import build_context, check_drift, drift_rule_ids, save_union_answers
from py_tbparse.templates import ANSWERS_FORMAT, load_answers

PUBLIC = Path(__file__).parent / "fixtures" / "public"
HEAD = "Category,Number of Records,Order Date,Sales Target,Segment\n"
GOOD = "Furniture,1,2026-01-31,10,Consumer\nOffice,2,2026-02-01,20,Corporate\n"


@pytest.fixture
def template(tmp_path):
    book = tmp_path / "Cache.twbx"
    shutil.copy(PUBLIC / "Cache.twbx", book)
    return make_template(str(book), output_path=str(tmp_path / "sales.template.twbx"), template_id="tpl-1")


@pytest.fixture
def monthly(tmp_path):
    """A folder of CSVs: jan is clean, the others each drift in one way."""
    d = tmp_path / "monthly"
    d.mkdir()
    (d / "jan.csv").write_text(HEAD + GOOD, encoding="utf-8")
    (d / "feb.csv").write_text("Segment,Category,Number of Records,Order Date,Sales Target,Region\n"
                               "Consumer,Furniture,1,2026-01-31,10,East\n", encoding="utf-8")
    (d / "mar.csv").write_text("Category,Number of Records,Order Date,sales target,Segments\n"
                               "Furniture,1,2026-01-31,10,Consumer\n", encoding="utf-8")
    (d / "apr.csv").write_bytes("Category;Number of Records;Order Date;Sales Target;Segment\n"
                                "Caf\xe9;1;2026-01-31;10;Consumer\n".encode("cp1252"))
    (d / "may.csv").write_text(HEAD, encoding="utf-8")
    (d / "jun.csv").write_text(HEAD + "Furniture,1,2026-01-31,abc,Consumer\n", encoding="utf-8")
    (d / "jul.csv").write_text("Number of Records,Order Date,Sales Target,Segment\n1,2026-01-31,10,Consumer\n",
                               encoding="utf-8")
    return d


def rows(df, rule=None):
    return [(r.object, r.severity, r.detail) for r in df.itertuples() if rule in (None, r.rule)]


def objects(df, rule):
    return sorted(r.object for r in df.itertuples() if r.rule == rule)


# ------------------------------------------------------------ 17b: files --

def test_a_folder_a_glob_and_a_list_resolve_to_the_same_sorted_files(monthly):
    paths, root = resolve_files(str(monthly))
    names = [p.name for p in paths]
    assert names == sorted(names) == ["apr.csv", "feb.csv", "jan.csv", "jul.csv", "jun.csv", "mar.csv", "may.csv"]
    assert Path(root) == monthly.resolve()
    assert [p.name for p in resolve_files(str(monthly / "*.csv"))[0]] == names
    assert [p.name for p in resolve_files(str(monthly / "j*.csv"))[0]] == ["jan.csv", "jul.csv", "jun.csv"]
    assert [p.name for p in resolve_files([str(monthly / "jan.csv"), str(monthly / "j*.csv")])[0]] == \
        ["jan.csv", "jul.csv", "jun.csv"]


def test_lock_hidden_and_other_files_are_left_out(tmp_path):
    (tmp_path / "a.csv").write_text(HEAD + GOOD)
    (tmp_path / "~$b.xlsx").write_bytes(b"lock")
    (tmp_path / ".hidden.csv").write_text(HEAD)
    (tmp_path / "notes.md").write_text("x")
    assert [p.name for p in resolve_files(str(tmp_path))[0]] == ["a.csv"]
    assert [p.name for p in resolve_files(str(tmp_path / "*"))[0]] == ["a.csv"]


def test_subfolders_need_a_double_star_and_keep_their_path_in_the_name(tmp_path):
    (tmp_path / "2026").mkdir()
    (tmp_path / "2026" / "a.csv").write_text(HEAD + GOOD)
    (tmp_path / "b.csv").write_text(HEAD + GOOD)
    assert [p.name for p in read_many(str(tmp_path)).parts] == ["b.csv"]
    assert [p.name for p in read_many(str(tmp_path / "**" / "*.csv")).parts] == ["2026/a.csv", "b.csv"]


def test_nothing_matching_a_missing_path_and_too_many_files_are_errors(tmp_path):
    with pytest.raises(TemplateError, match="no CSV, TSV or Excel file"):
        resolve_files(str(tmp_path / "*.csv"))
    with pytest.raises(FileNotFoundError):
        resolve_files(str(tmp_path / "gone"))
    with pytest.raises(TemplateError, match="no files given"):
        resolve_files([])
    for i in range(3):
        (tmp_path / f"f{i}.csv").write_text(HEAD + GOOD)
    with pytest.raises(TemplateError, match="3 files match; at most 2"):
        resolve_files(str(tmp_path), max_files=2)
    assert MAX_FILES == 500


def test_merge_types_rule():
    assert merge_types([]) is None and merge_types([None, None]) is None
    assert merge_types(["integer", None, "integer"]) == "integer"
    assert merge_types(["integer", "real"]) == "real"
    assert merge_types(["date", "datetime"]) == "datetime"
    assert merge_types(["integer", "string"]) == "string"
    assert merge_types(["boolean", "integer"]) == "string"
    assert merge_types(["date", "integer", "real"]) == "string"


def test_read_many_merges_columns_types_and_fingerprints(tmp_path):
    (tmp_path / "a.csv").write_text("id,amount,day\n1,2,2026-01-01\n")
    (tmp_path / "b.csv").write_text("id,amount,note\n2,2.5,x\n")
    (tmp_path / "c.csv").write_text("id,amount,day\n3,4,2026-01-02 10:00:00\n")
    multi = read_many(str(tmp_path))
    assert multi.names() == ["id", "amount", "day", "note"]
    assert {f["name"]: f["datatype"] for f in multi.merged.fields} == \
        {"id": "integer", "amount": "real", "day": "datetime", "note": "string"}
    assert multi.conflicts["amount"] == {"integer": ["a.csv", "c.csv"], "real": ["b.csv"]}
    assert "id" not in multi.conflicts
    a, b, c = (p.fingerprint for p in multi.parts)
    assert len({a, b, c}) == 3 and multi.fingerprint not in (a, b, c)
    assert all(f.startswith("sha256:") for f in (a, b, c, multi.fingerprint))
    # the same shape gives the same fingerprint, whatever the rows are
    (tmp_path / "d.csv").write_text("id,amount,day\n9,9,2027-01-01\n8,7,2027-01-02\n")
    again = read_many(str(tmp_path))
    assert again.parts[3].fingerprint == a == read_many(str(tmp_path / "a.csv")).parts[0].fingerprint


def test_a_column_with_no_values_in_one_file_agrees_with_any_type(tmp_path):
    (tmp_path / "a.csv").write_text("id,amount\n1,5\n")
    (tmp_path / "b.csv").write_text("id,amount\n2,\n")
    multi = read_many(str(tmp_path))
    assert multi.merged.datatype("amount") == "integer" and multi.conflicts == {}


def test_encoding_and_separator_are_sniffed(tmp_path):
    (tmp_path / "u.csv").write_text("a,b\n1,2\n", encoding="utf-8-sig")
    (tmp_path / "w.csv").write_text("a,b\n1,2\n", encoding="utf-16")
    (tmp_path / "l.csv").write_bytes("a;b\nCaf\xe9;2\n".encode("cp1252"))
    (tmp_path / "t.tsv").write_text("a\tb\n1\t2\n")
    (tmp_path / "q.csv").write_text('"a,x",b\n1,2\n')
    got = {p.name: (p.encoding, p.separator, p.columns) for p in read_many(str(tmp_path)).parts}
    assert got["u.csv"] == ("utf-8", ",", ["a", "b"])
    assert got["w.csv"] == ("utf-16", ",", ["a", "b"])
    assert got["l.csv"] == ("cp1252", ";", ["a", "b"])
    assert got["t.tsv"] == ("utf-8", "\t", ["a", "b"])
    assert got["q.csv"][1] == "," and got["q.csv"][2] == ["a,x", "b"]


def test_empty_and_unreadable_files_do_not_stop_the_read(tmp_path):
    (tmp_path / "ok.csv").write_text("a,b\n1,2\n")
    (tmp_path / "zero.csv").write_bytes(b"")
    (tmp_path / "head.csv").write_text("a,b\n")
    (tmp_path / "ragged.csv").write_text("a,b\n1,2,3,4\n5\n6,7,8,9,10\n")
    multi = read_many(str(tmp_path))
    status = {p.name: p.status for p in multi.parts}
    assert status["ok.csv"] == "ok" and status["zero.csv"] == "empty" and status["head.csv"] == "empty"
    assert status["ragged.csv"] == "unreadable" and "not readable as a CSV" in {p.name: p.error for p in multi.parts}["ragged.csv"]
    assert multi.names() == ["a", "b"]
    assert read_part(tmp_path / "zero.csv").data is None and read_part(tmp_path / "head.csv").data is not None


def test_the_answers_block_has_relative_paths_and_loads_back(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "a.csv").write_text("a,b\n1,2\n")
    multi = read_many(str(tmp_path / "data" / "*.csv"))
    block = multi.block(str(tmp_path))
    assert block["kind"] == "union" and block["files"][0]["path"] == "data/a.csv"
    assert block["files"][0]["fingerprint"] == multi.parts[0].fingerprint
    assert block["schema_fingerprint"] == multi.fingerprint and block["columns"] == ["a", "b"]
    json.dumps(block)


# --------------------------------------------------------------- 17b: excel --

try:
    import openpyxl
except ImportError:      # the Excel tests skip, the rest of the file runs
    openpyxl = None

needs_excel = pytest.mark.skipif(openpyxl is None, reason="needs openpyxl (pip install 'py-tbparse[excel]')")


def make_xlsx(path, sheets):
    book = openpyxl.Workbook()
    book.remove(book.active)
    for name, rows_ in sheets.items():
        ws = book.create_sheet(name)
        for row in rows_:
            ws.append(row)
    book.save(str(path))
    return str(path)


EXCEL_ROWS = [["Category", "Number of Records", "Order Date", "Sales Target", "Segment"],
              ["Furniture", 1, dt.datetime(2026, 1, 31), 10, "Consumer"]]


@needs_excel
def test_excel_and_csv_files_merge_into_one_source(tmp_path):
    make_xlsx(tmp_path / "x.xlsx", {"Orders": EXCEL_ROWS})
    (tmp_path / "y.csv").write_text(HEAD + GOOD)
    multi = read_many(str(tmp_path))
    assert [p.kind for p in multi.parts] == ["excel", "csv"] and multi.merged.kind == "mixed"
    assert multi.parts[0].origin == "A1" and multi.parts[0].sheet == "Orders" and multi.parts[0].rows == 1
    assert multi.names() == ["Category", "Number of Records", "Order Date", "Sales Target", "Segment"]


@needs_excel
def test_excel_with_two_visible_sheets_needs_sheet_and_a_missing_sheet_is_its_own_status(tmp_path):
    make_xlsx(tmp_path / "x.xlsx", {"Orders": EXCEL_ROWS, "Other": EXCEL_ROWS})
    assert read_many(str(tmp_path)).parts[0].status == "unreadable"
    assert read_many(str(tmp_path), sheet="Orders").parts[0].status == "ok"
    assert read_many(str(tmp_path), sheet="Gone").parts[0].status == "no-sheet"
    assert read_many(str(tmp_path), sheet=5).parts[0].status == "no-sheet"
    (tmp_path / "bad.xlsx").write_bytes(b"not a zip")
    assert {p.name: p.status for p in read_many(str(tmp_path), sheet="Orders").parts}["bad.xlsx"] == "unreadable"


# ------------------------------------------------------------- 17c: rules --

def test_the_drift_rules_have_stable_ids():
    assert drift_rule_ids() == ["D001", "D002", "D003", "D004", "D005", "D006", "D007", "D008", "D009", "D010", "D011"]


def test_each_kind_of_drift_is_reported_for_its_file(template, monthly):
    df = check_drift(template, str(monthly))
    assert list(df.columns) == FINDING_COLUMNS
    assert df.attrs["files"] == 7 and df.attrs["fingerprint"].startswith("sha256:")
    assert df.attrs["scope"] == "drift" and df.attrs["saved_fingerprint"] is None
    # jul lacks a required column: an error; mar lacks two optional ones: warnings
    assert rows(df, "D001") == [
        ("jul.csv: Category", "error", "the column mapped to Category is missing"),
        ("mar.csv: Sales Target", "warning", "the column mapped to Sales Target is missing (the field is optional)"),
        ("mar.csv: Segment", "warning", "the column mapped to Segment is missing (the field is optional)")]
    assert rows(df, "D002") == [("apr.csv", "error", "the encoding is cp1252; most files are utf-8"),
                                ("apr.csv", "error", "the separator is a semicolon; most files use a comma")]
    assert objects(df, "D003") == ["feb.csv: Region"]
    assert rows(df, "D004") == [("mar.csv: Segment", "warning",
                                 "the column is missing and 'Segments' looks like it renamed (similar name)")]
    assert objects(df, "D005") == ["mar.csv: Sales Target"] and "'sales target'" in rows(df, "D005")[0][2]
    assert rows(df, "D006") == [("jun.csv: Sales Target", "error",
                                 "the column reads as string; most files read it as integer (merged: string), "
                                 "and the template field wants integer")]
    assert objects(df, "D008") == ["may.csv"]
    assert objects(df, "D009") == ["feb.csv"] and df[df.rule == "D009"].iloc[0].severity == "info"
    assert not (df.rule.isin(["D007", "D010", "D011"])).any()
    # a renamed column is not also reported as an extra one
    assert "mar.csv" not in " ".join(objects(df, "D003"))


def test_a_clean_folder_has_no_findings(template, tmp_path):
    for n in ("a", "b"):
        (tmp_path / f"{n}.csv").write_text(HEAD + GOOD)
    df = check_drift(template, str(tmp_path))
    assert df.empty and df.attrs["files"] == 2


def test_only_and_skip_take_rule_ids(template, monthly):
    assert set(check_drift(template, str(monthly), only="D002").rule) == {"D002"}
    assert "D001" not in set(check_drift(template, str(monthly), skip=["D001"]).rule)
    with pytest.raises(ValueError, match="unknown rule D999"):
        check_drift(template, str(monthly), only=["D999"])


def test_a_required_field_no_file_has_is_reported_once(template, tmp_path):
    (tmp_path / "a.csv").write_text("Number of Records,Segment\n1,x\n")
    (tmp_path / "b.csv").write_text("Number of Records,Segment\n2,y\n")
    got = rows(check_drift(template, str(tmp_path)), "D001")
    assert got == [("Category", "error", "no file has a column for this required field")]


@needs_excel
def test_unreadable_and_empty_files(template, tmp_path):
    (tmp_path / "ok.csv").write_text(HEAD + GOOD)
    (tmp_path / "zero.csv").write_bytes(b"")
    make_xlsx(tmp_path / "multi.xlsx", {"A": EXCEL_ROWS, "B": EXCEL_ROWS})
    df = check_drift(template, str(tmp_path))
    assert rows(df, "D008") == [("zero.csv", "warning", "the file has no content")]
    assert objects(df, "D011") == ["multi.xlsx"] and "visible sheets" in rows(df, "D011")[0][2]
    # the unreadable file adds no column findings: its columns are unknown
    assert not any(o.startswith("multi.xlsx:") for o in df.object)


@needs_excel
def test_excel_header_moved_and_sheet_missing(template, tmp_path):
    make_xlsx(tmp_path / "a.xlsx", {"Orders": EXCEL_ROWS})
    make_xlsx(tmp_path / "b.xlsx", {"Orders": EXCEL_ROWS})
    make_xlsx(tmp_path / "moved.xlsx", {"Orders": [[], [], *EXCEL_ROWS]})
    make_xlsx(tmp_path / "other.xlsx", {"Totals": EXCEL_ROWS})
    df = check_drift(template, str(tmp_path), sheet="Orders")
    assert rows(df, "D007") == [
        ("other.xlsx", "error", "other.xlsx has no sheet 'Orders'; it has: Totals"),
        ("moved.xlsx", "warning", "the header starts at A3; most files start at A1")]


@needs_excel
def test_the_header_cell_follows_the_most_common_origin(template, tmp_path):
    make_xlsx(tmp_path / "a.xlsx", {"Orders": [[], *EXCEL_ROWS]})
    make_xlsx(tmp_path / "b.xlsx", {"Orders": [[], *EXCEL_ROWS]})
    make_xlsx(tmp_path / "c.xlsx", {"Orders": EXCEL_ROWS})
    assert objects(check_drift(template, str(tmp_path), sheet="Orders"), "D007") == ["c.xlsx"]


def test_a_type_tie_goes_to_the_type_the_template_wants(template, tmp_path):
    (tmp_path / "a.csv").write_text(HEAD + GOOD)
    (tmp_path / "b.csv").write_text(HEAD + "Furniture,1,2026-01-31,abc,Consumer\n")
    df = check_drift(template, str(tmp_path))
    assert objects(df, "D006") == ["b.csv: Sales Target"]


def test_an_unmapped_column_that_files_disagree_on_is_a_warning(template, tmp_path):
    (tmp_path / "a.csv").write_text(HEAD.strip() + ",Extra\n" + "Furniture,1,2026-01-31,10,Consumer,5\n")
    (tmp_path / "b.csv").write_text(HEAD.strip() + ",Extra\n" + "Furniture,1,2026-01-31,10,Consumer,five\n")
    (tmp_path / "c.csv").write_text(HEAD.strip() + ",Extra\n" + "Furniture,1,2026-01-31,10,Consumer,6\n")
    got = rows(check_drift(template, str(tmp_path)), "D006")
    assert got == [("b.csv: Extra", "warning", "the column reads as string; most files read it as integer (merged: string)")]


# ------------------------------------------------------------ 17c: answers --

def _answers(tmp_path, template, **extra):
    """Answers as `template apply` writes them (made by hand: the mapping, columns and, optionally, the files)."""
    t = load_answers_template(template)
    data = {"file": "jan.csv", "kind": "csv", "schema_fingerprint": "sha256:old",
            "columns": ["Category", "Number of Records", "Order Date", "Sales Target", "Segment"], **extra}
    entry = {"datasource": t["datasources"][0]["name"], "data": data,
             "mapping": {"[Category]": "Category", "[Number of Records]": "Number of Records",
                         "[Sales Target]": "Sales Target"}, "missing": []}
    answers = {"format": ANSWERS_FORMAT, "version": 2, "template": {"id": "tpl-1", "manifest": t},
               "data": data, "datasource": entry["datasource"], "mapping": entry["mapping"], "missing": [],
               "datasources": [entry], "parameters": {}}
    path = tmp_path / "saved.answers.json"
    path.write_text(json.dumps(answers), encoding="utf-8")
    return str(path)


def load_answers_template(template):
    from py_tbparse import load_template
    return load_template(template).manifest


def test_answers_alone_are_a_reference_and_old_answers_load_unchanged(template, monthly, tmp_path):
    path = _answers(tmp_path, template)
    before = load_answers(path)
    df = check_drift(path, str(monthly))
    # the saved mapping decides for the fields it names; the others are matched as usual
    assert objects(df, "D001") == ["jul.csv: Category", "mar.csv: Sales Target", "mar.csv: Segment"]
    assert objects(df, "D003") == ["feb.csv: Region"]
    assert objects(df, "D004") == ["mar.csv: Segment"] and objects(df, "D005") == ["mar.csv: Sales Target"]
    assert not df.rule.isin(["D010"]).any()                    # a single-file block says nothing about new files
    assert load_answers(path) == before
    assert df.attrs["saved_fingerprint"] == "sha256:old"


def test_a_saved_column_no_file_has_any_more_is_still_the_mapped_column(template, tmp_path):
    path = _answers(tmp_path, template)
    for n in ("a", "b"):
        (tmp_path / f"{n}.csv").write_text("Category,Number of Records,Order Date,sales target,Segment\nx,1,2026-01-31,3,y\n")
    df = check_drift(path, str(tmp_path / "*.csv"))
    assert objects(df, "D001") == ["a.csv: Sales Target", "b.csv: Sales Target"]
    assert objects(df, "D005") == ["a.csv: Sales Target", "b.csv: Sales Target"]


def test_files_new_and_gone_since_the_saved_answers(template, tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    for n in ("jan", "feb", "mar"):
        (d / f"{n}.csv").write_text(HEAD + GOOD)
    path = _answers(tmp_path, template, kind="union", pattern="data/*.csv",
                    files=[{"path": "data/jan.csv", "fingerprint": "x"}, {"path": "data/feb.csv", "fingerprint": "x"},
                           {"path": "data/dec.csv", "fingerprint": "x"}])
    df = check_drift(template, str(d), answers=path)
    assert rows(df, "D010") == [
        ("dec.csv", "info", "the saved answers list this file and these files do not include it"),
        ("mar.csv", "info", "the file is new since the saved answers")]


def test_answers_made_for_another_template_are_refused(template, tmp_path, monthly):
    path = _answers(tmp_path, template)
    data = json.loads(Path(path).read_text())
    data["template"]["id"] = "other"
    Path(path).write_text(json.dumps(data))
    with pytest.raises(TemplateError, match="another template"):
        check_drift(template, str(monthly), answers=path)


def test_answers_without_a_manifest_need_the_template(tmp_path, monthly):
    path = tmp_path / "bare.json"
    path.write_text(json.dumps({"format": ANSWERS_FORMAT, "version": 2, "template": {"id": "x"}}))
    with pytest.raises(TemplateError, match="pass the template as well"):
        check_drift(str(path), str(monthly))


def test_save_answers_writes_the_union_block_and_never_overwrites(template, monthly, tmp_path):
    path = _answers(tmp_path, template)
    out = tmp_path / "out" / "new.answers.json"
    out.parent.mkdir()
    save_union_answers(template, str(monthly), str(out), answers=path)
    saved = json.loads(out.read_text())
    block = saved["datasources"][0]["data"]
    assert block["kind"] == "union" and saved["data"] == block and "_base_dir" not in saved
    assert sorted(f["path"] for f in block["files"])[0] == "../monthly/apr.csv"       # relative to out/
    assert all(f["fingerprint"].startswith("sha256:") for f in block["files"])
    assert load_answers(str(out))["datasources"][0]["data"]["kind"] == "union"
    with pytest.raises(FileExistsError):
        save_union_answers(template, str(monthly), str(out), answers=path)
    with pytest.raises(TemplateError, match="needs answers"):
        save_union_answers(template, str(monthly), str(tmp_path / "x.json"))
    # the original is untouched, and drift against the new block sees no new or gone file
    assert json.loads(Path(path).read_text())["data"]["kind"] == "csv"
    again = check_drift(template, str(monthly), answers=str(out))
    assert not again.rule.isin(["D010"]).any()
    assert again.attrs["saved_fingerprint"] == again.attrs["fingerprint"]


def test_applying_to_answers_that_hold_many_files_says_so(template, tmp_path, monthly):
    out = tmp_path / "new.answers.json"
    save_union_answers(template, str(monthly), str(out), answers=_answers(tmp_path, template))
    with pytest.raises(TemplateError, match="not built yet"):
        resolve_apply(template, answers=str(out))


# --------------------------------------------------------------------- CLI --

def run_cli(argv, capsys):
    rc = main(argv)
    out = capsys.readouterr()
    return rc, out.out, out.err


def test_cli_table_exit_codes_and_the_summary(template, monthly, capsys):
    rc, out, err = run_cli(["template", "drift", template, str(monthly)], capsys)
    assert rc == 1 and "D001" in out and "jul.csv: Category" in out
    assert "7 file(s), merged fingerprint sha256:" in err and "errors" in err
    assert run_cli(["template", "drift", template, str(monthly), "--fail-on", "never"], capsys)[0] == 0
    assert run_cli(["template", "drift", template, str(monthly), "--only", "D009", "--fail-on", "warning"], capsys)[0] == 0
    assert run_cli(["template", "drift", template, str(monthly), "--only", "D008", "--fail-on", "warning"], capsys)[0] == 1


def test_cli_takes_a_quoted_glob_and_a_shell_expanded_list(template, monthly, capsys):
    rc, _, err = run_cli(["template", "drift", template, str(monthly / "j*.csv"), "--fail-on", "never"], capsys)
    assert rc == 0 and "3 file(s)" in err
    rc, _, err = run_cli(["template", "drift", template, str(monthly / "jan.csv"), str(monthly / "feb.csv"),
                          "--fail-on", "never"], capsys)
    assert rc == 0 and "2 file(s)" in err


def test_cli_ci_formats(template, monthly, capsys):
    rc, out, _ = run_cli(["template", "drift", template, str(monthly), "--format", "junit"], capsys)
    suite = ET.fromstring(out).find("testsuite")
    assert rc == 1 and suite.get("name") == "py-tbparse template drift" and int(suite.get("failures")) >= 3
    classes = {c.get("classname") for c in suite.findall("testcase")}
    assert {"D001", "D002", "D006", "D009"} <= classes
    rc, out, _ = run_cli(["template", "drift", template, str(monthly), "--format", "sarif", "--fail-on", "never"], capsys)
    run = json.loads(out)["runs"][0]
    assert [r["id"] for r in run["tool"]["driver"]["rules"]] == drift_rule_ids()
    levels = {r["ruleId"]: r["level"] for r in run["results"]}
    assert levels["D001"] in ("error", "warning") and levels["D009"] == "note" and levels["D002"] == "error"
    rc, out, _ = run_cli(["template", "drift", template, str(monthly), "--format", "github", "--fail-on", "never"], capsys)
    assert "::error " in out and "title=D002" in out and "::notice " in out


def test_cli_json_and_csv(template, monthly, capsys):
    rc, out, _ = run_cli(["template", "drift", template, str(monthly), "-f", "json", "--fail-on", "never"], capsys)
    assert {r["rule"] for r in json.loads(out)} >= {"D001", "D002", "D003"}
    rc, out, _ = run_cli(["template", "drift", template, str(monthly), "-f", "csv", "--fail-on", "never"], capsys)
    assert out.splitlines()[0] == ",".join(FINDING_COLUMNS)


def test_cli_errors_are_exit_2(template, monthly, tmp_path, capsys):
    assert run_cli(["template", "drift", template, str(tmp_path / "none" / "*.csv")], capsys)[0] == 2
    assert run_cli(["template", "drift", str(tmp_path / "gone.twbx"), str(monthly)], capsys)[0] == 2
    assert run_cli(["template", "drift", template, str(monthly), "--only", "D999"], capsys)[0] == 2
    assert run_cli(["template", "drift", template, str(monthly), "--only", " "], capsys)[0] == 2
    rc, _, err = run_cli(["template", "drift", template, str(monthly), "--max-files", "2"], capsys)
    assert rc == 2 and "at most 2" in err


def test_cli_save_answers(template, monthly, tmp_path, capsys):
    path = _answers(tmp_path, template)
    out = tmp_path / "new.answers.json"
    rc, _, err = run_cli(["template", "drift", template, str(monthly), "-a", path, "--save-answers", str(out),
                          "--fail-on", "never"], capsys)
    assert rc == 0 and out.exists() and f"wrote {out}" in err
    rc, _, err = run_cli(["template", "drift", template, str(monthly), "-a", path, "--save-answers", str(out)], capsys)
    assert rc == 2 and "refusing to overwrite" in err
    rc, _, err = run_cli(["template", "drift", path, str(monthly), "--fail-on", "never"], capsys)
    assert rc == 0 and "differs from the saved answers" in err


def test_a_crashing_rule_is_exit_3(template, monthly, capsys):
    saved = dict(findings._RULES)

    @findings.rule("D990", "drift", severity="info")
    def boom(subject):
        """A rule that always fails (test only)."""
        raise KeyError("x")
    try:
        rc, out, err = run_cli(["template", "drift", template, str(monthly), "--fail-on", "never"], capsys)
        assert rc == 3 and "D990" in out and "Traceback" in err
    finally:
        findings._RULES.clear()
        findings._RULES.update(saved)


def test_the_context_names_the_baseline(template, monthly):
    ctx = build_context(template, str(monthly))
    assert ctx.ref_order == ["Category", "Number of Records", "Order Date", "Sales Target", "Segment"]
    assert {"Region", "Segments"}.isdisjoint(ctx.ref_names)
