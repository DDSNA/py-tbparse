"""Workbooks py-tbparse writes, checked against Tableau's schema and for dangling references.

Both checks are differential: a workbook can already break a rule before we touch it (the schema
describes 2026.2, most real workbooks are older), so only what the output has and the input did not
counts. See tests/schema_check.py. Neither proves Tableau opens the file; docs/verify-in-tableau.md
is the manual step for that.
"""

import collections
import csv
import shutil
from pathlib import Path

import pytest
from lxml import etree

from py_tbparse import TwbParser, apply_template, load_template, make_template, suggest_mapping, suggest_renames
from py_tbparse.rename import build_renamed_workbook
from py_tbparse.templates import read_data
from py_tbparse.verify import validate_workbook
from schema_check import new_schema_errors, schema_errors, twb_bytes

PUBLIC = Path(__file__).parent / "fixtures" / "public"
CORPUS = Path(__file__).parent / "corpus" / "files"
FIXTURES = ["filtering.twb", "datasource_test.twb", "Cache.twbx", "TABLEAU_10_TWBX.twbx"]


def _finding_keys(frame):
    # the sheet an issue sits on is renamed by a rename; what it says is not
    return collections.Counter(zip(frame["check"], frame["datasource"], frame["detail"]))


def _csv_for(template, entry, folder):
    """A CSV that holds every column the template's datasource reads."""
    path = folder / "data.csv"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerow([f["remote"] for f in entry["fields"]])
    mapping = suggest_mapping(template, read_data(str(path)), datasource=entry["name"])
    return str(path), set(mapping[mapping["mapped_to"] == ""]["field"])


def written_workbooks(book, folder):
    """What py-tbparse writes from a workbook: a renamed copy and the template applied to a CSV.
    Yields (kind, workbook bytes, names of the fields the CSV could not feed)."""
    parser = TwbParser(str(book))
    yield "rename", build_renamed_workbook(parser, suggest_renames(parser), {}), set()
    template = load_template(make_template(str(book)))
    for i, entry in enumerate(template.manifest["datasources"]):
        if not entry["fields"]:
            continue
        data, unfed = _csv_for(template, entry, folder)
        out = apply_template(template, data, datasource=entry["name"], allow_missing=True,
                             output_path=str(folder / f"out{i}.twbx"))
        yield "apply", twb_bytes(out), unfed
        try:
            import openpyxl
        except ImportError:
            break
        sheet = openpyxl.Workbook()
        sheet.active.title = "Data"
        sheet.active.append([f["remote"] for f in entry["fields"]])
        sheet.save(str(folder / "data.xlsx"))
        out = apply_template(template, str(folder / "data.xlsx"), datasource=entry["name"], allow_missing=True,
                             output_path=str(folder / f"excel{i}.twbx"))
        yield "apply-excel", twb_bytes(out), unfed
        break


def introduced(book, folder, kind, data, unfed):
    """Schema errors and reference findings `data` has that `book` did not."""
    out = folder / f"{kind}.twb"
    out.write_bytes(twb_bytes(data))
    schema = new_schema_errors(str(book), data)
    refs = _finding_keys(validate_workbook(str(out))) - _finding_keys(validate_workbook(str(book)))
    # a field the CSV cannot feed is gone on purpose; apply reports the sheets it breaks
    refs = {k: v for k, v in refs.items() if not any(name in k[2] for name in unfed)}
    return schema, sorted(refs)


@pytest.mark.parametrize("name", FIXTURES)
def test_written_fixtures_add_no_schema_or_reference_errors(name, tmp_path):
    book = tmp_path / name
    shutil.copy(PUBLIC / name, book)
    seen = 0
    for kind, data, unfed in written_workbooks(book, tmp_path):
        schema, refs = introduced(book, tmp_path, kind, data, unfed)
        assert schema == [] and refs == [], (kind, schema, refs)
        seen += 1
    assert seen >= 1


def test_the_schema_check_can_fail(tmp_path):
    """Two worksheets that end up with one name (a bad rename), and an element that is not in the schema.
    The schema does not check that a window or dashboard names a sheet that exists: that is what
    verify.validate_workbook is for."""
    book = PUBLIC / "filtering.twb"
    doc = etree.fromstring(book.read_bytes())
    first, second = doc.xpath("/workbook/worksheets/worksheet")[:2]
    second.set("name", first.get("name"))
    assert any("Duplicate" in m for _, m in new_schema_errors(str(book), etree.tostring(doc)))

    doc = etree.fromstring(book.read_bytes())
    etree.SubElement(doc.xpath("/workbook/worksheets/worksheet")[0], "not-a-tableau-element")
    assert any("not-a-tableau-element" in m for _, m in new_schema_errors(str(book), etree.tostring(doc)))


def test_errors_the_input_already_had_are_not_counted():
    assert schema_errors(PUBLIC / "filtering.twb") == schema_errors((PUBLIC / "filtering.twb").read_bytes())
    assert new_schema_errors(PUBLIC / "filtering.twb", PUBLIC / "filtering.twb") == []


# --- the 200-workbook corpus (python scripts/fetch_corpus.py) ---------------------------------------

corpus = pytest.mark.skipif(not CORPUS.is_dir() or not any(CORPUS.glob("*.twb")),
                            reason="corpus not fetched: python scripts/fetch_corpus.py")


@corpus
def test_written_workbooks_add_no_schema_or_reference_errors_on_the_corpus(tmp_path):
    problems = []
    for n, book in enumerate(sorted(CORPUS.glob("*.twb"))):
        work = tmp_path / f"w{n}"
        work.mkdir()
        copy = work / "book.twb"
        shutil.copy(book, copy)
        for kind, data, unfed in written_workbooks(copy, work):
            schema, refs = introduced(copy, work, kind, data, unfed)
            if schema or refs:
                problems.append((book.name, kind, schema[:2], refs[:2]))
        shutil.rmtree(work)
    assert problems == []


def test_the_verification_pack_is_made_and_clean(tmp_path, capsys):
    import runpy

    pack = runpy.run_path(str(Path(__file__).parent.parent / "scripts" / "make_verification_pack.py"))
    out = tmp_path / "pack"
    assert pack["main"]([str(out)]) == 0
    assert sorted(p.name for p in out.iterdir()) == [
        "0-original.twb", "1-renamed.twb", "2-template-on-csv.twbx", "3-template-on-workbook.twbx",
        "4-template-on-excel.twbx", "5-template-on-db.twbx", "_work", "data"]
    assert sorted(p.suffix for p in (out / "data").iterdir()) == [".csv", ".json", ".xlsx"]
    text = capsys.readouterr().out
    assert text.count("no new errors") == 5 and text.count("no new findings") == 5
    assert pack["main"]([str(out)]) == 2                       # never writes into a folder with files
