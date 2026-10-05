"""Connection targets: a table in a database, described by a file, as the data of a template."""

import copy
import importlib.util
import json
import shutil
import warnings
import zipfile
from pathlib import Path

import pytest
from lxml import etree

import py_tbparse.templates as templates
from py_tbparse import TemplateError, apply_template, load_template, make_template, suggest_mapping
from py_tbparse import connections
from py_tbparse.cli import main
from py_tbparse.connections import CLASSES, ConnClass, connection_attributes, load_target, relation_table, remote_type
from py_tbparse.template_batch import apply_template_folder
from py_tbparse.templates import _db_connection, read_answers, read_data
from schema_check import twb_bytes
from test_schema import introduced

PUBLIC = Path(__file__).parent / "fixtures" / "public"
CORPUS = Path(__file__).parent / "corpus" / "files"
corpus = pytest.mark.skipif(not CORPUS.is_dir() or not any(CORPUS.glob("*.twb")),
                            reason="corpus not fetched: python scripts/fetch_corpus.py")

COLUMNS = [{"name": "Category", "type": "varchar(80)"}, {"name": "Number of Records", "type": "bigint"},
           {"name": "Order Date", "type": "date"}, {"name": "Sales Target", "type": "numeric(12,2)"},
           {"name": "Segment", "type": "varchar(20)"}, {"name": "Paid", "type": "boolean"},
           {"name": "Shipped", "type": "timestamp"}]
BASE = {"format": "py-tbparse-target", "version": 1, "columns": COLUMNS, "server": "db.example.com", "dbname": "sales",
        "table": "orders"}
TARGETS = {
    "mysql": {**BASE, "class": "mysql"},
    "postgres": {**BASE, "class": "postgres", "schema": "public", "port": 5432},
    "sqlserver": {**BASE, "class": "sqlserver", "schema": "dbo"},
    "snowflake": {**BASE, "class": "snowflake", "schema": "PUBLIC", "warehouse": "COMPUTE_WH"},
}


def write_target(path, **changes):
    body = copy.deepcopy(TARGETS[changes.pop("cls", "postgres")])
    for key, value in changes.items():
        if value is None:
            body.pop(key, None)
        else:
            body[key] = value
    Path(path).write_text(json.dumps(body), encoding="utf-8")
    return str(path)


def target_of(tmp_path, cls="postgres", name="orders.target.json", **changes):
    return write_target(tmp_path / name, cls=cls, **changes)


# --- the registry is the corpus -------------------------------------------------------------------------------


