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


def test_extract_joins_multi_key_and_wrapper_emits_no_junk_row():
    # A two-key join wraps its '=' comparisons in an outer op="AND"
    # expression. Only the leaf comparisons are join conditions; the AND
    # wrapper must not become a row of its own (left_field='=', ...).
    xml_doc = xml_from_string(
        """
        <workbook>
          <relation type="join" join="inner">
            <expression op="AND">
              <expression op="=">
                <expression op="[Orders].[CustomerID]"/>
                <expression op="[Customers].[CustomerID]"/>
              </expression>
              <expression op="=">
                <expression op="[Orders].[Region]"/>
                <expression op="[Customers].[Region]"/>
              </expression>
            </expression>
          </relation>
        </workbook>
        """
    )
    joins = extract_joins(xml_doc)
    assert len(joins) == 2
    assert "AND" not in set(joins["operator"])
    assert list(joins["operator"]) == ["=", "="]
    assert list(joins["left_field"]) == ["CustomerID", "Region"]
    assert list(joins["right_field"]) == ["CustomerID", "Region"]
