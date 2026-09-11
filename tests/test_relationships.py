from twbparser_py import extract_relations, extract_relationships
from conftest import xml_from_string


def test_extract_relations_fixture(wenjie_xml):
    relations = extract_relations(wenjie_xml)
    assert not relations.empty
    assert "table" in relations.columns


def test_extract_relationships_fixture(wenjie_xml):
    rels = extract_relationships(wenjie_xml)
    assert len(rels) == 1
    row = rels.iloc[0]
    assert row["left_table"] == "Sheet1"
    assert row["right_table"] == "Municipal_Boundaries_of_NJ"
    assert row["left_field"] == "County"
    assert row["right_field"] == "COUNTY"
    assert row["operator"] == "="


def test_extract_relations_empty():
    xml_doc = xml_from_string("<workbook></workbook>")
    assert extract_relations(xml_doc).empty


def test_extract_relationships_empty():
    xml_doc = xml_from_string("<workbook></workbook>")
    assert extract_relationships(xml_doc).empty
