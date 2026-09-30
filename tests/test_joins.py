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


def test_extract_joins_nested_join_not_double_counted():
    # inner(Orders, left(People, Returns)): the nested join's condition
    # belongs only to the inner <relation>, not also to the outer one.
    xml_doc = xml_from_string(
        """
        <workbook>
          <relation type="join" join="inner">
            <clause>
              <column table="[Orders]" name="[Region]"/>
              <column table="[People]" name="[Region]"/>
            </clause>
            <relation name="Orders" table="[Orders]" type="table"/>
            <relation type="join" join="left">
              <clause>
                <column table="[People]" name="[r]"/>
                <column table="[Returns]" name="[r]"/>
              </clause>
              <relation name="People" table="[People]" type="table"/>
              <relation name="Returns" table="[Returns]" type="table"/>
            </relation>
          </relation>
        </workbook>
        """
    )
    joins = extract_joins(xml_doc)
    assert len(joins) == 2
    assert list(joins["join_type"]) == ["inner", "left"]
    assert list(joins["left_field"]) == ["Region", "r"]


def test_extract_joins_nested_expression_join_not_double_counted():
    xml_doc = xml_from_string(
        """
        <workbook>
          <relation type="join" join="inner">
            <clause type="join">
              <expression op="=">
                <expression op="[Orders].[Region]"/>
                <expression op="[People].[Region]"/>
              </expression>
            </clause>
            <relation type="join" join="left">
              <clause type="join">
                <expression op="=">
                  <expression op="[People].[r]"/>
                  <expression op="[Returns].[r]"/>
                </expression>
              </clause>
            </relation>
          </relation>
        </workbook>
        """
    )
    joins = extract_joins(xml_doc)
    assert len(joins) == 2
    assert list(joins["join_type"]) == ["inner", "left"]
    assert list(joins["left_field"]) == ["Region", "r"]
