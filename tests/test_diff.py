import pandas as pd

from twbparser_py import TwbParser, diff_tables, diff_workbooks


def test_diff_tables_identical_frames_are_empty():
    a = pd.DataFrame([{"x": 1, "y": "a"}, {"x": 2, "y": "b"}])
    b = a.copy()
    out = diff_tables(a, b)
    assert out.empty


def test_diff_tables_detects_added_and_removed():
    a = pd.DataFrame([{"x": 1, "y": "a"}])
    b = pd.DataFrame([{"x": 2, "y": "b"}])
    out = diff_tables(a, b)
    assert len(out) == 2
    assert set(out["_diff"]) == {"added", "removed"}
    added = out[out["_diff"] == "added"].iloc[0]
    removed = out[out["_diff"] == "removed"].iloc[0]
    assert added["x"] == 2
    assert removed["x"] == 1


def test_diff_tables_both_empty():
    empty = pd.DataFrame(columns=["x", "y"])
    out = diff_tables(empty, empty)
    assert out.empty


def test_diff_workbooks_self_is_empty(wenjie_path):
    a = TwbParser(wenjie_path)
    b = TwbParser(wenjie_path)
    out = diff_workbooks(a, b, table="datasources")
    assert out.empty


def test_diff_workbooks_unknown_table_raises(wenjie_path):
    a = TwbParser(wenjie_path)
    b = TwbParser(wenjie_path)
    import pytest

    with pytest.raises(ValueError):
        diff_workbooks(a, b, table="not-a-table")
