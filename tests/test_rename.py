import json

import pandas as pd
import pytest

from twbparser_py import TwbParser, normalize_name, suggest_field_renames
from twbparser_py.cli import main


def _fields(names, ds="ds1", **extra):
    return pd.DataFrame(
        [{"datasource": ds, "name": f"[{n}]", "caption": None, "field_clean": n,
          "is_parameter": False, **extra} for n in names]
    )


@pytest.mark.parametrize(
    "raw, style, expected",
    [
        ("ORDER_ID", "title", "Order ID"),
        ("orderId", "title", "Order ID"),
        ("order-date", "title", "Order Date"),
        ("Sales (copy)", "title", "Sales"),
        ("Sales (copy) 2", "title", "Sales"),
        ("CENSUS2020", "title", "Census2020"),
        ("customerName", "snake", "customer_name"),
        ("HTTPStatus", "snake", "http_status"),
        ("Order_ID", "lower", "order id"),
        ("Order_ID", "keep", "Order ID"),
    ],
)
def test_normalize_name(raw, style, expected):
    assert normalize_name(raw, style) == expected


def test_normalize_name_missing_and_bad_style():
    assert normalize_name(None) is None
    assert normalize_name("  ") is None
    with pytest.raises(ValueError):
        normalize_name("x", "shouty")


def test_normalizes_without_reference():
    out = suggest_field_renames(_fields(["ORDER_ID", "customerName", "Sales"]))
    got = dict(zip(out["current"], out["suggested"]))
    assert got == {"ORDER_ID": "Order ID", "customerName": "Customer Name", "Sales": "Sales"}
    assert out.set_index("current").loc["Sales", "reason"] == "already clean"
    assert not out.set_index("current").loc["Sales", "changed"]


def test_dedup_suffix_only_removed_when_base_exists():
    out = suggest_field_renames(_fields(["Order ID", "Order ID1", "Sales (Orders1)", "Address2"]))
    got = dict(zip(out["current"], out["suggested"]))
    # "Order ID1" would collide with "Order ID", so it stays put as a conflict.
    assert got["Order ID1"] == "Order ID1"
    assert out.set_index("current").loc["Order ID1", "reason"] == "conflict"
    # No un-suffixed sibling -> suffix may be meaningful, left alone.
    assert got["Address2"] == "Address2"
    assert got["Sales (Orders1)"] == "Sales (Orders1)"


def test_dedup_suffix_removed_when_sibling_is_spelled_differently():
    out = suggest_field_renames(_fields(["ORDER_ID", "Order ID1"]))
    row = out.set_index("current").loc["Order ID1"]
    assert row["suggested"] == "Order ID" or row["reason"] == "conflict"


def test_reference_spelling_wins():
    ref = _fields(["Order ID", "Customer Name", "Sales Amount"])
    new = _fields(["ORDER_ID", "customerName", "Sales Amount (Orders1)", "NEW_COLUMN"])
    out = suggest_field_renames(new, reference=ref).set_index("current")
    assert out.loc["ORDER_ID", "suggested"] == "Order ID"
    assert out.loc["ORDER_ID", "reason"] == "matches reference"
    assert out.loc["customerName", "suggested"] == "Customer Name"
    assert out.loc["Sales Amount (Orders1)", "suggested"] == "Sales Amount"
    # Not in the reference: falls back to plain normalisation.
    assert out.loc["NEW_COLUMN", "suggested"] == "New Column"
    assert out.loc["NEW_COLUMN", "reason"] == "normalized"


def test_reference_fuzzy_match_and_cutoff():
    ref = ["Customer Name"]
    new = _fields(["CUSTOMER_NAMES"])
    out = suggest_field_renames(new, reference=ref).iloc[0]
    assert out["suggested"] == "Customer Name"
    assert out["reason"] == "close to reference"
    assert 0.85 <= out["score"] < 1
    strict = suggest_field_renames(new, reference=ref, fuzzy_cutoff=0.99).iloc[0]
    assert strict["reason"] == "normalized"


def test_reference_accepts_list_and_parser():
    new = _fields(["ORDER_ID"])
    assert suggest_field_renames(new, reference=["Order ID"]).iloc[0]["suggested"] == "Order ID"


def test_collision_keeps_already_clean_field():
    out = suggest_field_renames(_fields(["ORDER_ID", "Order ID"])).set_index("current")
    assert out.loc["Order ID", "suggested"] == "Order ID"
    assert out.loc["ORDER_ID", "suggested"] == "ORDER_ID"
    assert out.loc["ORDER_ID", "reason"] == "conflict"
    assert not out.loc["ORDER_ID", "changed"]


def test_same_name_in_different_datasources_is_not_a_conflict():
    df = pd.concat([_fields(["ORDER_ID"], ds="a"), _fields(["ORDER_ID"], ds="b")])
    out = suggest_field_renames(df)
    assert list(out["suggested"]) == ["Order ID", "Order ID"]


def test_parameters_skipped_and_caption_preferred():
    df = _fields(["ORDER_ID", "Parameter 1"])
    df.loc[1, "is_parameter"] = True
    df.loc[0, "caption"] = "Order_Number"
    out = suggest_field_renames(df)
    assert list(out["current"]) == ["Order_Number"]
    assert out.iloc[0]["name"] == "[ORDER_ID]"


def test_only_changed_and_empty():
    out = suggest_field_renames(_fields(["Sales", "ORDER_ID"]), only_changed=True)
    assert list(out["current"]) == ["ORDER_ID"]
    assert suggest_field_renames(pd.DataFrame()).empty


def test_parser_method_and_cli(wenjie_path, capsys):
    p = TwbParser(wenjie_path)
    out = p.get_field_renames(only_changed=True)
    # Physical columns are skipped; Tableau-level fields keep their captions.
    assert "MUN_LABEL" not in set(out["current"])
    assert out.set_index("current").loc["no data", "suggested"] == "No Data"

    assert main(["rename", wenjie_path, "--only-changed", "-f", "json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert any(r["current"] == "no data" for r in rows)

    assert main(["rename", wenjie_path, "-r", wenjie_path, "--only-changed"]) == 0
    assert "(empty)" in capsys.readouterr().out


def test_cli_missing_file(capsys):
    assert main(["rename", "nope.twb"]) == 1
    assert "error" in capsys.readouterr().err


def test_physical_columns_ignored_when_bracketed_exist():
    df = pd.DataFrame(
        [
            {"datasource": "d", "name": "MUN_LABEL", "caption": None, "field_clean": "MUN_LABEL", "is_parameter": False},
            {"datasource": "d", "name": "[MUN_LABEL]", "caption": "Mun Label", "field_clean": "MUN_LABEL", "is_parameter": False},
        ]
    )
    out = suggest_field_renames(df)
    assert list(out["current"]) == ["Mun Label"]
    assert not out["changed"].any()
