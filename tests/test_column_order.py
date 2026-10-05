"""Internal columns come last, in the parser's tables (and so in the CLI, CSV and GUI)."""
from __future__ import annotations

import pandas as pd
import pytest

from py_tbparse import TwbParser
from py_tbparse._clean import INTERNAL_COLUMNS, internal_last
from py_tbparse._tables import TABLE_SPECS

FIXTURE = "tests/fixtures/test_for_wenjie.twb"


def test_internal_last_moves_internal_columns_and_keeps_the_rest_in_order():
    df = pd.DataFrame(columns=["datasource", "name", "tableau_internal_name", "caption", "role", "connection_id"])
    assert list(internal_last(df).columns) == ["caption", "role", "datasource", "name",
                                               "tableau_internal_name", "connection_id"]


def test_name_stays_in_front_when_the_table_shows_nothing_friendlier():
    df = pd.DataFrame(columns=["datasource", "name", "tableau_internal_name", "datatype"])
    assert list(internal_last(df).columns) == ["name", "datatype", "datasource", "tableau_internal_name"]


def test_a_table_without_internal_columns_is_returned_unchanged():
    df = pd.DataFrame(columns=["left_table", "right_table"])
    assert internal_last(df) is df


@pytest.mark.parametrize("key", list(TABLE_SPECS))
def test_no_internal_column_comes_before_a_plain_one(key):
    cols = list(TABLE_SPECS[key](TwbParser(FIXTURE)).columns)
    is_internal = [c in INTERNAL_COLUMNS or (c == "name" and ("current" in cols or "caption" in cols))
                   for c in cols]
    assert is_internal == sorted(is_internal), cols      # False... then True...


def test_the_documented_examples():
    p = TwbParser(FIXTURE)
    assert list(p.get_datasources().columns)[-2:] == ["datasource", "connection_id"]
    assert list(p.get_field_renames().columns)[-2:] == ["datasource", "name"]
    assert list(p.get_dashboard_sheets().columns)[-1] == "zone_id"
    assert list(p.get_initial_sql().columns) == ["initial_sql", "connection_id"]
