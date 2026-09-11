from twbparser_py import extract_datasource_details, extract_named_connections


def test_extract_named_connections(wenjie_xml):
    conns = extract_named_connections(wenjie_xml)
    assert not conns.empty
    assert "connection_class" in conns.columns


def test_extract_datasource_details(wenjie_xml):
    res = extract_datasource_details(wenjie_xml)
    assert set(res.keys()) == {"data_sources", "parameters", "all_sources"}
    ds = res["data_sources"]
    assert not ds.empty
    assert "Municipal_Boundaries_of_NJ" in ds["datasource"].values
