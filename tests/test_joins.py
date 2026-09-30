from twbparser_py import extract_joins, to_dot
from conftest import xml_from_string


def test_extract_joins_clause_column_style():
    xml_doc = xml_from_string(
        """
        <workbook>
          <relation type="join" join="inner">
            <clause>
              <column table="[Orders]" name="[CustomerID]"/>
              <column table="[Customers]" name="[CustomerID]"/>
            </clause>
          </relation>
        </workbook>
        """
    )
    joins = extract_joins(xml_doc)
    assert len(joins) == 1
    row = joins.iloc[0]
    assert row["join_type"] == "inner"
    assert row["left_table"] == "Orders"
    assert row["right_table"] == "Customers"
    assert row["left_field"] == "CustomerID"
    assert row["right_field"] == "CustomerID"
    assert row["operator"] == "="


def test_extract_joins_expression_fallback():
    xml_doc = xml_from_string(
        """
        <workbook>
          <relation type="join" join="left">
            <expression op="=">
              <expression op="[Orders].[CustomerID]"/>
              <expression op="[Customers].[CustomerID]"/>
            </expression>
          </relation>
        </workbook>
        """
    )
    joins = extract_joins(xml_doc)
    assert len(joins) == 1
    row = joins.iloc[0]
    assert row["join_type"] == "left"
    assert row["left_field"] == "CustomerID"
    assert row["right_field"] == "CustomerID"


def test_extract_joins_expression_tables_from_qualified_op():
    # Modern Tableau puts the table inside the op string ("[Orders].[a]"),
    # never in a `table` attribute -- without parsing it out, left/right
    # table were None and to_dot() silently dropped the edge.
    xml_doc = xml_from_string(
        """
        <workbook>
          <relation type="join" join="inner">
            <expression op="=">
              <expression op="[Orders].[Region]"/>
              <expression op="[People].[Region]"/>
            </expression>
          </relation>
        </workbook>
        """
    )
    joins = extract_joins(xml_doc)
    assert len(joins) == 1
    row = joins.iloc[0]
    assert row["left_table"] == "Orders"
    assert row["left_field"] == "Region"
    assert row["right_table"] == "People"
    assert row["right_field"] == "Region"

    dot = to_dot(joins, joins.iloc[0:0])
    assert '"Orders" -> "People" [label="Region = Region"];' in dot


def test_extract_joins_empty():
    xml_doc = xml_from_string("<workbook></workbook>")
    joins = extract_joins(xml_doc)
    assert joins.empty


def test_extract_joins_preserves_empty_operator():
    # A present-but-empty op="" attribute must be kept as "", not coerced
    # to "=" -- xpath's [@op] predicate guarantees it's present, so this
    # isn't the "missing attribute" case that legitimately defaults to "=".
    xml_doc = xml_from_string(
        """
        <workbook>
          <relation type="join" join="left">
            <expression op="">
              <expression op="[Orders].[CustomerID]"/>
              <expression op="[Customers].[CustomerID]"/>
            </expression>
          </relation>
        </workbook>
        """
    )
    joins = extract_joins(xml_doc)
    assert len(joins) == 1
    assert joins.iloc[0]["operator"] == ""
