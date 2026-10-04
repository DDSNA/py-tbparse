"""`template apply-folder`: one template, many data files."""

import datetime as dt
import json
import zipfile
import shutil
from pathlib import Path

import pandas as pd
import pytest

import py_tbparse.templates as templates
from py_tbparse import TemplateError, apply_template_folder, load_template, make_template
from py_tbparse.cli import main
from py_tbparse.template_batch import SUMMARY_COLUMNS, read_inputs
from py_tbparse.templates import read_answers

PUBLIC = Path(__file__).parent / "fixtures" / "public"
HEADER = "Category,Number of Records,Order Date,Sales Target,Segment\n"
GOOD = HEADER + "Furniture,1,2026-01-31,10,Consumer\nOffice,2,2026-02-01,20,Corporate\n"


@pytest.fixture
def batch(tmp_path, monkeypatch):
    """A template and a folder holding two good CSVs and one that lacks a required column."""
    monkeypatch.setattr(templates, "_now", lambda: "2026-10-02T00:00:00+00:00")
    book = tmp_path / "Cache.twbx"
    shutil.copy(PUBLIC / "Cache.twbx", book)
    template = make_template(str(book), output_path=str(tmp_path / "sales.template.twbx"), template_id="tpl-1")
    folder = tmp_path / "customers"
    folder.mkdir()
    (folder / "acme.csv").write_text(GOOD, encoding="utf-8")
    (folder / "globex.csv").write_text(GOOD, encoding="utf-8")
    (folder / "initech.csv").write_text("Order Date,Segment\n2026-01-31,x\n", encoding="utf-8")
    return {"dir": tmp_path, "template": template, "folder": folder, "out": tmp_path / "out"}


def run(batch, **kwargs):
    return apply_template_folder(batch["template"], str(batch["folder"]), output_dir=str(batch["out"]), **kwargs)


def by_input(table):
    return {r.input: r for r in table.itertuples()}


def test_each_file_gets_a_workbook_and_the_one_that_does_not_fit_is_skipped(batch):
    table = run(batch)
    assert list(table.columns) == SUMMARY_COLUMNS
    rows = by_input(table)
    assert sorted(rows) == ["acme.csv", "globex.csv", "initech.csv"]
    assert rows["acme.csv"].status == "ok" and rows["acme.csv"].output == "sales_acme.twbx"
    assert rows["acme.csv"].missing == 0 and rows["acme.csv"].broken_sheets == ""
    assert (batch["out"] / "sales_globex.twbx").exists()
    bad = rows["initech.csv"]
    assert bad.status == "error" and "no column for required field(s)" in bad.error and bad.output == ""
    assert bad.missing == 2 and bad.broken_sheets
    assert not (batch["out"] / "sales_initech.twbx").exists()


def test_the_summary_is_written_beside_the_outputs(batch):
    table = run(batch)
    written = pd.read_csv(batch["out"] / "summary.csv", keep_default_na=False)
    assert list(written["input"]) == list(table["input"]) and list(written["status"]) == list(table["status"])


def test_nothing_is_overwritten_unless_asked(batch):
    run(batch)
    with pytest.raises(FileExistsError, match="summary.csv"):
        run(batch)
    first = (batch["out"] / "sales_acme.twbx").read_bytes()
    (batch["out"] / "summary.csv").unlink()
    table = run(batch)
    assert by_input(table)["acme.csv"].status == "skipped"
    assert "refusing to overwrite existing file" in by_input(table)["acme.csv"].error
    assert (batch["out"] / "sales_acme.twbx").read_bytes() == first
    again = run(batch, overwrite=True)
    assert by_input(again)["acme.csv"].status == "ok"


