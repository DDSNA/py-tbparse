import pandas as pd

from py_tbparse import TwbParser, to_dot


def test_to_dot_basic_structure():
    joins = pd.DataFrame(
        [{"left_table": "Orders", "left_field": "CustomerID", "operator": "=",
          "right_table": "Customers", "right_field": "CustomerID"}]
    )
    relationships = pd.DataFrame(columns=["left_table", "right_table", "left_field", "right_field", "operator"])

    dot = to_dot(joins, relationships)
    assert dot.startswith("digraph \"twb\" {")
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
    assert dot == "digraph \"twb\" {\n  rankdir=LR;\n  node [shape=box];\n}"


def test_to_dot_escapes_quotes_in_names():
    joins = pd.DataFrame(
        [{"left_table": 'Weird"Table', "left_field": "x", "operator": "=",
          "right_table": "Other", "right_field": "y"}]
    )
    empty = pd.DataFrame(columns=["left_table", "right_table", "left_field", "right_field", "operator"])
    dot = to_dot(joins, empty)
    assert 'Weird\\"Table' in dot


def test_to_dot_quotes_and_escapes_graph_name():
    # graph_name is a public parameter; a bare DOT ID can't contain
    # spaces/quotes, so an arbitrary caller-supplied name must be quoted.
    empty = pd.DataFrame(columns=["left_table", "right_table", "left_field", "right_field", "operator"])
    dot = to_dot(empty, empty, graph_name='My "Graph"')
    assert dot.startswith('digraph "My \\"Graph\\"" {')


def test_parser_get_relationship_graph_dot(wenjie_path):
    p = TwbParser(wenjie_path)
    dot = p.get_relationship_graph_dot()
    assert dot.startswith("digraph \"twb\" {")
    assert "Sheet1" in dot
    assert "Municipal_Boundaries_of_NJ" in dot


def test_repr_html(wenjie_path):
    p = TwbParser(wenjie_path)
    html = p._repr_html_()
    assert html.startswith("<div>")
    assert "test_for_wenjie.twb" in html
    assert "<table" in html


def test_graph_data_has_nodes_edges_and_kinds():
    from py_tbparse import graph_data

    cols = ["left_table", "right_table", "left_field", "right_field", "operator"]
    joins = pd.DataFrame([{"left_table": "Orders", "left_field": "ID", "operator": "=", "right_table": "Customers", "right_field": "ID"}])
    rels = pd.DataFrame([{"left_table": "Customers", "left_field": "Region", "operator": "=", "right_table": "Regions", "right_field": "Name"}])
    inferred = pd.DataFrame([{"left_table": "A", "left_field": "x", "right_table": "B", "right_field": "x", "reason": "same name"}])
    g = graph_data(joins, rels, inferred)
    assert [n["id"] for n in g["nodes"]] == ["A", "B", "Customers", "Orders", "Regions"]
    assert [(e["source"], e["target"], e["kind"]) for e in g["edges"]] == [
        ("Orders", "Customers", "join"), ("Customers", "Regions", "relationship"), ("A", "B", "inferred")]
    assert g["edges"][0]["label"] == "ID = ID"
    assert graph_data(joins, rels)["edges"][-1]["kind"] == "relationship"
    empty = pd.DataFrame(columns=cols)
    assert graph_data(empty, empty) == {"nodes": [], "edges": []}


def test_graph_data_agrees_with_the_dot_text(wenjie_path):
    p = TwbParser(wenjie_path)
    for inferred in (False, True):
        g = p.get_relationship_graph_data(include_inferred=inferred)
        dot = p.get_relationship_graph_dot(include_inferred=inferred)
        for n in g["nodes"]:
            assert f'"{n["id"]}"' in dot
        assert dot.count(" -> ") == len(g["edges"])


def test_dot_matches_graph_data_on_real_workbooks():
    # to_dot and graph_data share one edge list; over the real corpus, the DOT text has exactly one node line per
    # node and one edge line per edge (skipped when the corpus is not fetched)
    from pathlib import Path

    import pytest

    files = sorted((Path(__file__).parent / "corpus" / "files").glob("*.twb"))
    if not files:
        pytest.skip("corpus not fetched: python scripts/fetch_corpus.py")
    with_edges = 0
    for path in files:
        p = TwbParser(str(path))
        data = p.get_relationship_graph_data(include_inferred=True)
        dot = p.get_relationship_graph_dot(include_inferred=True)
        lines = dot.splitlines()
        assert len([ln for ln in lines if " -> " in ln]) == len(data["edges"]), path.name
        assert len([ln for ln in lines if ln.endswith('";') and " -> " not in ln]) == len(data["nodes"]), path.name
        with_edges += bool(data["edges"])
    assert with_edges > 20