def _survey():
    spec = importlib.util.spec_from_file_location("survey_connections", Path(__file__).parent.parent / "scripts" / "survey_connections.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.survey(CORPUS)


@corpus
def test_the_registry_says_what_the_corpus_says():
    seen = _survey()
    assert set(CLASSES) == set(seen)
    for name, conn in CLASSES.items():
        found = seen[name]
        # the attributes Tableau wrote: ours are exactly those, without the username
        corpus_attrs = set(found["attributes"]) - {"username"}
        assert set(conn.attributes) <= corpus_attrs, (name, set(conn.attributes) - corpus_attrs)
        assert corpus_attrs - set(conn.attributes) <= {"port"} if name == "sqlserver" else corpus_attrs == set(conn.attributes), name
        assert conn.evidence == "corpus"
        assert set(found["attributes"].get("authentication", {})) == set(conn.authentication) if conn.authentication else \
            "authentication" not in found["attributes"]
        # every remote type we call measured was written by Tableau for that class, with those debug names
        written = {(remote, debug, wire) for (_local, remote, debug, wire, _agg) in found["types"]}
        for family, (code, debug, wire) in conn.types.items():
            assert (str(code), debug, wire) in written, (name, family)
        # a database relation has no <columns> child; the 4 in the corpus that do (2 workbooks, MySQL) carry only a
        # hand-set date-parse-format for two date columns, which a target cannot describe
        assert found["tables"]["no <columns> child"] > 5 * found["tables"].get("has <columns> child", 0)
        assert all(c.startswith("from") for c in found["ordinals"])


def test_a_class_with_documentation_only_evidence_refuses_unless_experimental(tmp_path, monkeypatch):
    monkeypatch.setitem(CLASSES, "oracle", ConnClass("oracle", "docs", default_port="1521", attributes={"class": "oracle", "server": "$server"},
                                                     schema="required"))
    path = target_of(tmp_path, **{"class": "oracle"})
    with pytest.raises(TemplateError, match=r"class oracle is written from documentation only.*experimental"):
        load_target(path)
    assert load_target(path, experimental=True)["class"] == "oracle"


# --- target files ---------------------------------------------------------------------------------------------


def test_a_good_target_is_loaded_with_tableau_types_and_a_note_of_what_is_unverified(tmp_path):
    t = load_target(target_of(tmp_path))
    assert [(c["name"], c["datatype"]) for c in t["columns"]] == [
        ("Category", "string"), ("Number of Records", "integer"), ("Order Date", "date"), ("Sales Target", "real"),
        ("Segment", "string"), ("Paid", "boolean"), ("Shipped", "datetime")]
    assert t["port"] == "5432" and t["warnings"] == []
    # postgres: varchar(measured), bigint, date, numeric, boolean, timestamp are measured; nothing here is borrowed
    assert t["unverified_types"] == []
    assert load_target(target_of(tmp_path, "mysql"))["unverified_types"] == ["bigint", "boolean", "timestamp"]


def test_reading_a_target_warns_about_unverified_types_and_unknown_ones(tmp_path):
    path = target_of(tmp_path, "mysql", columns=[{"name": "a", "type": "json"}, {"name": "b", "type": "boolean"}])
    with pytest.warns(UserWarning) as caught:
        data = read_data(path)
    texts = " | ".join(str(w.message) for w in caught)
    assert "column a: type 'json' has no Tableau type" in texts and "boolean" in texts and "not opened in Tableau" in texts
    assert data.kind == "db" and data.names() == ["a", "b"] and data.datatype("a") == "string"
    assert data.fields[1]["sql_type"] == "boolean"


@pytest.mark.parametrize("changes,message", [
    ({"format": "something"}, "is not a target file"),
    ({"format": None}, "is not a target file"),
    ({"class": "oracle"}, r"unknown class 'oracle'; known classes: mysql, postgres, snowflake, sqlserver"),
    ({"class": None}, "unknown class None"),
    ({"table": None}, 'needs "table"'),
    ({"server": ""}, 'needs "server"'),
    ({"dbname": None}, 'needs "dbname"'),
    ({"schema": None}, 'needs "schema"'),
    ({"columns": None}, "either as .columns. or as .schema_file."),
    ({"schema_file": "x.sql"}, "not both or neither"),
    ({"port": "abc"}, "port must be a number"),
    ({"authentication": "kerberos"}, "authentication 'kerberos' was not seen for class postgres"),
    ({"colums": []}, "unknown key.*colums"),
    ({"password": "hunter2"}, r"must not hold credentials, but has 'password'"),
    ({"username": "sa"}, r"must not hold credentials, but has 'username'"),
    ({"version": 9}, "newer py-tbparse"),
])
def test_a_bad_target_is_refused_naming_the_problem(tmp_path, changes, message):
    path = target_of(tmp_path, **changes)
    with pytest.raises(TemplateError, match=message):
        load_target(path)


def test_class_specific_rules(tmp_path):
    with pytest.raises(TemplateError, match="class mysql has no schema"):
        load_target(target_of(tmp_path, "mysql", schema="x"))
    with pytest.raises(TemplateError, match='class snowflake needs "warehouse"'):
        load_target(target_of(tmp_path, "snowflake", warehouse=None))
    with pytest.raises(TemplateError, match="class postgres has no warehouse"):
        load_target(target_of(tmp_path, warehouse="w"))
    with pytest.raises(TemplateError, match="no port for class sqlserver"):
        load_target(target_of(tmp_path, "sqlserver", port=1433))
    with pytest.raises(TemplateError, match="authentication 'x' was not seen for class sqlserver"):
        load_target(target_of(tmp_path, "sqlserver", authentication="x"))
    assert load_target(target_of(tmp_path, "sqlserver", authentication="x"), experimental=True)["authentication"] == "x"


def test_a_credential_nested_anywhere_is_refused(tmp_path):
    path = target_of(tmp_path, columns=[{"name": "a", "type": "int", "token": "t"}])
    with pytest.raises(TemplateError, match="credentials"):
        load_target(path)


def test_invalid_json_and_a_plain_json_file_are_refused(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{nope", encoding="utf-8")
    with pytest.raises(TemplateError, match="not valid JSON"):
        load_target(str(bad))
    other = tmp_path / "other.json"
    other.write_text('{"a": 1}', encoding="utf-8")
    with pytest.raises(TemplateError, match="not a target file"):
        read_data(str(other))
    assert not connections.is_target_file(str(other)) and not connections.is_target_file(str(bad))


def test_columns_can_come_from_a_schema_file_next_to_the_target(tmp_path):
    (tmp_path / "ddl").mkdir()
    (tmp_path / "ddl" / "orders.sql").write_text("create table orders (id bigint not null, name varchar(10));", encoding="utf-8")
    path = target_of(tmp_path, columns=None, schema_file="ddl/orders.sql")
    t = load_target(path)
    assert [(c["name"], c["type"]) for c in t["columns"]] == [("id", "bigint"), ("name", "varchar(10)")]
    (tmp_path / "cols.json").write_text(json.dumps([{"name": "x", "type": "int"}]), encoding="utf-8")
    assert load_target(target_of(tmp_path, columns=None, schema_file="cols.json"))["columns"][0]["name"] == "x"
    with pytest.raises(FileNotFoundError):
        load_target(target_of(tmp_path, columns=None, schema_file="missing.sql"))
    (tmp_path / "bad.sql").write_text("create table a (x int); create table b (y int);", encoding="utf-8")
    with pytest.raises(TemplateError, match="bad.sql: line 1.*one table"):
        load_target(target_of(tmp_path, columns=None, schema_file="bad.sql"))


# --- the connection ---------------------------------------------------------------------------------------


def _data(tmp_path, cls="postgres"):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return read_data(target_of(tmp_path, cls))


def _locals(data):
    return {f["name"]: f"[{f['name']}]" for f in data.fields}


EXPECTED_ATTRS = {
    "mysql": {"class": "mysql", "dbname": "sales", "odbc-native-protocol": "", "one-time-sql": "", "port": "3306",
              "server": "db.example.com", "source-charset": ""},
    "postgres": {"authentication": "username-password", "class": "postgres", "dbname": "sales", "one-time-sql": "",
                 "port": "5432", "server": "db.example.com"},
    "sqlserver": {"authentication": "sspi", "class": "sqlserver", "dbname": "sales", "odbc-native-protocol": "yes",
                  "one-time-sql": "", "server": "db.example.com"},
    "snowflake": {"authentication": "Username Password", "class": "snowflake", "dbname": "sales", "max-varchar-size": "",
                  "odbc-connect-string-extras": "", "one-time-sql": "", "schema": "PUBLIC", "server": "db.example.com",
                  "service": "", "warehouse": "COMPUTE_WH"},
}
EXPECTED_TABLE = {"mysql": "[orders]", "postgres": "[public].[orders]", "sqlserver": "[dbo].[orders]",
                  "snowflake": "[sales].[PUBLIC].[orders]"}      # Snowflake names the database in the relation too


@pytest.mark.parametrize("cls", sorted(EXPECTED_ATTRS))
def test_the_connection_has_the_shape_tableau_writes(tmp_path, cls):
    data = _data(tmp_path, cls)
    conn, extras = _db_connection(data, _locals(data), model=None)
    assert extras == []
    named = conn.find("named-connections/named-connection")
    assert named.get("caption") == "db.example.com" and named.get("name").startswith(f"{cls}.")
    inner = named.find("connection")
    assert dict(inner.attrib) == EXPECTED_ATTRS[cls] and list(inner.attrib) == sorted(EXPECTED_ATTRS[cls])
    assert "username" not in inner.attrib and "password" not in inner.attrib
    rel = conn.find("relation")
    assert (rel.get("name"), rel.get("table"), rel.get("type"), rel.get("connection")) == (
        "orders", EXPECTED_TABLE[cls], "table", named.get("name"))
    assert rel.find("columns") is None                       # a database relation has none
    records = conn.findall("metadata-records/metadata-record")
    assert [r.findtext("ordinal") for r in records] == [str(i) for i in range(1, 8)]
    assert [r.findtext("remote-name") for r in records] == [c["name"] for c in COLUMNS]
    for r in records:
        assert r.findtext("parent-name") == "[orders]" and r.findtext("contains-null") == "true"
        assert [c.tag for c in r][:9] == ["remote-name", "remote-type", "local-name", "parent-name", "remote-alias",
                                          "ordinal", "local-type", "aggregation", "contains-null"]


def test_remote_types_and_debug_attributes_follow_the_class(tmp_path):
    def rec(cls):
        data = _data(tmp_path, cls)
        conn, _ = _db_connection(data, _locals(data), model=None)
        out = {}
        for r in conn.findall("metadata-records/metadata-record"):
            attrs = {a.get("name"): a.text for a in r.findall("attributes/attribute")}
            out[r.findtext("remote-name")] = (r.findtext("remote-type"), r.findtext("local-type"),
                                              r.findtext("aggregation"), attrs.get("DebugRemoteType"), attrs.get("DebugWireType"))
        return out
    pg, ms = rec("postgres"), rec("sqlserver")
    assert pg["Category"] == ("129", "string", "Count", None, None)            # postgres writes no debug attributes
    assert pg["Number of Records"] == ("20", "integer", "Sum", None, None)
    assert pg["Sales Target"] == ("131", "real", "Sum", None, None)
    assert pg["Order Date"] == ("7", "date", "Year", None, None) and pg["Shipped"] == ("135", "datetime", "Year", None, None)
    assert pg["Paid"] == ("11", "boolean", "Count", None, None)
    assert ms["Category"] == ("130", "string", "Count", '"SQL_WVARCHAR"', '"SQL_C_WCHAR"')
    assert ms["Number of Records"] == ("20", "integer", "Sum", '"SQL_BIGINT"', '"SQL_C_SBIGINT"')
    assert ms["Shipped"] == ("7", "datetime", "Year", '"SQL_TYPE_TIMESTAMP"', '"SQL_C_TYPE_TIMESTAMP"')
    sf = rec("snowflake")
    assert sf["Category"] == ("129", "string", "Count", '"SQL_VARCHAR"', '"SQL_C_CHAR"')
    assert sf["Number of Records"][:3] == ("131", "integer", "Sum")      # a whole NUMBER is DECIMAL 131 and an integer


@pytest.mark.parametrize("model", ["prefixed", "plain"])
def test_the_object_model_forms_match_the_file_ones(tmp_path, model):
    data = _data(tmp_path)
    conn, extras = _db_connection(data, _locals(data), model=model, object_id="orders_ID")
    table_col, graph = extras
    assert table_col.get("name") == "[__tableau_internal_object_id__].[orders_ID]"
    assert table_col.get("caption") == "orders" and table_col.get("datatype") == "table"
    assert graph.find("objects/object").get("id") == "orders_ID"
    inner = graph.find("objects/object/properties/relation")
    assert inner.get("table") == "[public].[orders]" and inner.find("columns") is None
    relations = [e for e in conn if e.tag.endswith("relation")]
    assert len(relations) == (2 if model == "prefixed" else 1)
    assert [e.text for e in conn.iter() if e.tag.endswith("object-id")] == ["[orders_ID]"] * 7


def test_a_bracket_in_a_name_is_doubled_and_the_connection_id_depends_on_the_whole_target(tmp_path):
    assert relation_table("postgres", {"schema": "a]b", "table": "t[x]"}) == "[a]]b].[t[x]]]"
    a = _data(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    b = read_data(write_target(other / "t.json", dbname="other"))
    ca = _db_connection(a, _locals(a), model=None)[0].find("named-connections/named-connection").get("name")
    cb = _db_connection(b, _locals(b), model=None)[0].find("named-connections/named-connection").get("name")
    assert ca != cb and len(ca.split(".")[1]) == 28


def test_remote_type_says_which_codes_are_borrowed():
    assert remote_type("postgres", "bigint")[0].measured and not remote_type("postgres", "real")[0].measured
    assert remote_type("mysql", "varchar(3)")[0].remote == 130 and remote_type("snowflake", "varchar")[0].remote == 129
    borrowed = remote_type("postgres", "real")[0]
    assert (borrowed.remote, borrowed.debug) == (4, "")           # from mysql, without a debug name postgres never writes
    assert remote_type("sqlserver", "int")[0].debug == "SQL_INTEGER"
    for cls in CLASSES:                                           # every family resolves for every class
        for sql in ("tinyint", "smallint", "int", "bigint", "numeric(9,0)", "numeric(9,2)", "real", "double", "char(2)",
                    "text", "date", "timestamp", "bool", "json"):
            assert remote_type(cls, sql)[0].remote > 0


def test_connection_attributes_never_include_a_secret(tmp_path):
    for cls in CLASSES:
        attrs = connection_attributes(load_target(target_of(tmp_path, cls)))
        assert not {"username", "password"} & set(attrs)


# --- applying ---------------------------------------------------------------------------------------------


@pytest.fixture
def cache_template(tmp_path, monkeypatch):
    monkeypatch.setattr(templates, "_now", lambda: "2026-10-02T00:00:00+00:00")
    book = tmp_path / "Cache.twbx"
    shutil.copy(PUBLIC / "Cache.twbx", book)
    return load_template(make_template(str(book), output_path=str(tmp_path / "cache.template.twbx"), template_id="tpl-1"))


def _twb(path):
    z = zipfile.ZipFile(path)
    return z.read(next(n for n in z.namelist() if n.endswith(".twb")))


@pytest.mark.filterwarnings("ignore::UserWarning")
def test_a_template_applies_to_a_target_and_the_answers_keep_it(cache_template, tmp_path):
    target = target_of(tmp_path)
    entry = cache_template.manifest["datasources"][0]["name"]
    report: dict = {}
    out = apply_template(cache_template, target, datasource=entry, allow_missing=True, report=report,
                         output_path=str(tmp_path / "out.twbx"))
    doc = etree.fromstring(_twb(out))
    assert doc.xpath("//datasource[@name=$n]//connection[@class='postgres']", n=entry)
    assert doc.xpath("//relation[@table='[public].[orders]']")
    assert not doc.xpath("//connection[@username or @password]")
    assert b"hunter2" not in _twb(out) and report["unverified_types"] == []
    answers = read_answers(out)
    assert answers["data"]["kind"] == "db" and answers["data"]["file"] == str(Path(target).resolve())
    assert answers["data"]["columns"] == [c["name"] for c in COLUMNS]
    assert "username" not in json.dumps(answers) and "password" not in json.dumps(answers)
    again = apply_template(cache_template, answers=out, allow_missing=True, output_path=str(tmp_path / "again.twbx"))
    assert _twb(out) == _twb(again)                                 # --answers repeats the run byte for byte


@pytest.mark.filterwarnings("ignore::UserWarning")
def test_mapping_works_on_a_targets_columns_like_on_a_csv(cache_template, tmp_path):
    data = read_data(target_of(tmp_path))
    row = suggest_mapping(cache_template, data).set_index("field")
    assert row.loc["[Category]", "mapped_to"] == "Category" and row.loc["[Order Date]", "mapped_to"] == "Order Date"


@pytest.mark.filterwarnings("ignore::UserWarning")
def test_a_changed_column_list_shows_in_the_fingerprint(tmp_path):
    a = read_data(target_of(tmp_path))
    b = read_data(target_of(tmp_path, name="b.target.json", columns=COLUMNS[:-1]))
    assert a.fingerprint() != b.fingerprint()
    c = read_data(target_of(tmp_path, name="c.target.json", dbname="elsewhere"))
    assert a.fingerprint() == c.fingerprint()          # same table shape on another database: the mapping carries over


@pytest.mark.filterwarnings("ignore::UserWarning")
def test_check_data_says_it_cannot_read_values_of_a_database(cache_template, tmp_path):
    data = read_data(target_of(tmp_path))
    found = templates.check_data(cache_template, data, suggest_mapping(cache_template, data))
    assert "values-not-read" in set(found["check"])
    assert "not read" in found[found["check"] == "values-not-read"].iloc[0]["detail"]


@pytest.mark.filterwarnings("ignore::UserWarning")
def test_the_command_line_applies_a_target(cache_template, tmp_path, capsys):
    target = target_of(tmp_path)
    assert main(["template", "apply", cache_template.path, "--data", target]) == 0
    assert "Category" in capsys.readouterr().out
    out = tmp_path / "cli.twbx"
    assert main(["template", "apply", cache_template.path, "--data", target, "--allow-missing", "--write", str(out)]) == 0
    assert out.exists() and b"class='postgres'" in _twb(str(out)) or b'class="postgres"' in _twb(str(out))
    assert main(["template", "apply", cache_template.path, "--data", target_of(tmp_path, password="x", name="p.target.json")]) == 1
    assert "credentials" in capsys.readouterr().err


@pytest.mark.filterwarnings("ignore::UserWarning")
def test_experimental_reaches_the_loader(cache_template, tmp_path, monkeypatch, capsys):
    monkeypatch.setitem(CLASSES, "oracle", ConnClass("oracle", "docs", default_port="1521", attributes={"class": "oracle"}, schema="required"))
    path = target_of(tmp_path, **{"class": "oracle"})
    assert main(["template", "apply", cache_template.path, "--data", path]) == 1
    assert "experimental" in capsys.readouterr().err
    assert main(["template", "apply", cache_template.path, "--data", path, "--experimental"]) == 0


# --- many customers, one database ---------------------------------------------------------------------------


@pytest.mark.filterwarnings("ignore::UserWarning")
def test_apply_folder_takes_target_files_and_only_real_ones(cache_template, tmp_path):
    folder = tmp_path / "customers"
    folder.mkdir()
    for customer in ("acme", "globex"):
        write_target(folder / f"{customer}.target.json", dbname=f"cust_{customer}")
    (folder / "settings.target.json").write_text('{"just": "settings"}', encoding="utf-8")   # named a target: reported
    (folder / "other.json").write_text("{}", encoding="utf-8")                                # any other json: ignored
    table = apply_template_folder(cache_template, str(folder), output_dir=str(tmp_path / "out"),
                                  min_mapped=0.0, overwrite=True)
    assert sorted(table["input"]) == ["acme.target.json", "globex.target.json", "settings.target.json"]
    assert dict(zip(table["input"], table["status"])) == {"acme.target.json": "ok", "globex.target.json": "ok",
                                                          "settings.target.json": "error"}
    table = table[table["status"] == "ok"]
    assert sorted(table["output"]) == ["cache_acme.twbx", "cache_globex.twbx"]
    docs = {n: etree.fromstring(_twb(tmp_path / "out" / f"cache_{n}.twbx")) for n in ("acme", "globex")}
    for n, doc in docs.items():
        assert doc.xpath("//named-connection/connection[@dbname=$d]", d=f"cust_{n}")
    ids = {n: doc.xpath("//named-connection/@name")[0] for n, doc in docs.items()}
    assert ids["acme"] != ids["globex"]


# --- against Tableau's own output ---------------------------------------------------------------------------

_SQL_FOR = {"mysql": {(16, "SQL_TINYINT"): "tinyint", (18, "SQL_SMALLINT"): "smallint", (3, "SQL_INTEGER"): "int",
                      (131, "SQL_DECIMAL"): "numeric(9,2)", (131, "SQL_DECIMAL", "whole"): "numeric(9,0)",
                      (4, "SQL_REAL"): "real", (5, "SQL_DOUBLE"): "double", (130, "SQL_WVARCHAR"): "varchar(10)", (129, "SQL_LONGVARCHAR"): "text",
                      (7, "SQL_TYPE_DATE"): "date"},
            "postgres": {(3, ""): "int", (20, ""): "bigint", (129, ""): "varchar(10)", (131, ""): "numeric(9,2)",
                         (131, "", "whole"): "numeric(9,0)", (7, ""): "date", (135, ""): "timestamp", (11, ""): "boolean"},
            "sqlserver": {(130, "SQL_WVARCHAR"): "varchar(10)", (20, "SQL_BIGINT"): "bigint",
                          (7, "SQL_TYPE_TIMESTAMP"): "datetime2", (4, "SQL_REAL"): "real"},
            "snowflake": {(131, "SQL_DECIMAL", "whole"): "numeric(38,0)", (131, "SQL_DECIMAL"): "numeric(38,6)", (129, "SQL_VARCHAR"): "varchar(10)",
                          (7, "SQL_TYPE_DATE"): "date", (5, "SQL_DOUBLE"): "double",
                          (7, "SQL_TYPE_TIMESTAMP"): "timestamp"}}


# DECIMAL (131) is an integer when it has no decimals and a real otherwise: the local type tells which
_DECIMALS = {(131, "SQL_DECIMAL"): {"integer": (131, "SQL_DECIMAL", "whole"), "real": (131, "SQL_DECIMAL")},
             (131, ""): {"integer": (131, "", "whole"), "real": (131, "")}}


def _own_tables():
    """(workbook, datasource element, class, named-connection element, table relation, records, SQL-type keys) for
    every table of the four classes in the corpus (one named connection per datasource) whose columns all have a type
    we can describe in SQL; each table is compared on its own, by the `parent-name` of its metadata records."""
    found = []
    for path in sorted(CORPUS.glob("*.twb")):
        try:
            root = etree.parse(str(path)).getroot()
        except etree.XMLSyntaxError:
            continue
        for ds in root.xpath("//datasource[connection[@class='federated']]"):
            named = ds.xpath("./connection/named-connections/named-connection")
            if len(named) != 1 or named[0].find("connection").get("class") not in CLASSES:
                continue
            cls = named[0].find("connection").get("class")
            rels = sorted({(r.get("name"), r.get("table")) for r in ds.xpath(
                "./connection//*[local-name()='relation' or substring(name(), string-length(name()) - 10) = '...relation']"
                "[@type='table']")})
            all_records = ds.xpath("./connection/metadata-records/metadata-record[@class='column']")
            for rel in rels:
                if rel[1][1:-1].split("].[")[-1].replace("]]", "]") != rel[0]:
                    continue   # the same table added twice: Tableau suffixes the relation's name (finanzas1)
                records = [r for r in all_records if r.findtext("parent-name") == f"[{rel[0]}]"]
                keys = []
                for r in records:
                    attrs = {a.get("name"): (a.text or "").strip('"') for a in r.xpath("./attributes/attribute")}
                    code, debug = int(r.findtext("remote-type")), attrs.get("DebugRemoteType", "")
                    keys.append((code, debug) if (code, debug) not in _DECIMALS else _DECIMALS[(code, debug)][r.findtext("local-type")])
                if records and all(k in _SQL_FOR[cls] for k in keys):
                    found.append((path, ds, cls, named[0], rel, records, keys))
    return found


def _normal_record(r, cls):
    attrs = {a.get("name"): (a.text or "").strip('"') for a in r.xpath("./attributes/attribute")}
    return (r.findtext("remote-name"), r.findtext("remote-type"), r.findtext("local-type"), r.findtext("aggregation"),
            r.findtext("parent-name"), attrs.get("DebugRemoteType", ""), attrs.get("DebugWireType", ""))


@corpus
def test_our_connection_matches_the_one_tableau_wrote_for_the_same_table(tmp_path):
    cases = _own_tables()
    assert len({c[2] for c in cases}) >= 2, "the corpus should give us at least two classes to compare with"
    compared = 0
    for n, (path, ds, cls, named, (table_name, table), records, keys) in enumerate(cases):
        inner = named.find("connection")
        parts = [p.replace("]]", "]") for p in table[1:-1].split("].[")]
        target = {"format": "py-tbparse-target", "class": cls, "server": inner.get("server"), "dbname": inner.get("dbname"),
                  "table": table_name,
                  "columns": [{"name": r.findtext("remote-name"), "type": _SQL_FOR[cls][k]} for r, k in zip(records, keys)]}
        if len(parts) >= 2:
            target["schema"] = parts[-2]
        if cls == "snowflake":
            assert parts[0] == inner.get("dbname") and parts[1] == inner.get("schema")   # the three parts, as measured
            target["warehouse"] = inner.get("warehouse") or "W"
        if inner.get("port"):
            target["port"] = inner.get("port")
        if inner.get("authentication"):
            target["authentication"] = inner.get("authentication")
        t = tmp_path / f"t{n}.json"
        t.write_text(json.dumps(target), encoding="utf-8")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            data = read_data(str(t))
        local_of = {r.findtext("remote-name"): r.findtext("local-name") for r in records}
        ours, _ = _db_connection(data, local_of, model=None)
        mine = ours.find("named-connections/named-connection/connection")
        expected = {k: v for k, v in inner.attrib.items() if k != "username"}
        # attributes Tableau wrote for this class and we also write must agree, and ours add nothing it did not write
        assert set(mine.attrib) - set(expected) <= {"max-varchar-size", "odbc-connect-string-extras", "one-time-sql",
                                                    "service", "source-charset", "odbc-native-protocol", "port"}, path.name
        for key in set(mine.attrib) & set(expected):
            assert mine.get(key) == expected[key], (path.name, key)
        rel = ours.find("relation")
        assert rel.get("table") == table and rel.get("name") == table_name and rel.find("columns") is None, path.name
        ours_records = [_normal_record(r, cls) for r in ours.findall("metadata-records/metadata-record")]
        theirs = [_normal_record(r, cls) for r in records]
        for (name, code, local, agg, parent, debug, wire), (name2, code2, local2, agg2, parent2, debug2, wire2) in zip(theirs, ours_records):
            assert (name, code, local, agg, parent) == (name2, code2, local2, agg2, parent2), (path.name, name)
            assert (debug, wire) == (debug2, wire2), (path.name, name)
        compared += 1
    assert compared >= 15 and {c[2] for c in cases} == set(CLASSES)


# --- the whole corpus -----------------------------------------------------------------------------------------

_SQL_OF = {"integer": "bigint", "real": "double", "string": "varchar(255)", "date": "date", "datetime": "timestamp",
           "boolean": "boolean"}


@corpus
def test_targets_add_no_schema_or_reference_errors_on_the_corpus(tmp_path):
    problems, classes = [], set()
    for n, book in enumerate(sorted(CORPUS.glob("*.twb"))):
        work = tmp_path / f"w{n}"
        work.mkdir()
        copy_of = work / "book.twb"
        shutil.copy(book, copy_of)
        template = load_template(make_template(str(copy_of)))
        entry = next((e for e in template.manifest["datasources"] if e["fields"]), None)
        if entry is None:
            shutil.rmtree(work)
            continue
        cls = sorted(CLASSES)[n % len(CLASSES)]            # every class gets about a quarter of the workbooks
        classes.add(cls)
        body = copy.deepcopy(TARGETS[cls])
        seen, columns = set(), []
        for f in entry["fields"]:
            if f["remote"] not in seen:
                seen.add(f["remote"])
                columns.append({"name": f["remote"], "type": _SQL_OF.get(f["datatype"], "varchar(255)")})
        body["columns"] = columns
        target = work / "t.target.json"
        target.write_text(json.dumps(body), encoding="utf-8")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            data = read_data(str(target))
            unfed = set(suggest_mapping(template, data, datasource=entry["name"]).query("mapped_to == ''")["field"])
            out = apply_template(template, data, datasource=entry["name"], allow_missing=True,
                                 output_path=str(work / "out.twbx"))
        schema, refs = introduced(copy_of, work, f"apply-db-{cls}", twb_bytes(out), unfed)
        if schema or refs:
            problems.append((book.name, cls, schema[:2], refs[:2]))
        shutil.rmtree(work)
    assert problems == [] and classes == set(CLASSES)


# --- the command line -----------------------------------------------------------------------------------------


def test_targets_lists_the_classes_and_how_well_each_is_known(capsys):
    assert main(["template", "targets"]) == 0
    captured = capsys.readouterr()
    for cls in ("mysql", "postgres", "snowflake", "sqlserver"):
        assert cls in captured.out
    assert "corpus" in captured.out and "No target file has been opened in Tableau" in captured.err


def test_target_make_writes_a_checked_file_from_columns_or_a_schema_file(tmp_path, capsys):
    out = tmp_path / "t" / "a.target.json"
    assert main(["template", "target-make", "--class", "postgres", "--server", "h", "--dbname", "d", "--schema", "public",
                 "--table", "orders", "-c", "id:bigint", "-c", "name: varchar(5)", "-o", str(out)]) == 0
    body = json.loads(out.read_text(encoding="utf-8"))
    assert body["columns"] == [{"name": "id", "type": "bigint"}, {"name": "name", "type": "varchar(5)"}]
    assert "password" not in body and "username" not in body
    assert "not opened in Tableau" in capsys.readouterr().err
    assert main(["template", "target-make", "--class", "postgres", "--server", "h", "--dbname", "d", "--schema", "public",
                 "--table", "orders", "-c", "id:bigint", "-o", str(out)]) == 1                 # never overwrites
    assert "refusing to overwrite" in capsys.readouterr().err
    (tmp_path / "orders.sql").write_text("create table sales.orders (id int, at timestamp);", encoding="utf-8")
    other = tmp_path / "b.target.json"
    assert main(["template", "target-make", "--class", "mysql", "--server", "h", "--dbname", "d",
                 "--schema-file", str(tmp_path / "orders.sql"), "-o", str(other)]) == 0
    saved = json.loads(other.read_text(encoding="utf-8"))
    assert saved["table"] == "orders" and saved["schema_file"] == "orders.sql" and "columns" not in saved
    assert [c["name"] for c in load_target(str(other))["columns"]] == ["id", "at"]
    err = capsys.readouterr().err
    assert "timestamp" in err and "not seen in Tableau's own output for class mysql" in err


def test_target_make_removes_a_file_it_cannot_accept(tmp_path, capsys):
    out = tmp_path / "bad.target.json"
    assert main(["template", "target-make", "--class", "mysql", "--server", "h", "--dbname", "d", "--schema", "x",
                 "--table", "t", "-c", "a:int", "-o", str(out)]) == 1
    assert "class mysql has no schema" in capsys.readouterr().err and not out.exists()
    with pytest.raises(SystemExit):
        main(["template", "target-make", "--class", "mysql", "--server", "h", "--dbname", "d", "--table", "t",
              "-o", str(out)])                                                       # no columns at all
    assert not out.exists()


def test_target_make_column_splits_at_the_last_colon(tmp_path):
    out = tmp_path / "c.target.json"
    assert main(["template", "target-make", "--class", "postgres", "--server", "h", "--dbname", "d", "--schema", "public",
                 "--table", "t", "-c", "a:b:int", "-o", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["columns"] == [{"name": "a:b", "type": "int"}]


# --- review findings (#32) ---------------------------------------------------------------------------------------


def test_apply_folder_reports_a_truncated_target_json(cache_template, tmp_path):
    folder = tmp_path / "customers"
    folder.mkdir()
    write_target(folder / "acme.target.json", dbname="cust_acme")
    (folder / "cut.target.json").write_text('{"format": "py-tbparse-target", "cla', encoding="utf-8")
    table = apply_template_folder(cache_template, str(folder), output_dir=str(tmp_path / "out"),
                                  min_mapped=0.0, overwrite=True)
    rows = {r["input"]: r for r in table.to_dict("records")}
    assert rows["cut.target.json"]["status"] == "error" and "not valid JSON" in rows["cut.target.json"]["error"]
    assert rows["acme.target.json"]["status"] == "ok"


def test_apply_folder_reports_a_target_json_with_the_wrong_format_value(cache_template, tmp_path):
    folder = tmp_path / "customers"
    folder.mkdir()
    write_target(folder / "acme.target.json", dbname="cust_acme")
    write_target(folder / "bad.target.json", format="other")
    (folder / "plain.json").write_text('{"format": "other"}', encoding="utf-8")       # not *.target.json: still ignored
    table = apply_template_folder(cache_template, str(folder), output_dir=str(tmp_path / "out"),
                                  min_mapped=0.0, overwrite=True)
    rows = {r["input"]: r for r in table.to_dict("records")}
    assert sorted(rows) == ["acme.target.json", "bad.target.json"]
    assert rows["bad.target.json"]["status"] == "error" and "not a target file" in rows["bad.target.json"]["error"]
    assert rows["acme.target.json"]["status"] == "ok"


@pytest.mark.parametrize("changes", [{"server": "bob:hunter2@db.example.com"}, {"server": "postgres://bob:hunter2@h/db"},
                                     {"authentication": "bob:hunter2"}, {"table": "bob:hunter2@t"},
                                     {"warehouse": "bob:hunter2@w"}])
def test_credentials_in_values_are_refused(tmp_path, changes):
    cls = "snowflake" if "warehouse" in changes else "postgres"
    with pytest.raises(TemplateError, match="credentials") as e:
        load_target(target_of(tmp_path, cls, **changes), experimental=True)
    assert "hunter2" not in str(e.value)


def test_target_make_refuses_credentials_before_writing(tmp_path, capsys):
    out = tmp_path / "c.target.json"
    assert main(["template", "target-make", "--class", "postgres", "--server", "bob:hunter2@h", "--dbname", "d",
                 "--schema", "public", "--table", "t", "-c", "a:int", "-o", str(out)]) == 1
    err = capsys.readouterr().err
    assert "credentials" in err and "hunter2" not in err and not out.exists()


def test_an_experimental_authentication_value_must_look_like_a_name(tmp_path):
    assert load_target(target_of(tmp_path, "sqlserver", authentication="ntlm_v2"), experimental=True)
    with pytest.raises(TemplateError, match="authentication"):
        load_target(target_of(tmp_path, "sqlserver", authentication="a b;c"), experimental=True)


def test_parent_name_escapes_closing_bracket(tmp_path):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        data = read_data(target_of(tmp_path, table="we]ird"))
    conn = _db_connection(data, _locals(data), model=None)[0]
    parents = {p.text for p in conn.iter("parent-name")}
    assert parents == {"[we]]ird]"}
    assert relation_table("postgres", data.target).endswith(".[we]]ird]")


@pytest.mark.parametrize("changes", [{"version": "abc"}, {"version": None, "schema_file": 5, "columns": None},
                                     {"version": [1]}])
def test_bad_version_and_schema_file_types(tmp_path, changes):
    body = copy.deepcopy(TARGETS["postgres"])
    for k, v in changes.items():
        body.pop(k, None) if v is None else body.__setitem__(k, v)
    path = tmp_path / "v.target.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(TemplateError):
        load_target(str(path))


@pytest.mark.parametrize("port", ["0", 0, "65536", "٣٣٠٦", "-1", "12.5", "1e3", True, 123456])
def test_port_range_and_digits(tmp_path, port):
    with pytest.raises(TemplateError, match="port"):
        load_target(target_of(tmp_path, port=port))


def test_valid_ports_are_kept(tmp_path):
    assert load_target(target_of(tmp_path, port=65535))["port"] == "65535"
    assert load_target(target_of(tmp_path, port="1"))["port"] == "1"


@pytest.mark.parametrize("changes", [{"table": " orders"}, {"table": "orders "}, {"server": "db\nhost"},
                                     {"server": "db\x00host"}, {"dbname": "a\tb"}])
def test_spaces_around_a_table_and_control_characters_are_refused(tmp_path, changes):
    with pytest.raises(TemplateError):
        load_target(target_of(tmp_path, **changes))


def test_target_make_overwrite_keeps_old_file_when_validation_fails(tmp_path, capsys):
    out = tmp_path / "a.target.json"
    base = ["template", "target-make", "--class", "postgres", "--server", "h", "--dbname", "d", "--schema", "public",
            "--table", "t", "-c", "a:int", "-o", str(out)]
    assert main(base) == 0
    good = out.read_text(encoding="utf-8")
    capsys.readouterr()
    assert main(base + ["--overwrite", "--port", "99999"]) == 1
    assert out.read_text(encoding="utf-8") == good
    assert [p.name for p in tmp_path.iterdir()] == ["a.target.json"]                 # no temp file left behind
    assert main(base[:-2] + ["-c", "b:text", "-o", str(out), "--overwrite"]) == 0
    assert "b" in out.read_text(encoding="utf-8") and [p.name for p in tmp_path.iterdir()] == ["a.target.json"]
