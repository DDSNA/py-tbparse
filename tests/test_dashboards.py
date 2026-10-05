from py_tbparse import dashboard_sheets, list_dashboards
from py_tbparse.dashboards import _int_attr, _xpath_string_literal
from conftest import xml_from_string

_XML = """
<workbook>
  <dashboards>
    <dashboard name="Overview">
      <zones>
        <zone id="1" worksheet="Sheet1" x="0" y="0" w="600" h="400"/>
      </zones>
    </dashboard>
  </dashboards>
</workbook>
"""


def test_list_dashboards():
    xml_doc = xml_from_string(_XML)
    names = list_dashboards(xml_doc)
    assert names["name"].tolist() == ["Overview"]


def test_dashboard_sheets():
    xml_doc = xml_from_string(_XML)
    sheets = dashboard_sheets(xml_doc)
    assert len(sheets) == 1
    row = sheets.iloc[0]
    assert row["dashboard"] == "Overview"
    assert row["sheet"] == "Sheet1"
    assert row["zone_id"] == "1"
    assert row["x"] == 0
    assert row["y"] == 0
    assert row["w"] == 600
    assert row["h"] == 400


def test_dashboard_sheets_filtered_by_name():
    xml_doc = xml_from_string(_XML)
    sheets = dashboard_sheets(xml_doc, dashboard="Overview")
    assert len(sheets) == 1
    sheets_missing = dashboard_sheets(xml_doc, dashboard="Nope")
    assert sheets_missing.empty


def test_int_attr_truncates_fractional_coordinates():
    # R's as.integer(xml_attr(...)) parses via double and truncates, so a
    # fractional zone coordinate (Tableau emits these for some
    # floating-layout zones) must truncate rather than come back as None.
    xml_doc = xml_from_string('<zone w="682.666"/>')
    assert _int_attr(xml_doc, "w") == 682


def test_int_attr_none_for_missing_or_garbage():
    xml_doc = xml_from_string('<zone w="not-a-number"/>')
    assert _int_attr(xml_doc, "w") is None
    assert _int_attr(xml_doc, "missing") is None


def test_dashboard_sheets_filter_handles_apostrophe_in_name():
    # The old implementation stripped "'" out of the filter value instead
    # of escaping it, so a real dashboard named "Sales's Report" (which
    # the GUI's own dropdown offers verbatim, via get_dashboards()) could
    # never be matched by --dashboard/dashboard=.
    xml_doc = xml_from_string(
        """
        <workbook>
          <dashboards>
            <dashboard name="Sales's Report">
              <zones>
                <zone id="1" worksheet="Sheet1" x="0" y="0" w="600" h="400"/>
              </zones>
            </dashboard>
          </dashboards>
        </workbook>
        """
    )
    sheets = dashboard_sheets(xml_doc, dashboard="Sales's Report")
    assert len(sheets) == 1
    assert sheets.iloc[0]["dashboard"] == "Sales's Report"


def test_xpath_string_literal_plain():
    assert _xpath_string_literal("Overview") == "'Overview'"


def test_xpath_string_literal_single_quote():
    assert _xpath_string_literal("Sales's Report") == '"Sales\'s Report"'


def test_xpath_string_literal_double_quote():
    assert _xpath_string_literal('He said "hi"') == "'He said \"hi\"'"


def test_xpath_string_literal_both_quote_types_round_trips():
    # No single wrapper works when both ' and " are present -- must use
    # concat(). Verify against a real XPath evaluation, not just the
    # string shape, since the concat-splitting logic is easy to get
    # subtly wrong at the boundaries (leading/trailing/consecutive ').
    from lxml import etree

    for name in ["both ' and \" here", "'leading", "trailing'", "a''b", "''''"]:
        literal = _xpath_string_literal(name)
        doc = etree.fromstring(
            f'<w><d name="{name.replace(chr(34), "&quot;")}"/></w>'.encode()
        )
        assert doc.xpath(f".//d[@name={literal}]"), f"round-trip failed for {name!r}"


# Some files name a zone's sheet only in @name (no @worksheet); layout zones are not sheets.
_NAME_ONLY_XML = """
<workbook>
  <worksheets><worksheet name="Sheet 1"/><worksheet name="Sheet 2"/></worksheets>
  <dashboards>
    <dashboard name="setTest">
      <zones>
        <zone id="1" type-v2="layout-basic" name="Container" x="0" y="0" w="10" h="10">
          <zone id="3" name="Sheet 1" x="1" y="2" w="3" h="4"/>
          <zone id="5" name="Sheet 2" x="5" y="6" w="7" h="8"/>
          <zone id="6" type-v2="text" name="Note"/>
          <zone id="7" type-v2="filter" name="Sheet 2" param="[x]"/>
        </zone>
      </zones>
    </dashboard>
  </dashboards>
</workbook>
"""


def test_dashboard_sheets_reads_zones_named_only_by_name():
    sheets = dashboard_sheets(xml_from_string(_NAME_ONLY_XML))
    assert sheets["sheet"].tolist() == ["Sheet 1", "Sheet 2", "Sheet 2"]
    assert sheets["zone_id"].tolist() == ["3", "5", "7"]
    assert sheets.iloc[0][["x", "y", "w", "h"]].tolist() == [1, 2, 3, 4]


def test_dashboard_sheets_skips_layout_and_text_zones():
    sheets = dashboard_sheets(xml_from_string(_NAME_ONLY_XML))
    assert "Container" not in sheets["sheet"].tolist() and "Note" not in sheets["sheet"].tolist()


def test_the_report_usage_and_docgen_agree_on_a_dashboards_sheets(tmp_path):
    from py_tbparse import TwbParser
    from py_tbparse.dashboards import dashboard_targets
    from py_tbparse.report import workbook_report
    from py_tbparse.usage import _dashboards_of
    path = tmp_path / "wb.twb"
    path.write_text(_NAME_ONLY_XML)
    parser = TwbParser(str(path))
    db = parser.xml_doc.xpath("/workbook/dashboards/dashboard")[0]
    assert dashboard_targets(db) == ["Sheet 1", "Sheet 2", "Sheet 2"]
    assert workbook_report(parser)["dashboards"] == [{"name": "setTest", "sheets": ["Sheet 1", "Sheet 2"]}]
    assert _dashboards_of(parser.xml_doc) == {"Sheet 1": {"setTest"}, "Sheet 2": {"setTest"}}
    assert not [h for h in workbook_report(parser)["health"] if h["id"] == "sheets-off-dashboards"]


def test_the_shipped_name_only_fixture_has_its_sheets_on_the_dashboard():
    from pathlib import Path
    from py_tbparse import TwbParser
    from py_tbparse.report import workbook_report
    parser = TwbParser(str(Path(__file__).parent / "fixtures" / "public" / "filtering.twb"))
    assert workbook_report(parser)["dashboards"] == [{"name": "setTest", "sheets": ["Sheet 1", "Sheet 2"]}]
    assert parser.get_dashboard_sheets()["sheet"].tolist() == ["Sheet 1", "Sheet 2"]
