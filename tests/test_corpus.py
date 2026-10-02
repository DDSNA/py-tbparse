"""Every feature over a corpus of 200 real workbooks (tests/corpus).

The files are not in git; fetch them with `python scripts/fetch_corpus.py`. Without
them these tests skip, so the normal suite is unaffected.
"""

import csv
import hashlib
import shutil
from pathlib import Path

import pytest

from py_tbparse import (
    TwbParser,
    apply_template,
    field_usage,
    load_template,
    make_template,
    suggest_mapping,
    suggest_renames,
)
from py_tbparse._tables import TABLE_SPECS
from py_tbparse.rename import build_renamed_workbook
from py_tbparse.templates import read_data

CORPUS = Path(__file__).parent / "corpus"
FILES = sorted((CORPUS / "files").glob("*.twb")) if (CORPUS / "files").is_dir() else []

pytestmark = pytest.mark.skipif(not FILES, reason="corpus not fetched: python scripts/fetch_corpus.py")


def test_corpus_is_the_one_in_the_manifest():
    rows = list(csv.DictReader(open(CORPUS / "manifest.csv", encoding="utf-8")))
    present = {p.name: p for p in FILES}
    assert set(present) <= {r["file"] for r in rows}
    for r in rows:
        if r["file"] in present:
            assert hashlib.sha256(present[r["file"]].read_bytes()).hexdigest() == r["sha256"], r["file"]


def test_every_table_extracts_from_every_workbook():
    for path in FILES:
        parser = TwbParser(str(path))
        for name, spec in TABLE_SPECS.items():
            spec(parser)  # must not raise


def test_rename_everything_keeps_every_report_consistent(tmp_path):
    for path in FILES:
        parser = TwbParser(str(path))
        report = {}
        data = build_renamed_workbook(parser, suggest_renames(parser), report)
        assert report["skipped"] == 0, path.name
        out = tmp_path / "r.twb"
        out.write_bytes(data)
        again = TwbParser(str(out))
        sheets = set(again.xml_doc.xpath("/workbook/worksheets/worksheet/@name"))
        assert len(sheets) == len(set(parser.xml_doc.xpath("/workbook/worksheets/worksheet/@name"))), path.name
        known = sheets | set(again.xml_doc.xpath("/workbook/dashboards/dashboard/@name"))
        assert set(again.get_dashboard_sheets()["sheet"]) <= known, path.name


def test_template_round_trip_on_every_workbook(tmp_path):
    for n, path in enumerate(FILES):
        work = tmp_path / f"w{n}"
        work.mkdir()
        book = work / "book.twb"
        shutil.copy(path, book)
        field_usage(TwbParser(str(book)))
        template = load_template(make_template(str(book)))
        for i, entry in enumerate(template.manifest["datasources"]):
            if not entry["fields"]:
                continue
            csv_path = work / f"d{i}.csv"
            with open(csv_path, "w", newline="", encoding="utf-8") as fh:
                csv.writer(fh).writerow([f["remote"] for f in entry["fields"]])
            mapping = suggest_mapping(template, read_data(str(csv_path)), datasource=entry["name"])
            # a field always finds its own column again, unless a joined source
            # has the same column name in two tables and one CSV can only feed one
            lost = mapping[mapping["required"] & (mapping["mapped_to"] == "")]
            assert all("already used by" in s for s in lost["status"]), (path.name, list(lost["field"]))
            apply_template(template, str(csv_path), datasource=entry["name"], allow_missing=True,
                           output_path=str(work / f"o{i}.twbx"))


def test_answers_explain_and_checks_on_every_workbook(tmp_path, monkeypatch):
    """Version 2 on real workbooks: ids are unique, nothing raises, and the answers a workbook keeps make
    that same workbook again, byte for byte."""
    import py_tbparse.templates as templates
    from py_tbparse import broken_sheets, check_data, explain

    monkeypatch.setattr(templates, "_now", lambda: "2026-10-02T00:00:00+00:00")
    for n, path in enumerate(FILES):
        work = tmp_path / f"w{n}"
        work.mkdir()
        book = work / "book.twb"
        shutil.copy(path, book)
        template = load_template(make_template(str(book)))
        assert template.id and template.manifest["version"] == 2, path.name
        for entry in template.manifest["datasources"]:
            uids = [f["uid"] for f in entry["fields"]]
            assert len(uids) == len(set(uids)), path.name
        entry = next((e for e in template.manifest["datasources"] if e["fields"]), None)
        if entry is None:
            continue
        csv_path = work / "d.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerow([f["remote"] for f in entry["fields"]])
        data = read_data(str(csv_path))
        mapping = suggest_mapping(template, data, datasource=entry["name"])
        for frame in (broken_sheets(template, mapping, datasource=entry["name"]),
                      explain(template, data, mapping, datasource=entry["name"]),
                      check_data(template, data, mapping, datasource=entry["name"])):
            assert frame is not None, path.name
        first = apply_template(template, str(csv_path), datasource=entry["name"], allow_missing=True,
                               output_path=str(work / "first.twbx"))
        again = apply_template(template, answers=first, allow_missing=True, output_path=str(work / "again.twbx"))
        assert Path(first).read_bytes() == Path(again).read_bytes(), path.name


def test_a_second_revision_identical_to_the_first_reports_no_change_on_every_workbook(tmp_path):
    """Revision 2 made from the same workbook: no change in the diff, none in the report against answers a
    workbook of revision 1 kept, and the update of such a workbook is a clean re-apply."""
    from py_tbparse import diff_template_revisions, template_update_report, update_from_answers

    for n, path in enumerate(FILES):
        work = tmp_path / f"w{n}"
        work.mkdir()
        book = work / "book.twb"
        shutil.copy(path, book)
        v1 = make_template(str(book), output_path=str(work / "v1.twbx"))
        v2 = make_template(str(book), output_path=str(work / "v2.twbx"), revision_of=v1)
        assert load_template(v2).id == load_template(v1).id and load_template(v2).revision == 2, path.name
        diff = diff_template_revisions(v1, v2)
        assert diff.empty, (path.name, diff.to_dict("records"))
        entry = next((e for e in load_template(v1).manifest["datasources"] if e["fields"]), None)
        if entry is None:
            continue
        csv_path = work / "d.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerow([f["remote"] for f in entry["fields"]])
        first = apply_template(v1, str(csv_path), datasource=entry["name"], allow_missing=True,
                               output_path=str(work / "first.twbx"))
        report = template_update_report(v2, first)
        assert report.empty, (path.name, report.to_dict("records"))
        out = update_from_answers(v2, first, allow_missing=True, output_path=str(work / "second.twbx"))
        assert out and Path(out).exists(), path.name
