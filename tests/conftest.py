from pathlib import Path

import pytest
from lxml import etree

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def wenjie_xml():
    return etree.parse(str(FIXTURES / "test_for_wenjie.twb"))


@pytest.fixture
def wenjie_path():
    return str(FIXTURES / "test_for_wenjie.twb")


@pytest.fixture
def zip_twbx_path():
    return str(FIXTURES / "test_for_zip.twbx")


def xml_from_string(s: str):
    return etree.fromstring(s.encode("utf-8"))


# Real Tableau workbooks give every column in the "Parameters" datasource a
# @param-domain-type attribute plus a <calculation> holding its value.
REAL_PARAMS_XML = """
<workbook>
  <datasources>
    <datasource name="Parameters" hasconnection="false" inline="true">
      <aliases enabled="yes"/>
      <column caption="Top N" datatype="integer" name="[Parameter 1]"
              param-domain-type="range" role="measure" type="quantitative" value="10">
        <calculation class="tableau" formula="10"/>
        <range granularity="1" max="50" min="1"/>
      </column>
      <column caption="Region Pick" datatype="string" name="[Parameter 2]"
              param-domain-type="list" role="measure" type="nominal" value="&quot;East&quot;">
        <calculation class="tableau" formula="&quot;East&quot;"/>
        <members>
          <member value="&quot;East&quot;"/>
          <member value="&quot;West&quot;"/>
        </members>
      </column>
    </datasource>
    <datasource name="Orders">
      <column name="[Amount]" caption="Amount" datatype="real" role="measure">
        <calculation class="tableau" formula="SUM([Sales])"/>
      </column>
    </datasource>
  </datasources>
</workbook>
"""
