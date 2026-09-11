from twbparser_py import extract_datasource_details, extract_named_connections
from conftest import xml_from_string


def test_extract_named_connections(wenjie_xml):
    conns = extract_named_connections(wenjie_xml)
    assert not conns.empty
    assert "connection_class" in conns.columns


def test_extract_datasource_details(wenjie_xml):
    res = extract_datasource_details(wenjie_xml)
    assert set(res.keys()) == {"data_sources", "parameters", "all_sources"}
    ds = res["data_sources"]
    assert not ds.empty
    assert "Municipal_Boundaries_of_NJ" in ds["datasource"].values


def test_target_coalesce_keeps_empty_server_string():
    # dplyr::coalesce()/%||% only substitute on NA/NULL, never on "" --
    # an empty-but-present server attribute must not fall through to
    # directory/filename.
    xml_doc = xml_from_string(
        """
        <workbook>
          <named-connection name="c1" caption="Conn 1">
            <connection class="other" server="" directory="/data" filename="f.csv"/>
          </named-connection>
        </workbook>
        """
    )
    conns = extract_named_connections(xml_doc)
    assert conns.iloc[0]["connection_target"] == ""


def test_athena_region_falls_back_to_full_server_on_no_match():
    # R's sub() returns the original (lowercased) string unchanged when
    # the finer region pattern fails to match, not NA.
    xml_doc = xml_from_string(
        """
        <workbook>
          <named-connection name="c1" caption="Conn 1">
            <connection class="athena" server="jdbc:athena." dbname="mydb"/>
          </named-connection>
        </workbook>
        """
    )
    conns = extract_named_connections(xml_doc)
    assert conns.iloc[0]["region"] == "jdbc:athena."


def test_athena_region_extracts_when_pattern_matches():
    xml_doc = xml_from_string(
        """
        <workbook>
          <named-connection name="c1" caption="Conn 1">
            <connection class="athena" server="athena.us-east-1.amazonaws.com" dbname="mydb"/>
          </named-connection>
        </workbook>
        """
    )
    conns = extract_named_connections(xml_doc)
    assert conns.iloc[0]["region"] == "us-east-1"