def test_min_mapped_writes_the_files_that_are_close_enough_and_names_what_breaks(batch):
    (batch["folder"] / "partial.csv").write_text("Category,Order Date\nx,2026-01-31\n", encoding="utf-8")
    table = run(batch, min_mapped=0.5)
    rows = by_input(table)
    assert rows["partial.csv"].status == "ok" and rows["partial.csv"].missing == 1 and rows["partial.csv"].broken_sheets
    assert rows["initech.csv"].status == "skipped" and "of 2 required fields map" in rows["initech.csv"].error
    assert not (batch["out"] / "sales_initech.twbx").exists()
    with pytest.raises(ValueError, match="between 0 and 1"):
        run(batch, min_mapped=2, overwrite=True)


def test_on_error_stop_raises_at_the_first_bad_file_but_keeps_the_summary(batch):
    with pytest.raises(TemplateError, match="initech.csv: no column for required"):
        run(batch, on_error="stop")
    done = pd.read_csv(batch["out"] / "summary.csv", keep_default_na=False)
    assert list(done["input"]) == ["acme.csv", "globex.csv", "initech.csv"]
    with pytest.raises(ValueError, match="skip"):
        run(batch, on_error="nope", overwrite=True)


def test_a_file_that_is_not_data_is_reported_and_does_not_stop_the_others(batch):
    (batch["folder"] / "broken.xlsx").write_text("not a zip", encoding="utf-8")
    (batch["folder"] / "empty.csv").write_text("", encoding="utf-8")
    rows = by_input(run(batch))
    assert rows["broken.xlsx"].status == "error" and "not a readable Excel file" in rows["broken.xlsx"].error
    assert rows["empty.csv"].status == "error"
    assert rows["acme.csv"].status == "ok"


def test_the_same_stem_under_two_extensions_gets_a_number(batch):
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    book.active.title = "Data"
    book.active.append(HEADER.strip().split(","))
    book.active.append(["Furniture", 1, dt.datetime(2026, 1, 31), 10, "Consumer"])
    book.active.append(["Office", 2, dt.datetime(2026, 2, 1), 20, "Corporate"])
    book.save(str(batch["folder"] / "acme.xlsx"))
    rows = by_input(run(batch))
    assert {rows["acme.csv"].output, rows["acme.xlsx"].output} == {"sales_acme.twbx", "sales_acme_2.twbx"}
    assert rows["acme.xlsx"].status == "ok"


def test_a_sidecar_gives_each_file_its_own_parameters_and_sheet(batch):
    sidecar = batch["dir"] / "inputs.csv"
    sidecar.write_text("file,New Quota,Base Salary\nacme.csv,750000,\nglobex.csv,900000,55000\nghost.csv,1,2\n",
                       encoding="utf-8")
    table = run(batch, inputs=str(sidecar), params={"Base Salary": "50000"})
    rows = by_input(table)
    assert rows["acme.csv"].status == "ok" and rows["globex.csv"].status == "ok"
    acme, globex = (read_answers(str(batch["out"] / f"sales_{n}.twbx")) for n in ("acme", "globex"))
    assert acme["parameters"]["[New Quota]".strip("[]")] == "750000"
    assert globex["parameters"]["New Quota"] == "900000" and globex["parameters"]["Base Salary"] == "55000"
    assert acme["parameters"]["Base Salary"] == "50000"            # the empty cell leaves the batch value alone
    assert rows["ghost.csv"].status == "skipped" and "not in the folder" in rows["ghost.csv"].error


def test_the_sidecar_is_checked_before_anything_is_written(batch):
    template = load_template(batch["template"])
    bad = batch["dir"] / "bad.csv"
    bad.write_text("file,Nope\nacme.csv,1\n", encoding="utf-8")
    with pytest.raises(TemplateError, match="Nope are neither parameters nor tokens of the template"):
        run(batch, inputs=str(bad))
    assert not batch["out"].exists()
    bad.write_text("name,New Quota\nacme.csv,1\n", encoding="utf-8")
    with pytest.raises(TemplateError, match="needs a 'file' column"):
        read_inputs(bad, template)
    bad.write_text("file,New Quota\nacme.csv,1\nacme.csv,2\n", encoding="utf-8")
    with pytest.raises(TemplateError, match="acme.csv twice"):
        read_inputs(bad, template)
    bad.write_text("file,sheet,New Quota\nsub/acme.csv,Orders,1\n", encoding="utf-8")
    assert read_inputs(bad, template) == {"sub/acme.csv": {"sheet": "Orders", "params": {"New Quota": "1"}, "tokens": {}}}


