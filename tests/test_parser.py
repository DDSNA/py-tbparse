import pytest

from twbparser_py import TwbParser


def test_parser_loads_twb(wenjie_path):
    p = TwbParser(wenjie_path)
    assert len(p.get_fields()) > 0
    assert len(p.get_datasources()) == 2
    assert len(p.get_calculated_fields()) == 1
    assert len(p.get_relationships()) == 1
    assert p.get_joins().empty
    assert p.get_dashboards().empty  # fixture has no dashboards


def test_parser_loads_twbx(zip_twbx_path):
    p = TwbParser(zip_twbx_path)
    assert p.twbx_path is not None
    assert p.twbx_dir is not None
    assert not p.get_twbx_manifest().empty
    assert len(p.get_raw_fields()) > 0


def test_parser_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        TwbParser("does_not_exist.twb")


def test_parser_unsupported_extension(tmp_path):
    bad = tmp_path / "file.txt"
    bad.write_text("hello")
    with pytest.raises(ValueError):
        TwbParser(str(bad))


def test_get_overview_returns_single_row(wenjie_path):
    p = TwbParser(wenjie_path)
    overview = p.get_overview()
    assert len(overview) == 1
    assert overview.iloc[0]["datasources"] == 2
