from twbparser_py import extract_published_refs
from conftest import xml_from_string


def test_columns_match_r_shape():
    # R/published.R's tibble has name, caption, hasconn, likely_published,
    # hints (it builds with an extra "raw" column, then drops only that
    # one) -- "hasconn" is easy to drop by accident since it's a local
    # intermediate variable name too.
    xml_doc = xml_from_string('<workbook><datasource name="ds1" caption="DS 1"/></workbook>')
    df = extract_published_refs(xml_doc)
    assert list(df.columns) == ["name", "caption", "hasconn", "likely_published", "hints"]


def test_flags_hasconnection_false():
    xml_doc = xml_from_string(
        '<workbook><datasource name="ds1" caption="DS 1" hasconnection="false"/></workbook>'
    )
    df = extract_published_refs(xml_doc)
    assert len(df) == 1
    assert df.iloc[0]["hasconn"] == "false"
    assert bool(df.iloc[0]["likely_published"]) is True


def test_flags_published_marker_in_text():
    # The marker regex runs against xml_text()-equivalent element text
    # content, not attribute values -- put it in a child element's text.
    xml_doc = xml_from_string(
        """
        <workbook>
          <datasource name="ds1" caption="DS 1" hasconnection="true">
            <description>Published to Tableau Server</description>
          </datasource>
        </workbook>
        """
    )
    df = extract_published_refs(xml_doc)
    assert bool(df.iloc[0]["likely_published"]) is True


def test_embedded_not_flagged():
    xml_doc = xml_from_string(
        '<workbook><datasource name="ds1" caption="DS 1" hasconnection="true"><connection class="excel"/></datasource></workbook>'
    )
    df = extract_published_refs(xml_doc)
    assert bool(df.iloc[0]["likely_published"]) is False
    assert df.iloc[0]["hints"] == "embedded or no published markers"


def test_empty():
    xml_doc = xml_from_string("<workbook></workbook>")
    assert extract_published_refs(xml_doc).empty
