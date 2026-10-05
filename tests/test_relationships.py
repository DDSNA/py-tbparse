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


_COLLECTION_XML = """
<workbook>
  <relation type='collection'>
    <relation connection='c1' name='Orders' table='[Orders$]' type='table'/>
    <relation connection='c1' name='People' table='[People$]' type='table'/>
    <relation connection='c2' name='Returns' table='[Returns$]' type='table'/>
  </relation>
</workbook>
"""


def test_collection_is_named_after_its_members_and_has_no_sql_text():
    # A collection holds the physical tables under one logical model; it has no name or table itself.
    rel = extract_relations(xml_from_string(_COLLECTION_XML))
    row = rel[rel["type"] == "collection"].iloc[0]
    assert row["name"] == "collection of Orders, People and Returns"
    assert row["custom_sql"] == ""
    assert list(rel.columns) == ["name", "table", "connection", "type", "join", "custom_sql"]
    # members still have their own rows
    assert set(rel[rel["type"] == "table"]["name"]) == {"Orders", "People", "Returns"}


def test_empty_and_single_member_collection_names():
    one = extract_relations(xml_from_string(
        "<workbook><relation type='collection'><relation name='A' table='[A]' type='table'/></relation></workbook>"))
    assert one[one["type"] == "collection"].iloc[0]["name"] == "collection of A"
    none = extract_relations(xml_from_string("<workbook><relation type='collection'/></workbook>"))
    assert none.iloc[0]["name"] == "empty collection"


def test_collection_with_prefixed_tag_in_real_fixture(wenjie_xml):
    # tests/fixtures/test_for_wenjie.twb writes the collection as a namespaced element the plain
    # `relation` query does not see; its members must still be listed and it must not add an empty row. (Only `relation`-tagged collections get their own row; the prefixed one is not matched by the query, as before.)
    rel = extract_relations(wenjie_xml)
    assert not rel["name"].isna().all()
    assert rel[rel["type"] == "collection"]["name"].notna().all()


def test_join_name_ignores_nested_collection_rows():
    rel = extract_relations(xml_from_string(
        "<workbook><relation type='join' join='inner'>"
        "<relation name='A' table='[A]' type='table'/><relation name='B' table='[B]' type='table'/>"
        "</relation></workbook>"))
    assert rel.iloc[0]["name"] == "inner join of A and B"


def test_collection_never_reaches_the_graph(wenjie_xml):
    from py_tbparse import extract_joins, extract_relationships
    from py_tbparse.graph import to_dot
    dot = to_dot(extract_joins(wenjie_xml), extract_relationships(wenjie_xml))
    assert "collection" not in dot and dot.startswith("digraph") and dot.rstrip().endswith("}")
