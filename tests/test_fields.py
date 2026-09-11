import pandas as pd

from twbparser_py import extract_columns_with_table_source, infer_implicit_relationships


def test_extract_columns_with_table_source(wenjie_xml):
    fields = extract_columns_with_table_source(wenjie_xml)
    assert not fields.empty
    assert "OBJECTID" in fields["name"].values
    assert (fields["is_parameter"] == False).all()  # noqa: E712


def test_infer_implicit_relationships_matches_by_field_name():
    fields_df = pd.DataFrame(
        [
            {"table_clean": "Orders", "field_clean": "CustomerID", "table": None, "name": None,
             "semantic_role": None, "is_parameter": False},
            {"table_clean": "Customers", "field_clean": "customerid", "table": None, "name": None,
             "semantic_role": None, "is_parameter": False},
            {"table_clean": "Orders", "field_clean": "Amount", "table": None, "name": None,
             "semantic_role": None, "is_parameter": False},
        ]
    )
    out = infer_implicit_relationships(fields_df)
    assert not out.empty
    pairs = set(zip(out["left_table"], out["left_field"], out["right_table"], out["right_field"]))
    assert any(
        {"Orders", "Customers"} == {lt, rt} for lt, _, rt, _ in
        [(row.left_table, row.left_field, row.right_table, row.right_field) for row in out.itertuples()]
    )
    assert (out["reason"] == "matched field name").any()


def test_infer_implicit_relationships_matches_by_semantic_role():
    fields_df = pd.DataFrame(
        [
            {"table_clean": "Orders", "field_clean": "cust_id", "table": None, "name": None,
             "semantic_role": "Customer.ID", "is_parameter": False},
            {"table_clean": "Customers", "field_clean": "id", "table": None, "name": None,
             "semantic_role": "Customer.ID", "is_parameter": False},
        ]
    )
    out = infer_implicit_relationships(fields_df)
    assert (out["reason"] == "matched semantic-role").any()


def test_infer_implicit_relationships_empty_input():
    out = infer_implicit_relationships(pd.DataFrame())
    assert out.empty
    assert list(out.columns) == ["left_table", "left_field", "right_table", "right_field", "reason"]
