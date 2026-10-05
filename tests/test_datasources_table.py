"""The Datasources table (issue #65): one sensible row per logical table, no row for the
internal Parameters datasource, no pure-blank rows."""

from pathlib import Path

from conftest import xml_from_string
from py_tbparse import TwbParser, extract_datasource_details

NOT_STORED = "not stored in the workbook"
DEMO = Path(__file__).parent.parent / "docs" / "demo" / "coffee-shop.twb"
COLUMNS = [
    "primary_table", "connection_caption", "connection_class", "connection_target",
    "datasource_name", "field_count", "connection_type", "location",
    "datasource", "connection_id",
]


def table(xml):
    return extract_datasource_details(xml)["data_sources"]


def test_demo_workbook_has_no_blank_rows():
    ds = TwbParser(str(DEMO)).get_datasources()
    assert list(ds.columns) == COLUMNS
    assert list(ds["primary_table"]) == [
        f"[{t}]" for t in ["Orders", "Customers", "Products", "Suppliers", "Returns", "Stores"]
    ]
    assert not ds.drop(columns=["connection_id"]).isna().any().any()
    # every table belongs to the one real datasource, 'coffee', not to Parameters
    assert set(ds["datasource_name"]) == {"coffee"}
    assert (ds["field_count"] == 27).all()
    # the workbook stores no connection: say so in words
    for col in ["connection_caption", "connection_class", "connection_target", "connection_type", "location"]:
        assert set(ds[col]) == {NOT_STORED}


def test_wenjie_rows_are_filled_and_agree(wenjie_xml):
    ds = table(wenjie_xml).set_index("primary_table")
    assert list(ds.index) == ["[Municipal_Boundaries_of_NJ]", "[Sheet1$]"]
    # both tables sit in the same Tableau datasource, so name and field count agree
    assert set(ds["datasource_name"]) == {"federated.0grgaor1pd01yy1f0yr380of1ags"}
    assert (ds["field_count"] == 110).all()
    shp, xls = ds.loc["[Municipal_Boundaries_of_NJ]"], ds.loc["[Sheet1$]"]
    assert shp["connection_class"] == "ogrdirect" and xls["connection_class"] == "excel-direct"
    assert shp["connection_type"] == "ogrdirect" and xls["connection_type"] == "excel-direct"
    # the target is where the data is, never an empty string
    assert shp["connection_target"] == "C:/Users/garthur/Downloads"
    assert xls["connection_target"] == "C:/Users/garthur/Downloads/test_county.xlsx"
    assert shp["location"] == "Shapefile: Municipal_Boundaries_of_NJ (1).zip"
    assert xls["location"] == "Excel: test_county.xlsx"
    assert not ds.drop(columns=["connection_id"]).isna().any().any()


PARAMS_AND_MODEL = """
<workbook>
  <datasources>
    <datasource name="Parameters" hasconnection="false" inline="true">
      <column caption="Top N" datatype="integer" name="[Parameter 1]" param-domain-type="range" role="measure">
        <calculation class="tableau" formula="10"/>
      </column>
    </datasource>
    <datasource name="federated.abc" caption="Sales">
      <connection class="federated">
        <named-connections>
          <named-connection name="postgres.1" caption="warehouse">
            <connection class="postgres" server="db.example.com" dbname="sales"/>
          </named-connection>
        </named-connections>
        <relation type="join">
          <relation connection="postgres.1" name="orders" table="[public].[orders]" type="table"/>
          <relation connection="postgres.1" name="people" table="[public].[people]" type="table"/>
        </relation>
      </connection>
      <column name="[a]" datatype="string" role="dimension"/>
      <column name="[b]" datatype="string" role="dimension"/>
      <column name="[c]" datatype="string" role="dimension"/>
      <object-graph>
        <objects>
          <object id="o1"><properties context=""><relation connection="postgres.1" name="orders" table="[public].[orders]" type="table"/></properties></object>
          <object id="o2"><properties context=""><relation connection="postgres.1" name="people" table="[public].[people]" type="table"/></properties></object>
        </objects>
      </object-graph>
    </datasource>
  </datasources>
</workbook>
"""


def test_parameters_datasource_never_gets_a_row():
    ds = table(xml_from_string(PARAMS_AND_MODEL))
    assert "Parameters" not in set(ds["datasource_name"])
    assert list(ds["primary_table"]) == ["[public].[orders]", "[public].[people]"]
    assert set(ds["datasource_name"]) == {"federated.abc"}
    assert (ds["field_count"] == 3).all()
    assert set(ds["connection_class"]) == {"postgres"}
    assert set(ds["connection_target"]) == {"db.example.com"}
    assert set(ds["connection_caption"]) == {"warehouse"}
    assert set(ds["location"]) == {"No Known File Postgres: db.example.com"}


def test_logical_table_without_a_table_name_does_not_pick_up_parameters():
    # A relation with no @table used to be merged on a missing key, and pandas joins a
    # missing key to the Parameters datasource's missing key: the row showed Parameters.
    xml = xml_from_string(PARAMS_AND_MODEL.replace(
        ' table="[public].[people]" type="table"/></properties>', ' type="table"/></properties>'))
    ds = table(xml)
    assert len(ds) == 2
    assert "Parameters" not in set(ds["datasource_name"])
    assert (ds["field_count"] == 3).all()
    assert ds["primary_table"].isna().sum() == 1


def test_parameters_only_workbook_has_no_datasource_rows():
    xml = xml_from_string("""
    <workbook><datasources>
      <datasource name="Parameters" hasconnection="false">
        <column name="[P]" datatype="integer" param-domain-type="range" role="measure"/>
      </datasource>
    </datasources></workbook>""")
    res = extract_datasource_details(xml)
    assert res["data_sources"].empty
    assert set(res["data_sources"].columns) == set(COLUMNS)
    assert len(res["parameters"]) == 1


def test_datasource_without_object_graph_gets_one_row():
    xml = xml_from_string("""
    <workbook><datasources>
      <datasource name="Parameters" hasconnection="false"/>
      <datasource name="federated.old" caption="Old">
        <connection class="federated">
          <named-connections>
            <named-connection name="textscan.1" caption="orders.csv">
              <connection class="textscan" directory="C:/data" filename="orders.csv"/>
            </named-connection>
          </named-connections>
          <relation connection="textscan.1" name="orders.csv" table="[orders#csv]" type="table"/>
        </connection>
        <column name="[x]" datatype="string" role="dimension"/>
      </datasource>
    </datasources></workbook>""")
    [row] = table(xml).to_dict("records")
    assert row["primary_table"] == "[orders#csv]"
    assert row["datasource_name"] == "federated.old"
    assert row["connection_class"] == "textscan" and row["connection_target"] == "C:/data"
    assert row["location"] == "CSV: orders.csv"
    assert row["field_count"] == 1


def test_workbook_without_datasources_is_empty_with_columns():
    ds = table(xml_from_string("<workbook/>"))
    assert ds.empty and set(ds.columns) == set(COLUMNS)
