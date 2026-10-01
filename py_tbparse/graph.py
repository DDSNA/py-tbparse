"""Graphviz DOT export of table relationships.

Not part of the R package (which uses igraph/ggraph for
`plot_dependency_graph`/`plot_relationship_graph`) -- this is a
dependency-free equivalent: render `joins`/`relationships` (and
optionally `inferred_relationships`) as a DOT digraph, which any
Graphviz-compatible tool (`dot`, most notebook/markdown renderers) can
turn into a picture without adding a plotting library to this package.
"""

from __future__ import annotations

import pandas as pd


def _escape(s: str) -> str:
    return str(s).replace("\\", "\\\\").replace('"', '\\"')


def _edges_from(df: pd.DataFrame, label_fn) -> list[tuple[str, str, str]]:
    if df is None or df.empty:
        return []
    edges = []
    for row in df.itertuples(index=False):
        left = getattr(row, "left_table", None)
        right = getattr(row, "right_table", None)
        if not left or not right:
            continue
        edges.append((str(left), str(right), label_fn(row)))
    return edges


def _join_label(row) -> str:
    op = getattr(row, "operator", "=") or "="
    return f"{row.left_field} {op} {row.right_field}"


def _relationship_label(row) -> str:
    op = getattr(row, "operator", "=") or "="
    return f"{row.left_field} {op} {row.right_field}"


def _inferred_label(row) -> str:
    return f"{row.left_field} ~ {row.right_field} ({row.reason})"


def to_dot(
    joins_df: pd.DataFrame,
    relationships_df: pd.DataFrame,
    inferred_df: pd.DataFrame | None = None,
    graph_name: str = "twb",
) -> str:
    """Render join/relationship (and optionally inferred) edges as a
    Graphviz DOT digraph string.

    Solid edges are real joins/relationships; dashed edges (when
    `inferred_df` is passed) are `infer_implicit_relationships()` guesses.
    """
    edges: list[tuple[str, str, str, bool]] = []
    for left, right, label in _edges_from(joins_df, _join_label):
        edges.append((left, right, label, False))
    for left, right, label in _edges_from(relationships_df, _relationship_label):
        edges.append((left, right, label, False))
    if inferred_df is not None:
        for left, right, label in _edges_from(inferred_df, _inferred_label):
            edges.append((left, right, label, True))

    nodes = sorted({n for left, right, _, _ in edges for n in (left, right)})

    # Quote the graph name -- a bare DOT ID can't contain spaces/braces/etc,
    # and graph_name is a public parameter so a caller could pass anything.
    lines = [f'digraph "{_escape(graph_name)}" {{', "  rankdir=LR;", '  node [shape=box];']
    for n in nodes:
        lines.append(f'  "{_escape(n)}";')
    for left, right, label, inferred in edges:
        style = ' [style=dashed, label="{}"]'.format(_escape(label)) if inferred else ' [label="{}"]'.format(
            _escape(label)
        )
        lines.append(f'  "{_escape(left)}" -> "{_escape(right)}"{style};')
    lines.append("}")
    return "\n".join(lines)
