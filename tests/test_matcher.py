"""suggest_mapping: spelling, caption and alias matching, roles, ties."""

from py_tbparse.templates import DataSource, Template, suggest_mapping


def template(*fields):
    """A template with one datasource and the given fields (dicts with at least `name`)."""
    base = {"caption": None, "remote": None, "alias": None, "datatype": "string", "physical_type": "string",
            "customized": False, "role": "dimension", "required": True, "used_by": ["Sheet 1"]}
    entry = {"name": "ds", "caption": "ds", "connections": [], "fields": [{**base, **f} for f in fields]}
    return Template(path="t.twbx", parser=None, manifest={"datasources": [entry]})


def csv(*columns):
    """CSV-like data: (name, datatype) pairs or bare names (strings)."""
    return DataSource(path="d.csv", kind="csv",
                      fields=[{"name": c, "datatype": "string"} if isinstance(c, str) else
                              {"name": c[0], "datatype": c[1]} for c in columns])


def mapped(t, d, **kw):
    return {r["field"]: (r["mapped_to"], r["status"]) for r in suggest_mapping(t, d, **kw).to_dict("records")}


def test_separators_and_case_do_not_matter():
    t = template({"name": "[customer-id]"}, {"name": "[Order Date]"}, {"name": "[ZipCode]"})
    got = mapped(t, csv("customer_id", "ORDER_DATE", "zip code"))
    assert got == {"[customer-id]": ("customer_id", "matched"), "[Order Date]": ("ORDER_DATE", "matched"),
                   "[ZipCode]": ("zip code", "matched")}


def test_a_field_is_found_by_its_caption_or_its_alias():
    t = template({"name": "[Calculation_1]", "caption": "Net Revenue"},
                 {"name": "[F2]", "alias": "Region Name"})
    got = mapped(t, csv("net-revenue", "REGION_NAME"))
    assert got["[Calculation_1]"] == ("net-revenue", "matched")
    assert got["[F2]"] == ("REGION_NAME", "matched")


def test_a_caption_is_tried_before_the_alias():
    t = template({"name": "[X]", "caption": "Sales", "alias": "Revenue"})
    assert mapped(t, csv("Revenue", "Sales"))["[X]"] == ("Sales", "matched")


def test_the_first_of_two_equally_close_columns_wins():
    t = template({"name": "[Customer Number]"})
    for columns in (("Customer Numbxr", "Customer Numbyr"), ("Customer Numbyr", "Customer Numbxr")):
        picked = mapped(t, csv(*columns))["[Customer Number]"]
        assert picked == (columns[0], "close match")


def test_the_same_data_always_gives_the_same_mapping():
    t = template({"name": "[Order Id]"}, {"name": "[Order Date]"}, {"name": "[Order Dat]"})
    d = csv("Order Idd", "Order Daate", "order id", "Order Dates")
    first = suggest_mapping(t, d).to_dict("records")
    assert all(suggest_mapping(t, d).to_dict("records") == first for _ in range(5))


def test_a_role_the_data_states_is_checked():
    t = template({"name": "[Sales]", "datatype": "real", "physical_type": "real", "role": "measure"},
                 {"name": "[Region]", "role": "dimension"})
    d = DataSource(path="d.twbx", kind="tableau", fields=[
        {"name": "Sales", "datatype": "real", "role": "dimension"},     # a measure in the template, a dimension here
        {"name": "Region", "datatype": "string", "role": "dimension"},
    ])
    got = mapped(t, d)
    assert got["[Sales]"] == ("Sales", "role differs") and got["[Region]"] == ("Region", "matched")


def test_a_csv_has_no_role_so_none_is_compared():
    t = template({"name": "[Sales]", "datatype": "real", "physical_type": "real", "role": "measure"})
    assert mapped(t, csv(("Sales", "real")))["[Sales]"] == ("Sales", "matched")


def test_a_type_problem_is_reported_before_a_role_problem():
    t = template({"name": "[Sales]", "datatype": "real", "physical_type": "real", "role": "measure"})
    d = DataSource(path="d.twbx", kind="tableau", fields=[{"name": "Sales", "datatype": "integer", "role": "dimension"}])
    assert mapped(t, d)["[Sales]"] == ("Sales", "numeric type differs")


def test_names_in_any_script_still_match():
    t = template({"name": "[顧客番号]"}, {"name": "[Größe]"})
    got = mapped(t, csv("顧客番号", "GRÖSSE"))
    assert got["[顧客番号]"][1] == "matched"
