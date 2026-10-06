"""A parameter used inside a calculation, bin or group is followed by `field_usage` (#78), and the custom SQL table
reads the `type='text'` relation Tableau writes for custom SQL. Real workbooks come from `tests/corpus`
(skipped when not fetched)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from conftest import xml_from_string
from py_tbparse import TwbParser, extract_custom_sql, field_usage

CORPUS = Path(__file__).parent / "corpus" / "files"


def corpus(name: str) -> TwbParser:
    path = CORPUS / name
    if not path.is_file():
        pytest.skip("corpus not fetched: python scripts/fetch_corpus.py")
    return TwbParser(str(path))


def row(df, field):
    return df[df["field"] == field].iloc[0]


BOOK = """<workbook><datasources>
  <datasource name='ds.1'>
    <connection class='federated'><metadata-records>
      <metadata-record class='column'><local-name>[Region]</local-name><local-type>string</local-type></metadata-record>
      <metadata-record class='column'><local-name>[Sales]</local-name><local-type>real</local-type></metadata-record>
    </metadata-records></connection>
    <column name='[Calc]' caption='Region Filter' datatype='boolean'>
      <calculation class='tableau' formula='[Region] = [Parameters].[Pick] and [Sales] &gt; [Parameters].[Floor]'/>
    </column>
    <column name='[Sales (bin)]' caption='Sales (bin)' datatype='integer'>
      <calculation class='bin' column='[Sales]' decimals='0' formula='bin([Sales], [Parameters].[Bin size])' peg='0' size-parameter='[Parameters].[Bin size]'/>
    </column>
    <group caption='Top' name='[Top]'>
      <groupfilter count='[Parameters].[Top N]' function='end' end='top' expression='SUM([Sales])'>
        <groupfilter function='level-members' level='[Region]'/>
      </groupfilter>
    </group>
  </datasource>
  <datasource name='Parameters' hasconnection='false'>
    <column name='[Pick]' datatype='string' param-domain-type='list' role='measure'><calculation class='tableau' formula='&quot;East&quot;'/></column>
    <column name='[Floor]' datatype='real' param-domain-type='range' role='measure'><calculation class='tableau' formula='0'/></column>
    <column name='[Bin size]' datatype='integer' param-domain-type='range' role='measure'><calculation class='tableau' formula='10'/></column>
    <column name='[Top N]' datatype='integer' param-domain-type='range' role='measure'><calculation class='tableau' formula='5'/></column>
    <column name='[Unused]' datatype='integer' param-domain-type='range' role='measure'><calculation class='tableau' formula='1'/></column>
  </datasource>
</datasources>
<worksheets><worksheet name='S'><table><view>
  <datasource-dependencies datasource='ds.1'><column name='[Calc]'/><column name='[Sales (bin)]'/><column name='[Top]'/></datasource-dependencies>
</view></table></worksheet></worksheets></workbook>"""


def test_a_parameter_is_followed_through_a_calculation_a_bin_and_a_group():
    df = field_usage(xml_from_string(BOOK))
    for name in ("[Pick]", "[Floor]", "[Bin size]", "[Top N]"):
        r = row(df, name)
        assert r["used"], name
        assert r["sheets"] == ["S"], name
    assert row(df, "[Pick]")["calculations"] == ["Region Filter"]
    assert row(df, "[Bin size]")["calculations"] == ["Sales (bin)"]
    assert row(df, "[Top N]")["calculations"] == ["Top"]
    assert not row(df, "[Unused]")["used"]


def test_the_field_next_to_a_parameter_is_not_swallowed_by_it():
    # the references `[Region] = [Parameters].[Pick]` were kept in a set, so `[Parameters]` could pair with the
    # wrong name and `[Region]` was lost
    df = field_usage(xml_from_string(BOOK))
    assert row(df, "[Region]")["used"]
    assert row(df, "[Sales]")["used"]


def test_real_workbook_region_filter_uses_its_parameter_and_its_field():
    df = corpus("PacktPublishing__Tableau-Creating-Interactive-Data-Visualizations__Chapter_9_-_Filters_and.twb"
                ).get_field_usage()
    parameter, field = row(df, "[Parameter 1]"), row(df, "[Region (Countries)]")
    assert parameter["used"] and field["used"]
    assert list(parameter["calculations"]) == ["Region Filter"] == list(field["calculations"])


def test_real_workbook_bin_size_and_top_n_parameters_are_followed():
    # a bin's size-parameter and a top-N group's count: no worksheet shows these, so they stay unused, but the
    # calculation that names them is now listed
    df = corpus("1230harry__TeamOne_MSc_Group_Project__Dumbbell.twb").get_field_usage()
    assert list(row(df, "[Parameter 1]")["calculations"]) == ["Top Customers by Profit"]
    assert list(row(df, "[Parameter 2]")["calculations"]) == ["Profit (bin)"]
    assert not row(df, "[Parameter 1]")["used"] and not row(df, "[Parameter 2]")["used"]


def test_real_workbook_parameter_through_a_chain_of_calculations():
    df = corpus("AbhinandanThatikonda__covid19-analysis-dashboard__Covid19-Tableau_dashboard.twb").get_field_usage()
    assert list(row(df, "[Parameter 1]")["calculations"]) == ["Calculation1", "Calculation2(Color)"]


def test_a_text_relation_is_custom_sql():
    xml = xml_from_string(
        "<workbook><connection>"
        "<relation connection='c' name='Custom SQL Query' type='text'>\n  select a from t\n</relation>"
        "<relation connection='c' name='Empty' type='text'/>"
        "<relation connection='c' name='Table' table='[t]' type='table'/>"
        "<relation name='by formula' type='table' formula='update t set a = 1'/>"
        "</connection><object-graph><relation connection='c' name='Custom SQL Query' type='text'>\n  select a from t\n</relation></object-graph>"
        "</workbook>")
    df = extract_custom_sql(xml)
    assert list(df["relation_name"]) == ["Custom SQL Query", "by formula"]
    first = df.iloc[0]
    assert first["custom_sql"] == "select a from t" and first["relation_type"] == "text" and first["is_custom_sql"]
    assert not df.iloc[1]["is_custom_sql"]


def test_real_workbook_custom_sql_table_lists_both_queries():
    df = corpus("Guust-Franssens__tableau-to-powerbi-migration__issue-166-custom-sql-disambiguation.twb"
                ).get_custom_sql()
    assert list(df["relation_name"]) == ["Custom SQL Query", "Custom SQL Query (Upgrade Aircraft Installs)"]
    assert df["is_custom_sql"].all() and (df["relation_type"] == "text").all()
    assert df.iloc[0]["custom_sql"] == "SELECT tail, technology, install_status FROM base_installs"


def test_the_audit_and_the_custom_sql_table_agree_over_the_corpus():
    from py_tbparse import audit

    files = sorted(CORPUS.glob("*.twb")) if CORPUS.is_dir() else []
    if not files:
        pytest.skip("corpus not fetched: python scripts/fetch_corpus.py")
    with_sql = 0
    for path in files:
        p = TwbParser(str(path))
        table = p.get_custom_sql()
        found = audit(p)
        a007 = found[found["rule"] == "A007"]
        distinct = len({(r.relation_name, r.custom_sql.strip()) for r in table.itertuples() if r.is_custom_sql})
        assert len(a007) == distinct, path.name
        with_sql += bool(distinct)
    assert with_sql == 1