def test_an_invalid_parameter_value_fails_only_that_file(batch):
    sidecar = batch["dir"] / "inputs.csv"
    sidecar.write_text("file,Sort by\nacme.csv,not allowed\n", encoding="utf-8")
    rows = by_input(run(batch, inputs=str(sidecar)))
    assert rows["acme.csv"].status == "error" and rows["acme.csv"].error
    assert rows["globex.csv"].status == "ok"


def test_saved_answers_are_the_prior_for_every_file(batch):
    first = apply_template_folder(batch["template"], str(batch["folder"]), output_dir=str(batch["out"]))
    answers = str(batch["out"] / "sales_acme.twbx")
    assert first.shape[0] == 3
    table = apply_template_folder(batch["template"], str(batch["folder"]), output_dir=str(batch["dir"] / "second"),
                                  answers=answers)
    rows = by_input(table)
    assert rows["globex.csv"].status == "ok"
    assert read_answers(str(batch["dir"] / "second" / "sales_globex.twbx"))["mapping"] == read_answers(answers)["mapping"]


def test_a_mapping_file_applies_to_every_file_and_a_file_without_its_columns_fails(batch):
    mapping = batch["dir"] / "map.csv"
    from py_tbparse import load_template as lt, suggest_mapping
    from py_tbparse.templates import read_data
    suggest_mapping(lt(batch["template"]), read_data(str(batch["folder"] / "acme.csv"))).to_csv(mapping, index=False)
    rows = by_input(run(batch, mapping=str(mapping)))
    assert rows["acme.csv"].status == "ok" and rows["globex.csv"].status == "ok"
    assert rows["initech.csv"].status == "error" and "does not have" in rows["initech.csv"].error


def _members(path):
    """A workbook's zip members by name. Workers that are spawned (Windows, macOS) do not inherit the test's
    patched clock, so the `created` stamp in the answers file is left out of the comparison."""
    with zipfile.ZipFile(path) as z:
        members = {n: z.read(n) for n in z.namelist()}
    for n, data in members.items():
        if n.endswith("template-answers.json"):
            members[n] = {k: v for k, v in json.loads(data).items() if k != "created"}
    return members


def test_workers_give_the_same_workbooks_as_one_process(batch):
    serial = run(batch)
    parallel = apply_template_folder(batch["template"], str(batch["folder"]), output_dir=str(batch["dir"] / "par"),
                                     workers=2)
    assert list(serial["status"]) == list(parallel["status"])
    for name in ("acme", "globex"):
        assert _members(batch["out"] / f"sales_{name}.twbx") == _members(batch["dir"] / "par" / f"sales_{name}.twbx")


def test_a_missing_folder_and_an_empty_one(batch, tmp_path):
    with pytest.raises(FileNotFoundError):
        apply_template_folder(batch["template"], str(tmp_path / "nope"))
    empty = tmp_path / "empty"
    empty.mkdir()
    table = apply_template_folder(batch["template"], str(empty), output_dir=str(tmp_path / "o"))
    assert table.empty and list(table.columns) == SUMMARY_COLUMNS


def test_cli_apply_folder(batch, capsys):
    code = main(["template", "apply-folder", batch["template"], str(batch["folder"]), "-o", str(batch["out"])])
    captured = capsys.readouterr()
    assert code == 1                                    # initech.csv was not written
    assert "2 written, 0 skipped, 1 failed" in captured.err and "acme.csv" in captured.out
    (batch["folder"] / "initech.csv").unlink()
    assert main(["template", "apply-folder", batch["template"], str(batch["folder"]), "-o", str(batch["out"]),
                 "--overwrite", "--format", "csv"]) == 0
    assert main(["template", "apply-folder", batch["template"], str(batch["folder"]), "-o", str(batch["out"])]) == 1
    assert "summary.csv" in capsys.readouterr().err
