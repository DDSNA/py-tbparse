"""The workbook report card and the missing-references check behind it."""

from __future__ import annotations

import glob
import json
import time
from pathlib import Path

import pytest

from py_tbparse import TwbParser
from py_tbparse._tables import TABLE_SPECS
from py_tbparse.report import workbook_report
from py_tbparse.usage import _code_refs, missing_references

WORKBOOK = """<?xml version='1.0' encoding='utf-8' ?>
<workbook version='18.1'>
  <datasources>
    <datasource name='Parameters' hasconnection='false'>
      <column name='[Parameter 1]' datatype='integer' param-domain-type='range' role='measure'>
        <calculation class='tableau' formula='5' />
      </column>
    </datasource>
    <datasource name='ds1' caption='Sales'>
      <column name='[Sales]' datatype='real' role='measure' />
      <column name='[Profit]' datatype='real' role='measure' />
      <column name='[Unused Col]' datatype='string' role='dimension' />
      <column name="[Quote's Total]" datatype='real' role='measure'>
        <calculation class='tableau' formula='[Sales] * 2' />
      </column>
      <column name='[Ratio]' datatype='real' role='measure'>
        <calculation class='tableau' formula='[Profit] / [Sales]' />
      </column>
      <column name='[Idle]' datatype='real' role='measure'>
        <calculation class='tableau' formula='[Sales] * 3' />
      </column>
      <column name='[Broken]' datatype='real' role='measure'>
        <calculation class='tableau' formula='[Nope] + [Parameters].[Parameter 1] + [Parameters].[Ghost]' />
      </column>
      <column name='[Script]' datatype='real' role='measure'>
        <calculation class='tableau' formula='SCRIPT_REAL("x[&apos;cost&apos;] + [inside a string]", SUM([Sales]))' />
      </column>
      <column name='[Uses Quote]' datatype='real' role='measure'>
        <calculation class='tableau' formula="[Quote's Total] + [:Measure Names]" />
      </column>
    </datasource>
  </datasources>
  <worksheets>
    <worksheet name='Sheet 1'>
      <table><view>
        <datasource-dependencies datasource='ds1'>
          <column name='[Sales]' datatype='real' role='measure' />
          <column name='[Ratio]' datatype='real' role='measure' />
        </datasource-dependencies>
      </view></table>
    </worksheet>
    <worksheet name='Loose'><table><view /></table></worksheet>
  </worksheets>
  <dashboards>
    <dashboard name='Overview'>
      <zones><zone worksheet='Sheet 1' id='1' x='0' y='0' w='10' h='10' /></zones>
    </dashboard>
  </dashboards>
</workbook>
"""


@pytest.fixture
def book(tmp_path):
    path = tmp_path / "wb.twb"
    path.write_text(WORKBOOK, encoding="utf-8")
    return TwbParser(str(path))


def _filtered_rows(parser, item):
    """The rows a health item's link opens: the table, then each column filter as a lowercase 'contains'."""
    df = TABLE_SPECS[item["table"]](parser)
    for f in item["filters"]:
        df = df[df[f["col"]].astype(str).str.lower().str.contains(f["text"].lower(), regex=False)]
    return df


# --- missing references -----------------------------------------------------------------------------------

def test_code_refs_skip_strings_but_not_quotes_inside_brackets():
    assert _code_refs("[A] + [B C]") == ["[A]", "[B C]"]
    assert _code_refs('SCRIPT_REAL("x[\'y\'] [z]", [A])') == ["[A]"]
    assert _code_refs("IF [A] = 'it''s [x]' THEN [B] END") == ["[A]", "[B]"]
    assert _code_refs("[Quote's Total] * 2") == ["[Quote's Total]"]
    assert _code_refs("[a]]b] + 1") == ["[a]]b]"]
    assert _code_refs("") == [] and _code_refs(None) == []
    assert _code_refs('"unterminated [x]') == []


def test_missing_references_reports_only_what_is_really_missing(book):
    df = missing_references(book)
    assert sorted(df["missing"]) == ["Parameters.[Ghost]", "[Nope]"]
    assert set(df["calculation"]) == {"[Broken]"}
    assert list(df.columns) == ["datasource", "calculation", "caption", "missing"]


def test_missing_references_is_empty_and_correctly_shaped_for_a_clean_workbook(wenjie_path):
    df = missing_references(TwbParser(wenjie_path))
    assert list(df.columns) == ["datasource", "calculation", "caption", "missing"]


def test_the_missing_references_table_is_registered_everywhere(book):
    assert "missing-references" in TABLE_SPECS
    assert len(TABLE_SPECS["missing-references"](book)) == 2


# --- the report -------------------------------------------------------------------------------------------

def test_the_summary_is_one_plain_sentence(book):
    rep = workbook_report(book)
    assert rep["summary"].startswith("wb.twb has 1 dashboard, 2 worksheets and ")
    assert rep["worksheets"] == ["Loose", "Sheet 1"]
    assert rep["dashboards"] == [{"name": "Overview", "sheets": ["Sheet 1"]}]


