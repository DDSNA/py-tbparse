import warnings

from twbparser_py import scan_folder


def test_scan_folder_finds_both_fixtures():
    df = scan_folder("tests/fixtures", table="overview")
    assert len(df) == 2
    assert set(df["workbook"]) == {"test_for_wenjie.twb", "test_for_zip.twbx"}


def test_scan_folder_empty_directory(tmp_path):
    df = scan_folder(str(tmp_path), table="overview")
    assert df.empty
    assert list(df.columns) == ["workbook"]


def test_scan_folder_unknown_table_raises():
    import pytest

    with pytest.raises(ValueError):
        scan_folder("tests/fixtures", table="not-a-table")


def test_scan_folder_skips_unparseable_file(tmp_path):
    bad = tmp_path / "broken.twb"
    bad.write_text("not valid xml <<<")
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        df = scan_folder(str(tmp_path), table="overview")
        assert any("skipping" in str(warning.message) for warning in w)
    assert df.empty


def test_scan_folder_datasources_table():
    df = scan_folder("tests/fixtures", table="datasources")
    assert "workbook" in df.columns
    assert "datasource" in df.columns
    assert (df["workbook"] == "test_for_wenjie.twb").sum() == 2
