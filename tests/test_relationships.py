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


def test_extract_relationships_preserves_empty_operator():
    xml_doc = xml_from_string(
        """
        <workbook>
          <relationships>
            <relationship>
              <first-end-point object-id="A"/>
              <second-end-point object-id="B"/>
              <expression op="">
                <expression op="[TableA].[Field1]"/>
                <expression op="[TableB].[Field2]"/>
              </expression>
            </relationship>
          </relationships>
        </workbook>
        """
    )
    rels = extract_relationships(xml_doc)
    assert len(rels) == 1
    row = rels.iloc[0]
    assert row["left_field"] == "Field1"
    assert row["right_field"] == "Field2"
    assert row["operator"] == ""


def test_extract_relations_preserves_empty_custom_sql():
    xml_doc = xml_from_string(
        '<workbook><relation name="r1" table="[T]" type="table"/></workbook>'
    )
    relations = extract_relations(xml_doc)
    assert relations.iloc[0]["custom_sql"] == ""


def _single_relationship(lhs_op, rhs_op):
    xml_doc = xml_from_string(
        f"""
        <workbook>
          <relationships>
            <relationship>
              <first-end-point object-id="A"/>
              <second-end-point object-id="B"/>
              <expression op="=">
                <expression op="{lhs_op}"/>
                <expression op="{rhs_op}"/>
              </expression>
            </relationship>
          </relationships>
        </workbook>
        """
    )
    rels = extract_relationships(xml_doc)
    assert len(rels) == 1
    return rels.iloc[0]


def test_extract_relationships_disambiguated_name_is_not_calc():
    # Tableau disambiguates duplicate column names as "Field (Table)"; that
    # word + " (...)" shape must not be mistaken for a function call.
    row = _single_relationship("[Region (People)]", "[Region]")
    assert row["left_field"] == "Region (People)"
    assert row["right_field"] == "Region"
    assert not row["left_is_calc"]
    assert not row["right_is_calc"]


def test_extract_relationships_real_calcs_are_calc():
    for formula in (
        "DATEPART('year', [Order Date])",
        "LOWER([x])",
        "IFNULL([a],[b])",
        "UPPER ([Region (People)])",
    ):
        row = _single_relationship(f"[{formula}]", "[Region]")
        assert row["left_is_calc"], formula
        assert not row["right_is_calc"], formula


def test_rel_field_expr_prefers_calc_over_disambiguated_name():
    from lxml import etree
    from twbparser_py.relationships import _rel_field_expr

    node = etree.fromstring(
        '<expression op="[LOWER(x)]" value="[Region (People)]"/>'
    )
    assert _rel_field_expr(node) == "LOWER(x)"
