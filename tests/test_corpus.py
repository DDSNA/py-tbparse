"""Every feature over a corpus of 200 real workbooks (tests/corpus).

The files are not in git; fetch them with `python scripts/fetch_corpus.py`. Without
them these tests skip, so the normal suite is unaffected.
"""

import csv
import hashlib
import shutil
import sys
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

sys.path.insert(0, str(Path(__file__).parent))

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


def test_every_table_extracts_from_every_workbook(strict_extractors):
    for path in FILES:
        parser = TwbParser(str(path))
        for name, spec in TABLE_SPECS.items():
            spec(parser)  # must not raise: strict_extractors makes an extractor's exception reach the test


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


def test_apply_folder_writes_every_file_on_every_workbook(tmp_path):
    """Two data files per template, `min_mapped=0` so a field a CSV cannot feed does not skip the file."""
    from py_tbparse import apply_template_folder

    for n, path in enumerate(FILES):
        work = tmp_path / f"w{n}"
        work.mkdir()
        book = work / "book.twb"
        shutil.copy(path, book)
        template = make_template(str(book), output_path=str(work / "book.template.twbx"))
        entry = next((e for e in load_template(template).manifest["datasources"] if e["fields"]), None)
        if entry is None:
            continue
        folder = work / "data"
        folder.mkdir()
        for name in ("a", "b"):
            with open(folder / f"{name}.csv", "w", newline="", encoding="utf-8") as fh:
                csv.writer(fh).writerow([f["remote"] for f in entry["fields"]])
        table = apply_template_folder(template, str(folder), output_dir=str(work / "out"), min_mapped=0.0,
                                      datasource=entry["name"])
        assert list(table["status"]) == ["ok", "ok"], (path.name, table.to_dict("records"))
        assert sorted(p.name for p in (work / "out").iterdir()) == ["book_a.twbx", "book_b.twbx", "summary.csv"]


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


def test_template_check_and_markdown_on_every_workbook(tmp_path):
    """Every rule runs without crashing, the frame is deterministic, the Markdown page is well formed
    and never carries a credential, over templates made from all 200 workbooks."""
    import re

    from py_tbparse.docgen import template_markdown
    from py_tbparse.findings import FINDING_COLUMNS
    from py_tbparse.template_check import check_template, template_rule_ids

    seen = set()
    for n, path in enumerate(FILES):
        work = tmp_path / f"w{n}"
        work.mkdir()
        book = work / "book.twb"
        shutil.copy(path, book)
        template = load_template(make_template(str(book)))
        found = check_template(template)
        assert list(found.columns) == FINDING_COLUMNS
        assert not found["detail"].str.startswith("rule failed").any(), (path.name, found[found["detail"].str.startswith("rule failed")].to_dict("records"))
        assert set(found["rule"]) <= set(template_rule_ids())
        assert found.equals(check_template(template)), path.name
        seen |= set(found["rule"])
        page = template_markdown(template)
        assert page == template_markdown(template)
        block = []
        for line in page.splitlines() + [""]:
            if line.startswith("|"):
                block.append(len(re.split(r"(?<!\\)\|", line.strip())) - 2)
            elif block:
                assert len(set(block)) == 1, (path.name, block)
                block = []
        for secret in ("password=", "username="):
            assert secret not in page, path.name
    assert {"T001", "T010"} <= seen        # the rules that must fire on real workbooks did


def test_library_self_import():
    """Export every datasource's calculations and parameters, import them into the same workbook: nothing
    may be added or fail. Export must never raise."""
    from py_tbparse import export_library, plan_import, build_imported_workbook
    checked = 0
    for path in FILES:
        parser = TwbParser(str(path))
        for ds in parser.xml_doc.xpath("/workbook/datasources/datasource[@name!='Parameters']"):
            rep = {}
            try:
                lib = export_library(parser, datasource=ds.get("name"), report=rep)
            except Exception as e:   # noqa: BLE001 - the point is that nothing may raise
                pytest.fail(f"{path.name} / {ds.get('name')}: export raised {e!r}")
            # calculations that refer to another datasource are not exported: counted, and named here
            assert rep["unsupported_names"] == KNOWN_UNSUPPORTED.get((path.name, ds.get("name")), []), \
                f"{path.name} / {ds.get('name')}: {rep['unsupported_names']} not exported (a new known issue?)"
            if not lib["entries"]:
                continue
            checked += 1
            plan = plan_import(parser, lib, datasource=ds.get("name"))
            rows = plan[plan["uid"] != ""]
            assert set(rows["action"]) == {"skip-identical"}, f"{path.name} / {ds.get('name')}: {rows[rows['action'] != 'skip-identical'][['name', 'action', 'reason']].to_dict('records')}"
            report = {}
            build_imported_workbook(parser, lib, datasource=ds.get("name"), report=report)
            assert report["failed"] == 0 and report["added"] == 0
    assert checked > 100


# Calculations that refer to another datasource (`[other].[Field]`) are not exported: the first slice of
# libraries does not handle them (docs/wp6-library-design.md, section 2). Known issues, by (workbook,
# datasource): the corpus has two such calculations (the design doc counted three, including a worksheet copy).
KNOWN_UNSUPPORTED = {
    ("PacktPublishing__Advanced-Analytics-with-R-and-Tableau__Chapter_4.twb", "csv.41596.059997384262"):
        ["Calculation_3521122022654976", "Calculation_7061121072343255"],
}


# Workbooks whose palette handling is a known issue. Empty: none were found.
KNOWN_STYLE_ISSUES: dict[str, str] = {}


def test_style_palettes_on_every_workbook(tmp_path):
    """read_palettes never raises; a self-import changes nothing; the workbooks with a named palette export to
    a .tps that checks clean and re-reads the same; importing those palettes into every workbook adds no
    schema error that the workbook did not already have."""
    from lxml import etree
    from py_tbparse import build_with_palettes, check_style_file, export_palettes, plan_palette_import, read_palettes
    from schema_check import new_schema_errors

    with_palettes = {}
    for path in FILES:
        if path.name in KNOWN_STYLE_ISSUES:
            continue
        parser = TwbParser(str(path))
        try:
            rep = {}
            palettes = read_palettes(parser, rep)
        except Exception as e:   # noqa: BLE001 - the point is that nothing may raise
            pytest.fail(f"{path.name}: read_palettes raised {e!r}")
        assert rep["invalid"] == [], f"{path.name}: invalid palettes {rep['invalid']}"
        plan = plan_palette_import(parser, parser)
        assert set(plan["action"]) <= {"skip-identical"}, path.name
        assert len(plan) == len(palettes)
        assert etree.tostring(etree.fromstring(build_with_palettes(parser, parser))) == \
            etree.tostring(parser.xml_doc.getroot()), path.name
        if palettes:
            with_palettes[path.name] = palettes
    assert len(with_palettes) == 3, sorted(with_palettes)         # the census: 3 of 200
    merged = []
    for name, palettes in with_palettes.items():
        out = export_palettes([str(CORPUS / "files" / name)], tmp_path / f"{name}.tps")
        assert check_style_file(out) == [], name
        assert read_palettes(out) == palettes, name
        merged += palettes
    for path in FILES:
        if path.name in KNOWN_STYLE_ISSUES:
            continue
        data = build_with_palettes(str(path), merged, on_clash="skip")
        assert new_schema_errors(str(path), data) == [] or path.name in KNOWN_STYLE_ISSUES, path.name
