"""validate_workbook: dangling references, and what template apply must keep intact."""

import shutil
import zipfile
from pathlib import Path

import pytest
from lxml import etree

from py_tbparse import TwbParser, apply_template, load_template, make_template
from py_tbparse.verify import VERIFY_COLUMNS, validate_workbook

PUBLIC = Path(__file__).parent / "fixtures" / "public"

BOOK = """<?xml version='1.0' encoding='utf-8'?>
<workbook version='18.1'>
  <datasources>
    <datasource name='federated.1' inline='true'>
      <connection class='federated'>
        <named-connections><named-connection name='textscan.1' caption='sales'>
          <connection class='textscan' directory='/d' filename='sales.csv'/>
        </named-connection></named-connections>
        <relation connection='textscan.1' name='sales.csv' table='[sales#csv]' type='table'>
          <columns header='yes'><column datatype='integer' name='Amount' ordinal='0'/></columns>
        </relation>
        <metadata-records>
          <metadata-record class='column'>
            <remote-name>Amount</remote-name><remote-type>{remote_type}</remote-type>
            <local-name>[Amount]</local-name><parent-name>[sales.csv]</parent-name>
            <local-type>{local_type}</local-type>
          </metadata-record>
        </metadata-records>
      </connection>
      <column name='[Amount]' datatype='integer' role='measure' type='quantitative'/>
      <column name='[Double]' datatype='integer' role='measure' type='quantitative'>
        <calculation class='tableau' formula='[{formula_ref}] * 2'/>
      </column>
    </datasource>
  </datasources>
  <worksheets>
    <worksheet name='Sheet 1'><table><view>
      <datasource-dependencies datasource='federated.1'>
        <column name='[{sheet_field}]' datatype='integer' role='measure' type='quantitative'/>
      </datasource-dependencies>
    </view></table></worksheet>
  </worksheets>
  <dashboards>
    <dashboard name='Board'><zones><zone name='{zone}' id='1'/></zones></dashboard>
  </dashboards>
  <windows>
    <window class='worksheet' name='{window}'/>
    <window class='dashboard' name='Board'/>
  </windows>
</workbook>
"""

CLEAN = dict(remote_type="20", local_type="integer", formula_ref="Amount", sheet_field="Amount",
             zone="Sheet 1", window="Sheet 1")


def book(tmp_path, **changes):
    path = tmp_path / "book.twb"
    path.write_text(BOOK.format(**{**CLEAN, **changes}), encoding="utf-8")
    return str(path)


def findings(frame):
    return set(zip(frame["check"], frame["severity"]))


def test_a_consistent_workbook_has_no_findings(tmp_path):
    frame = validate_workbook(book(tmp_path))
    assert list(frame.columns) == VERIFY_COLUMNS and frame.empty


@pytest.mark.parametrize("changes, expected", [
    ({"sheet_field": "Gone"}, ("sheet-field", "error")),
    ({"formula_ref": "Gone"}, ("calc-reference", "warning")),
    ({"zone": "Nowhere"}, ("dashboard-sheet", "error")),
    ({"window": "Nowhere"}, ("window-name", "error")),
    ({"local_type": "string", "remote_type": "129"}, ("local-type", "warning")),
    ({"remote_type": "99"}, ("remote-type", "error")),
])
def test_each_check_finds_its_own_problem(tmp_path, changes, expected):
    frame = validate_workbook(book(tmp_path, **changes))
    assert findings(frame) == {expected}


def test_a_remote_name_the_text_file_does_not_list_is_found(tmp_path):
    path = book(tmp_path)
    text = Path(path).read_text(encoding="utf-8").replace(
        "<remote-name>Amount</remote-name>", "<remote-name>Missing</remote-name>")
    Path(path).write_text(text, encoding="utf-8")
    frame = validate_workbook(path)
    assert findings(frame) == {("remote-name", "error")}
    assert "Missing" in frame.loc[0, "detail"]


def test_a_type_the_author_changed_is_not_a_finding(tmp_path):
    path = book(tmp_path, local_type="string", remote_type="129")
    text = Path(path).read_text(encoding="utf-8").replace(
        "<column name='[Amount]' datatype='integer'", "<column name='[Amount]' datatype='integer' datatype-customized='true'")
    Path(path).write_text(text, encoding="utf-8")
    assert "local-type" not in set(validate_workbook(path)["check"])


