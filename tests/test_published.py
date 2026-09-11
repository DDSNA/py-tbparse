from twbparser_py import extract_published_refs
from conftest import xml_from_string


def test_flags_hasconnection_false():
    xml_doc = xml_from_string(
        '<workbook><datasource name="ds1" caption="DS 1" hasconnection="false"/></workbook>'
    )
    df = extract_published_refs(xml_doc)
    assert len(df) == 1
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
