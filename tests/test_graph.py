import pandas as pd

from twbparser_py import TwbParser, to_dot


def test_to_dot_basic_structure():
    joins = pd.DataFrame(
        [{"left_table": "Orders", "left_field": "CustomerID", "operator": "=",
          "right_table": "Customers", "right_field": "CustomerID"}]
    )
    relationships = pd.DataFrame(columns=["left_table", "right_table", "left_field", "right_field", "operator"])

    dot = to_dot(joins, relationships)
    assert dot.startswith("digraph twb {")
    assert dot.endswith("}")
    assert '"Orders";' in dot
    assert '"Customers";' in dot
    assert '"Orders" -> "Customers" [label="CustomerID = CustomerID"];' in dot


def test_to_dot_inferred_edges_are_dashed():
    joins = pd.DataFrame(columns=["left_table", "right_table", "left_field", "right_field", "operator"])
    relationships = pd.DataFrame(columns=["left_table", "right_table", "left_field", "right_field", "operator"])
    inferred = pd.DataFrame(
        [{"left_table": "A", "left_field": "id", "right_table": "B", "right_field": "id",
          "reason": "matched field name"}]
    )
    dot = to_dot(joins, relationships, inferred)
    assert "style=dashed" in dot
    assert '"A" -> "B"' in dot


def test_to_dot_empty_inputs():
    empty = pd.DataFrame(columns=["left_table", "right_table", "left_field", "right_field", "operator"])
    dot = to_dot(empty, empty)
    assert dot == "digraph twb {\n  rankdir=LR;\n  node [shape=box];\n}"


def test_to_dot_escapes_quotes_in_names():
    joins = pd.DataFrame(
        [{"left_table": 'Weird"Table', "left_field": "x", "operator": "=",
          "right_table": "Other", "right_field": "y"}]
    )
    empty = pd.DataFrame(columns=["left_table", "right_table", "left_field", "right_field", "operator"])
    dot = to_dot(joins, empty)
    assert 'Weird\\"Table' in dot


def test_parser_get_relationship_graph_dot(wenjie_path):
    p = TwbParser(wenjie_path)
    dot = p.get_relationship_graph_dot()
    assert dot.startswith("digraph twb {")
    assert "Sheet1" in dot
    assert "Municipal_Boundaries_of_NJ" in dot


def test_repr_html(wenjie_path):
    p = TwbParser(wenjie_path)
    html = p._repr_html_()
    assert html.startswith("<div>")
    assert "test_for_wenjie.twb" in html
    assert "<table" in html