# --- template apply must leave the sheets something to point at ---------------


def _table_columns(doc):
    return doc.xpath("/workbook/datasources/datasource/*[@datatype='table']/@name")


def _csv(tmp_path):
    path = tmp_path / "q3.csv"
    path.write_text("burst_out_set_list,Amount,When\nA,1,2026-01-01\n", encoding="utf-8")
    return str(path)


def _apply(book_path, csv_path):
    return apply_template(load_template(make_template(str(book_path))), csv_path, allow_missing=True)


def _plain(text: str) -> str:
    """The same workbook the way newer builds write the object model: ordinary tags, one relation."""
    doc = etree.fromstring(text.encode("utf-8"))
    for el in list(doc.iter()):
        if isinstance(el.tag, str) and ".false..." in el.tag:
            el.getparent().remove(el)
    for el in doc.iter():
        if isinstance(el.tag, str) and ".true..." in el.tag and el.tag.startswith("_.fcp.ObjectModel"):
            el.tag = el.tag.split("...", 1)[1]
    return etree.tostring(doc, encoding="unicode")


@pytest.mark.parametrize("dialect", ["prefixed", "plain"])
def test_apply_keeps_the_table_column_the_sheets_use(tmp_path, dialect):
    src = tmp_path / "filtering.twb"
    text = (PUBLIC / "filtering.twb").read_text(encoding="utf-8")
    src.write_text(_plain(text) if dialect == "plain" else text, encoding="utf-8")
    before = TwbParser(str(src))
    out = _apply(src, _csv(tmp_path))
    after = TwbParser(out)
    assert _table_columns(before.xml_doc) and _table_columns(after.xml_doc) == _table_columns(before.xml_doc)
    raw = zipfile.ZipFile(out).read("filtering.twb").decode("utf-8")
    assert ("_.fcp.ObjectModelEncapsulateLegacy" in raw) == (dialect == "prefixed")
    assert not validate_workbook(after)["check"].eq("sheet-field").any()
    assert not validate_workbook(after).query("severity == 'error'")["check"].isin(["remote-name", "remote-type"]).any()


def test_applying_to_a_csv_writes_the_remote_types_tableau_writes(tmp_path):
    src = tmp_path / "filtering.twb"
    shutil.copy(PUBLIC / "filtering.twb", src)
    out = _apply(src, _csv(tmp_path))
    assert validate_workbook(out).query("check in ['remote-name', 'remote-type']").empty
    types = {r.findtext("local-type"): r.findtext("remote-type")
             for r in TwbParser(out).xml_doc.xpath("//metadata-record[@class='column']")}
    assert types and all(code in ("129", "20", "5", "11", "133", "135") for code in types.values())


def test_the_built_in_record_count_needs_a_formula_or_a_data_column(tmp_path):
    ns = "xmlns:user='http://www.tableausoftware.com/xml/user'"
    column = ("<column name='[Number of Records]' datatype='real' role='measure' type='quantitative' "
              "user:auto-column='numrec'{}")
    path = book(tmp_path)
    text = Path(path).read_text(encoding="utf-8").replace("<workbook ", f"<workbook {ns} ")
    bare = text.replace("<column name='[Double]'", column.format("/>") + "<column name='[Double]'", 1)
    Path(path).write_text(bare, encoding="utf-8")
    assert findings(validate_workbook(path)) == {("built-in-count", "error")}
    formula = column.format("><calculation class='tableau' formula='1'/></column>")
    Path(path).write_text(text.replace("<column name='[Double]'", formula + "<column name='[Double]'", 1),
                          encoding="utf-8")
    assert validate_workbook(path).empty


def test_apply_gives_the_record_count_its_formula_back(tmp_path):
    """filtering.twb has a data column named like the built-in; a template leaves that column out, so a
    sheet summing [Number of Records] would have nothing behind it (seen in Tableau: the sum errors)."""
    src = tmp_path / "filtering.twb"
    shutil.copy(PUBLIC / "filtering.twb", src)
    out = _apply(src, _csv(tmp_path))
    [col] = TwbParser(out).xml_doc.xpath("//datasource/column[@name='[Number of Records]']")
    assert [c.get("formula") for c in col.findall("calculation")] == ["1"]
    assert validate_workbook(out).query("check == 'built-in-count'").empty
