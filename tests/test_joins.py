from twbparser_py import extract_joins
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


def test_extract_joins_empty():
    xml_doc = xml_from_string("<workbook></workbook>")
    joins = extract_joins(xml_doc)
    assert joins.empty
