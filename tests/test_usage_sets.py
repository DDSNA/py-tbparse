"""A set or group refers to its field by a derived name (`[none:Region:nk]`); usage must still tie them together."""

import pytest

from py_tbparse import TwbParser, field_usage, load_template, make_template, suggest_mapping
from py_tbparse.templates import broken_sheets, explain, read_data
from py_tbparse.usage import _base_field

BOOK = """<?xml version='1.0' encoding='utf-8'?>
<workbook xmlns:user='http://www.tableausoftware.com/xml/user' version='18.1'>
  <datasources>
    <datasource name='federated.1' inline='true'>
      <connection class='federated'>
        <named-connections><named-connection name='textscan.1' caption='sales'>
          <connection class='textscan' directory='/d' filename='sales.csv'/>
        </named-connection></named-connections>
        <relation connection='textscan.1' name='sales.csv' table='[sales#csv]' type='table'>
          <columns header='yes'><column datatype='string' name='Region' ordinal='0'/>
                                <column datatype='date' name='Ordered' ordinal='1'/></columns>
        </relation>
        <metadata-records>
          <metadata-record class='column'><remote-name>Region</remote-name><remote-type>129</remote-type>
            <local-name>[Region]</local-name><parent-name>[sales.csv]</parent-name><local-type>string</local-type></metadata-record>
          <metadata-record class='column'><remote-name>Ordered</remote-name><remote-type>133</remote-type>
            <local-name>[Ordered]</local-name><parent-name>[sales.csv]</parent-name><local-type>date</local-type></metadata-record>
        </metadata-records>
      </connection>
      <column name='[Region]' datatype='string' role='dimension' type='nominal'/>
      <column name='[Ordered]' datatype='date' role='dimension' type='ordinal'/>
      <group caption='East only' name='[EastSet]' name-style='unqualified' user:ui-builder='filter-group'>
        <groupfilter function='member' level='[none:Region:nk]' member='&quot;East&quot;'/>
      </group>
      <group caption='Q1 only' name='[Q1Set]' name-style='unqualified' user:ui-builder='filter-group'>
        <groupfilter function='member' level='[tmn:Ordered:ok]' member='1'/>
      </group>
    </datasource>
  </datasources>
  <worksheets>
    <worksheet name='Only Set'><table><view>
      <datasource-dependencies datasource='federated.1'>
        <column name='[EastSet]' datatype='boolean' role='dimension' type='nominal'/>
        <column-instance column='[EastSet]' derivation='InOut' name='[io:EastSet:nk]' pivot='key' type='nominal'/>
      </datasource-dependencies>
    </view></table></worksheet>
  </worksheets>
</workbook>
"""


@pytest.fixture
def book(tmp_path):
    path = tmp_path / "sets.twb"
    path.write_text(BOOK, encoding="utf-8")
    return path


@pytest.mark.parametrize("ref, base", [
    ("[none:Region:nk]", "[Region]"), ("[tmn:Ordered:ok]", "[Ordered]"), ("[yr:Order Date:ok]", "[Order Date]"),
    ("[io:Set:nk]", "[Set]"), ("[Region]", "[Region]"), ("[Sales: Net]", "[Sales: Net]"),
])
def test_a_derived_name_is_traced_back_to_its_field(ref, base):
    assert _base_field(ref) == base


def test_a_sheet_that_uses_only_a_set_uses_the_field_under_it(book):
    usage = field_usage(TwbParser(str(book))).set_index("field")
    assert usage.loc["[Region]", "used"] and usage.loc["[Region]", "sheets"] == ["Only Set"]
    assert usage.loc["[Region]", "calculations"] == ["East only"]
    assert not usage.loc["[Ordered]", "used"] and usage.loc["[Ordered]", "calculations"] == ["Q1 only"]


def test_the_field_under_a_set_is_required_and_named_when_missing(book, tmp_path):
    t = load_template(make_template(str(book)))
    required = {f["name"]: f["required"] for f in t.manifest["datasources"][0]["fields"]}
    assert required == {"[Region]": True, "[Ordered]": False}
    csv = tmp_path / "d.csv"
    csv.write_text("Ordered\n2026-01-01\n", encoding="utf-8")
    d = read_data(str(csv))
    mapping = suggest_mapping(t, d)
    [row] = broken_sheets(t, mapping).to_dict("records")
    assert row["field"] == "[Region]" and row["calculations"] == "East only"
    changes = explain(t, d, mapping)
    [hit] = changes[changes["kind"] == "set or group"].to_dict("records")
    assert hit["object"] == "East only" and hit["detail"] == "is built on Region"
