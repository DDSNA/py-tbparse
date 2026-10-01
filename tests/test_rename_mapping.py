import shutil

import pandas as pd
import pytest

from py_tbparse import TwbParser, compare_field_schemas, load_rename_mapping
from py_tbparse.cli import main


def _fields(names, ds="ds1"):
    return pd.DataFrame(
        [{"datasource": ds, "name": f"[{n}]", "caption": None, "is_parameter": False} for n in names]
    )


def test_mapping_round_trip_applies_hand_edits(wenjie_path, tmp_path, capsys):
    src = tmp_path / "book.twb"
    shutil.copy(wenjie_path, src)
    csv_path = tmp_path / "mapping.csv"
    assert main(["rename", str(src), "-f", "csv", "-o", str(csv_path)]) == 0
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    row = df.index[df["changed"] == "True"][0]
    df.loc[row, "suggested"] = "My Custom Name"
    df.to_csv(csv_path, index=False)

    assert main(["rename", str(src), "--apply", str(csv_path)]) == 0
    assert "wrote" in capsys.readouterr().err
    fixed = TwbParser(str(tmp_path / "book_renamed.twb"))
    assert "My Custom Name" in set(fixed.get_fields()["caption"].dropna())
    # applying again would overwrite the output
    assert main(["rename", str(src), "--apply", str(csv_path)]) == 1


def test_load_rename_mapping_blank_means_unchanged_and_validates():
    df = pd.DataFrame(
        {"datasource": ["d", "d"], "name": ["[A]", "[B]"], "current": ["A", "B"], "suggested": ["", "Bee"]}
    )
    out = load_rename_mapping(df)
    assert list(out["changed"]) == [False, True]
    assert list(out["suggested"]) == ["A", "Bee"]
    with pytest.raises(ValueError, match="missing column"):
        load_rename_mapping(pd.DataFrame({"name": ["[A]"]}))
    dup = pd.DataFrame({"datasource": ["d", "d"], "name": ["[A]", "[B]"], "suggested": ["X", "x"]})
    with pytest.raises(ValueError, match="both"):
        load_rename_mapping(dup)


def test_cli_apply_errors(wenjie_path, tmp_path, capsys):
    assert main(["rename", str(wenjie_path), "--apply", str(tmp_path / "nope.csv")]) == 1
    bad = tmp_path / "bad.csv"
    bad.write_text("a,b\n1,2\n")
    assert main(["rename", str(wenjie_path), "--apply", str(bad)]) == 1
    assert "missing column" in capsys.readouterr().err


def test_compare_field_schemas_reports_both_sides():
    gaps = compare_field_schemas(_fields(["ORDER_ID", "NEW_THING", "SALES"]), ["Order ID", "Sales", "Old Thing"])
    assert list(gaps["side"]) == ["new only", "old only"]
    assert list(gaps["name"]) == ["NEW_THING", "Old Thing"]
    assert gaps.loc[0, "closest"] == "Old Thing"


def test_cli_missing(wenjie_path, capsys):
    with pytest.raises(SystemExit):  # needs --reference
        main(["rename", str(wenjie_path), "--missing"])
    capsys.readouterr()
    assert main(["rename", str(wenjie_path), "-r", str(wenjie_path), "--missing", "-f", "csv"]) == 0
    assert capsys.readouterr().out.startswith("side,datasource,name,closest")
