import tempfile

import pytest
from conftest import REAL_PARAMS_XML

from twbparser_py import TwbParser
from twbparser_py._xml import load_workbook_xml


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
    assert not p.get_twbx_manifest().empty
    assert len(p.get_raw_fields()) > 0
    assert p.get_overview().iloc[0]["file"].endswith(".twb")


def test_parser_twbx_leaves_no_temp_files(zip_twbx_path, tmp_path, monkeypatch):
    # Loading a .twbx used to extract into a fresh timestamped temp dir that
    # was never cleaned up, so batch scans / repeated GUI loads filled /tmp.
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    TwbParser(zip_twbx_path)
    load_workbook_xml(zip_twbx_path)
    assert list(tmp_path.iterdir()) == []


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


_PARAMS_CALC_XML = """
<workbook>
  <datasources>
    <datasource name="Orders">
      <column name="[Amount]" caption="Amount" datatype="real" role="measure">
        <calculation class="tableau" formula="SUM([Sales])"/>
      </column>
    </datasource>
    <datasource name="Parameters">
      <column name="[Calc Helper]" caption="Calc Helper" datatype="integer" role="measure">
        <calculation class="tableau" formula="1+1"/>
      </column>
    </datasource>
  </datasources>
</workbook>
"""


def test_include_parameters_actually_restores_parameters_rows(tmp_path):
    # Regression test: get_calculated_fields(include_parameters=True) must
    # be able to surface rows from the "Parameters" datasource. It can only
    # do that if the parser cached the *unfiltered* extraction at
    # construction time -- caching with the extractor's own
    # include_parameters=False default would drop those rows permanently
    # and make the flag a no-op.
    twb = tmp_path / "params.twb"
    twb.write_text(_PARAMS_CALC_XML)
    p = TwbParser(str(twb))

    default = p.get_calculated_fields()
    assert len(default) == 1
    assert "Parameters" not in default["datasource"].values

    with_params = p.get_calculated_fields(include_parameters=True)
    assert len(with_params) == 2
    assert "Parameters" in with_params["datasource"].values

    overview = p.get_overview()
    assert overview.iloc[0]["calculated_fields"] == 1


def test_include_parameters_with_real_param_domain_type_columns(tmp_path):
    # Real Parameters-datasource columns carry @param-domain-type; the flag
    # must surface them through TwbParser, not just synthetic ones without it.
    twb = tmp_path / "real_params.twb"
    twb.write_text(REAL_PARAMS_XML)
    p = TwbParser(str(twb))

    assert list(p.get_calculated_fields()["datasource"]) == ["Orders"]
    with_params = p.get_calculated_fields(include_parameters=True)
    assert (with_params["datasource"] == "Parameters").sum() == 2
