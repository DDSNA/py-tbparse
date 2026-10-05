from py_tbparse import extract_relations, extract_relationships
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


def test_extract_relationships_multi_key_and_emits_one_row_per_clause():
    xml_doc = xml_from_string(
        """
        <workbook>
          <relationships>
            <relationship>
              <first-end-point object-id="A"/>
              <second-end-point object-id="B"/>
              <expression op="AND">
                <expression op="=">
                  <expression op="[a (Orders)]"/>
                  <expression op="[a (People)]"/>
                </expression>
                <expression op="&lt;=">
                  <expression op="[b (Orders)]"/>
                  <expression op="[b (People)]"/>
                </expression>
              </expression>
            </relationship>
          </relationships>
        </workbook>
        """
    )
    rels = extract_relationships(xml_doc)
    assert list(zip(rels["left_field"], rels["operator"], rels["right_field"])) == [
        ("a (Orders)", "=", "a (People)"),
        ("b (Orders)", "<=", "b (People)"),
    ]
    assert (rels["left_table"] == "A").all()
    assert (rels["right_table"] == "B").all()


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
    from py_tbparse.relationships import _rel_field_expr

    node = etree.fromstring(
        '<expression op="[LOWER(x)]" value="[Region (People)]"/>'
    )
    assert _rel_field_expr(node) == "LOWER(x)"


def test_rel_field_expr_keeps_nested_bracket_calc_whole():
    from lxml import etree
    from py_tbparse.relationships import _rel_field_expr

    node = etree.fromstring('<expression op="[LOWER([Region])]"/>')
    assert _rel_field_expr(node) == "LOWER([Region])"


_JOIN_XML = """
<workbook>
  <relation type="join" join="inner">
    <clause type="join"><expression op="="/></clause>
    <relation connection="c1" name="a" table="[dbo].[a]" type="table"/>
    <relation type="join" join="left">
      <relation connection="c1" name="b" table="[dbo].[b]" type="table"/>
      <relation connection="c1" name="c" table="[dbo].[c]" type="table"/>
    </relation>
  </relation>
</workbook>
"""


def test_a_join_row_is_named_after_the_tables_it_joins():
    rel = extract_relations(xml_from_string(_JOIN_XML))
    assert not (rel["name"].isna() & rel["table"].isna()).any()
    joins = rel[rel["type"] == "join"]
    assert joins["name"].tolist() == ["inner join of a, b and c", "left join of b and c"]
    assert joins["join"].tolist() == ["inner", "left"]


def test_a_join_row_does_not_carry_the_text_of_its_subtree():
    rel = extract_relations(xml_from_string(_JOIN_XML))
    assert (rel[rel["type"] == "join"]["custom_sql"] == "").all()


def test_table_rows_are_unchanged_by_joins():
    rel = extract_relations(xml_from_string(_JOIN_XML))
    tables = rel[rel["type"] == "table"]
    assert tables["name"].tolist() == ["a", "b", "c"]
    assert tables["table"].tolist() == ["[dbo].[a]", "[dbo].[b]", "[dbo].[c]"]


def test_a_custom_sql_relation_keeps_its_sql_and_a_join_over_it_names_it():
    xml = ("<workbook><relation type='join' join='inner'>"
           "<relation name='Custom SQL Query' type='text'>select 1</relation>"
           "<relation name='t' table='[t]' type='table'/></relation></workbook>")
    rel = extract_relations(xml_from_string(xml))
    assert rel[rel["type"] == "text"]["custom_sql"].tolist() == ["select 1"]
    assert rel[rel["type"] == "join"]["name"].tolist() == ["inner join of Custom SQL Query and t"]
