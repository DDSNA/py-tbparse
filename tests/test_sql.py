from twbparser_py import extract_custom_sql, extract_initial_sql
from conftest import xml_from_string


def test_extract_custom_sql_flags_select():
    xml_doc = xml_from_string(
        """
        <workbook>
          <relation name="Custom SQL Query" type="text" formula="SELECT * FROM orders"/>
          <relation name="Plain Table" type="table" table="[Orders]"/>
        </workbook>
        """
    )
    df = extract_custom_sql(xml_doc)
    assert len(df) == 1
    row = df.iloc[0]
    assert row["relation_name"] == "Custom SQL Query"
    assert bool(row["is_custom_sql"]) is True


def test_extract_custom_sql_flags_with_cte():
    xml_doc = xml_from_string(
        '<workbook><relation name="r1" type="text" formula="WITH x AS (SELECT 1) SELECT * FROM x"/></workbook>'
    )
    df = extract_custom_sql(xml_doc)
    assert bool(df.iloc[0]["is_custom_sql"]) is True


def test_extract_custom_sql_non_select_not_flagged():
    xml_doc = xml_from_string(
        '<workbook><relation name="r1" type="text" formula="some_stored_proc()"/></workbook>'
    )
    df = extract_custom_sql(xml_doc)
    assert bool(df.iloc[0]["is_custom_sql"]) is False


def test_extract_custom_sql_empty():
    xml_doc = xml_from_string("<workbook></workbook>")
    assert extract_custom_sql(xml_doc).empty


def test_extract_initial_sql():
    xml_doc = xml_from_string(
        """
        <workbook>
          <connection class="postgres" server="db.example.com">
            <initial-sql>SET search_path TO public;</initial-sql>
          </connection>
        </workbook>
        """
    )
    df = extract_initial_sql(xml_doc)
    assert len(df) == 1
    assert df.iloc[0]["initial_sql"] == "SET search_path TO public;"


def test_extract_initial_sql_named_connection_uses_caption():
    xml_doc = xml_from_string(
        """
        <workbook>
          <named-connection caption="My Conn">
            <initial-sql>SELECT 1;</initial-sql>
          </named-connection>
        </workbook>
        """
    )
    df = extract_initial_sql(xml_doc)
    assert df.iloc[0]["connection_id"] == "My Conn"


def test_extract_initial_sql_empty():
    xml_doc = xml_from_string("<workbook></workbook>")
    assert extract_initial_sql(xml_doc).empty


def test_extract_custom_sql_on_fixture(wenjie_xml):
    df = extract_custom_sql(wenjie_xml)
    assert list(df.columns) == ["relation_name", "relation_type", "custom_sql", "is_custom_sql"]