def test_health_items_are_found_ranked_and_explained(book):
    rep = workbook_report(book)
    by_id = {h["id"]: h for h in rep["health"]}
    assert by_id["missing-references"]["count"] == 2
    assert by_id["missing-references"]["severity"] == "warning"
    assert by_id["unused-calculations"]["count"] == 5          # Quote's Total, Idle, Broken, Script, Uses Quote
    assert by_id["unused-fields"]["count"] == 1                # Unused Col; Profit is used through Ratio
    assert by_id["sheets-off-dashboards"]["count"] == 1 and by_id["sheets-off-dashboards"]["table"] == ""
    severities = [h["severity"] for h in rep["health"]]
    assert severities == sorted(severities, key=["problem", "warning", "info"].index), "problems first"
    for h in rep["health"]:
        assert h["title"] and h["severity"] in ("problem", "warning", "info")


def test_every_count_equals_the_rows_its_link_opens(book):
    for h in workbook_report(book)["health"]:
        if h["table"] and h["id"] not in ("inferred",):
            assert len(_filtered_rows(book, h)) == h["count"], h["id"]


def test_a_clean_workbook_has_no_problems(wenjie_path):
    rep = workbook_report(TwbParser(wenjie_path))
    assert not [h for h in rep["health"] if h["severity"] != "info"]
    assert json.dumps(rep)                                       # JSON-safe: no numpy ints or NaN left in


def test_the_report_is_json_safe_with_every_check_firing(book):
    text = json.dumps(workbook_report(book))
    assert "NaN" not in text


def test_relationship_problems_are_reported_as_problems(tmp_path):
    xml = WORKBOOK.replace("</datasources>", """</datasources>
  <object-graph><objects><object id='o1' caption='Orders'><properties context=''><relation name='Orders' table='[Orders]' type='table'/></properties></object></objects>
  <relationships><relationship><expression op='='><expression op='[Sales]'/><expression op='[Gone]'/></expression>
  <first-end-point object-id='o1'/><second-end-point object-id='o2'/></relationship></relationships></object-graph>""")
    path = tmp_path / "rel.twb"
    path.write_text(xml, encoding="utf-8")
    rep = workbook_report(TwbParser(str(path)))
    assert all(h["severity"] in ("problem", "warning", "info") for h in rep["health"])


def test_the_report_builds_for_a_workbook_with_nothing_in_it(tmp_path):
    path = tmp_path / "empty.twb"
    path.write_text("<?xml version='1.0'?><workbook version='18.1'/>", encoding="utf-8")
    rep = workbook_report(TwbParser(str(path)))
    assert rep["summary"].startswith("empty.twb has 0 dashboards, 0 worksheets and 0 datasources")
    assert rep["health"] == []


def test_parser_exposes_the_report(book):
    assert book.get_report()["summary"] == workbook_report(book)["summary"]
    assert len(book.get_missing_references()) == 2


# --- the real workbooks -----------------------------------------------------------------------------------

CORPUS = sorted(glob.glob(str(Path(__file__).parent / "corpus" / "files" / "*.tw*")))


@pytest.mark.skipif(not CORPUS, reason="corpus not fetched (python scripts/fetch_corpus.py)")
def test_the_report_builds_for_every_corpus_workbook_and_its_links_are_honest():
    started = time.time()
    slowest = (0.0, "")
    for path in CORPUS:
        try:
            parser = TwbParser(path)
        except Exception:
            continue                                             # the corpus test already owns unreadable files
        t0 = time.time()
        rep = workbook_report(parser)
        took = time.time() - t0
        slowest = max(slowest, (took, Path(path).name))
        json.dumps(rep)
        for h in rep["health"]:
            assert h["count"] > 0, (path, h)
            if h["table"] and h["filters"]:
                assert len(_filtered_rows(parser, h)) == h["count"], (path, h["id"])
    assert slowest[0] < 5.0, f"slowest report {slowest[0]:.1f} s ({slowest[1]})"
    assert time.time() - started < 180


def test_a_connectionless_source_is_mentioned_only_when_it_is_not_just_parameters(tmp_path, book):
    # the Parameters source never has a connection, so it alone is not worth a line
    assert "published" not in {h["id"] for h in workbook_report(book)["health"]}
    xml = WORKBOOK.replace("<datasource name='ds1' caption='Sales'>", "<datasource name='ds1' caption='Sales' hasconnection='false'>")
    path = tmp_path / "pub.twb"
    path.write_text(xml, encoding="utf-8")
    parser = TwbParser(str(path))
    item = {h["id"]: h for h in workbook_report(parser)["health"]}["published"]
    assert item["count"] == 2, "Parameters is counted too, so the count equals the rows the link opens"
    assert len(_filtered_rows(parser, item)) == item["count"]
    assert "Parameters" in item["detail"]
