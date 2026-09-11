from twbparser_py import dashboard_sheets, list_dashboards
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
