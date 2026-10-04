"""The SQL-type schema: type map, DDL subset, JSON column lists."""

import json

import pytest

from py_tbparse import TemplateError
from py_tbparse.schema import parse_ddl, read_schema, sql_family, sql_to_tableau_type

# --- the type map: every row of the table in docs/template-next-plan.md section 4.2 ---------------------------

INTEGER = ["smallint", "int", "integer", "tinyint", "mediumint", "bigint", "serial", "bigserial", "smallserial",
           "int2", "int4", "int8"]
REAL = ["decimal", "numeric", "number", "float", "double", "double precision", "real", "money", "smallmoney",
        "float4", "float8"]
STRING = ["char", "varchar", "nvarchar", "nchar", "text", "clob", "string", "longtext", "mediumtext", "tinytext",
          "citext", "uuid", "character", "character varying", "varchar2", "nvarchar2", "ntext", "nclob",
          "uniqueidentifier"]
DATETIME = ["timestamp", "datetime", "datetime2", "timestamptz", "timestamp_ntz", "timestamp_ltz", "timestamp_tz",
            "smalldatetime", "timestamp with time zone", "timestamp without time zone", "datetimeoffset"]


@pytest.mark.parametrize("sql", INTEGER)
def test_integer_types(sql):
    assert sql_to_tableau_type(sql) == "integer"


@pytest.mark.parametrize("sql", REAL)
def test_real_types(sql):
    assert sql_to_tableau_type(sql) == "real"


@pytest.mark.parametrize("sql", STRING)
def test_string_types(sql):
    assert sql_to_tableau_type(sql) == "string"


@pytest.mark.parametrize("sql", DATETIME)
def test_datetime_types(sql):
    assert sql_to_tableau_type(sql) == "datetime"


@pytest.mark.parametrize("sql", ["bool", "boolean", "bit"])
def test_boolean_types(sql):
    assert sql_to_tableau_type(sql) == "boolean"


def test_date_is_a_date():
    assert sql_to_tableau_type("date") == "date"


def test_case_whitespace_and_arguments_do_not_matter():
    assert sql_to_tableau_type("  VarChar ( 80 ) ") == "string"
    assert sql_to_tableau_type("NUMERIC(12,2)") == "real"
    assert sql_to_tableau_type("Timestamp(6)") == "datetime"
    assert sql_to_tableau_type("character   varying(20)") == "string"
    assert sql_to_tableau_type("int unsigned") == "integer"
    assert sql_to_tableau_type("bigint(20) unsigned zerofill") == "integer"


def test_a_decimal_with_no_decimals_is_an_integer():
    # Snowflake writes a whole NUMBER as DECIMAL (131), and Tableau calls it an integer (see the corpus survey)
    assert sql_to_tableau_type("numeric(10,0)") == "integer"
    assert sql_to_tableau_type("number(38, 0)") == "integer"
    assert sql_to_tableau_type("decimal(9)") == "integer"        # SQL's default scale is 0
    assert sql_to_tableau_type("number(12,2)") == "real"
    assert sql_to_tableau_type("number") == "real"
    assert sql_family("numeric(10,0)") == "wholenum" and sql_family("numeric(10,2)") == "decimal"


@pytest.mark.parametrize("sql", ["json", "jsonb", "blob", "geometry", "array", "variant", "time", "interval", "xml"])
def test_unknown_types_are_strings_with_a_warning(sql):
    warned = []
    assert sql_to_tableau_type(sql, warn=warned.append, column="payload") == "string"
    assert len(warned) == 1 and "payload" in warned[0] and sql in warned[0]


def test_known_types_do_not_warn():
    warned = []
    sql_to_tableau_type("int", warn=warned.append, column="a")
    assert warned == []


@pytest.mark.parametrize("sql,family", [
    ("tinyint", "tinyint"), ("smallint", "smallint"), ("int", "int"), ("bigint", "bigint"), ("real", "float4"),
    ("double precision", "double"), ("float", "double"), ("varchar(3)", "string"), ("longtext", "text"),
    ("date", "date"), ("timestamp", "datetime"), ("bool", "boolean"), ("json", "other")])
def test_families(sql, family):
    assert sql_family(sql) == family


# --- the DDL subset --------------------------------------------------------------------------------------------


def test_a_plain_create_table():
    table, columns = parse_ddl("""
        CREATE TABLE public.orders (
            order_id   bigint NOT NULL PRIMARY KEY,
            customer   varchar(80) DEFAULT 'n/a',
            ordered_at timestamp,
            amount     numeric(12,2) NOT NULL
        );
    """)
    assert table == "orders"
    assert columns == [{"name": "order_id", "type": "bigint"}, {"name": "customer", "type": "varchar(80)"},
                       {"name": "ordered_at", "type": "timestamp"}, {"name": "amount", "type": "numeric(12,2)"}]


def test_quoted_identifiers_comments_and_constraints():
    table, columns = parse_ddl('''
        -- the orders
        create table if not exists "My Orders" (   /* block
            comment, with a comma */
            "order id" int,          -- trailing, comment
            `unit price` decimal(10, 2) default 0,
            [Ship Date] date null,
            note double precision,
            PRIMARY KEY ("order id"),
            CONSTRAINT fk FOREIGN KEY (note) REFERENCES other(id),
            UNIQUE (note)
        )''')
    assert table == "My Orders"
    assert columns == [{"name": "order id", "type": "int"}, {"name": "unit price", "type": "decimal(10, 2)"},
                       {"name": "Ship Date", "type": "date"}, {"name": "note", "type": "double precision"}]


def test_composite_types_keep_their_words():
    _, columns = parse_ddl("CREATE TABLE t (a timestamp with time zone not null, b character varying(10), "
                           "c int unsigned auto_increment)")
    assert [c["type"] for c in columns] == ["timestamp with time zone", "character varying(10)", "int unsigned"]


def test_a_second_table_is_an_error():
    with pytest.raises(TemplateError, match="line 3.*one table"):
        parse_ddl("CREATE TABLE a (x int);\n\nCREATE TABLE b (y int);")


def test_no_table_is_an_error():
    with pytest.raises(TemplateError, match="no CREATE TABLE"):
        parse_ddl("SELECT 1;")


def test_a_syntax_it_does_not_know_names_the_line():
    with pytest.raises(TemplateError, match="line 3"):
        parse_ddl("CREATE TABLE t (\n a int,\n b,\n c int)")
    with pytest.raises(TemplateError, match="line 2.*CREATE INDEX|line 2"):
        parse_ddl("CREATE TABLE t (a int);\nCREATE INDEX i ON t(a);")


def test_an_unclosed_table_is_an_error():
    with pytest.raises(TemplateError, match="parenthesis"):
        parse_ddl("CREATE TABLE t (a int, b varchar(3)")


def test_duplicate_columns_are_an_error():
    with pytest.raises(TemplateError, match="twice"):
        parse_ddl("CREATE TABLE t (a int, A text)")


def test_a_table_with_no_columns_is_an_error():
    with pytest.raises(TemplateError, match="no columns"):
        parse_ddl("CREATE TABLE t (PRIMARY KEY (a))")


# --- read_schema -------------------------------------------------------------------------------------------------


def test_read_schema_from_a_json_list_a_json_object_and_a_ddl_file(tmp_path):
    cols = [{"name": "a", "type": "int"}, {"name": "b", "type": "varchar(5)"}]
    (tmp_path / "list.json").write_text(json.dumps(cols))
    (tmp_path / "obj.json").write_text(json.dumps({"columns": cols}))
    (tmp_path / "t.sql").write_text("create table t (a int, b varchar(5));")
    assert read_schema(str(tmp_path / "list.json")).columns == cols
    assert read_schema(str(tmp_path / "obj.json")).columns == cols
    sql = read_schema(str(tmp_path / "t.sql"))
    assert sql.columns == cols and sql.table == "t"
    assert read_schema(cols).columns == cols


@pytest.mark.parametrize("bad", [
    [], [{"name": "a"}], [{"type": "int"}], [{"name": "", "type": "int"}], [{"name": "a", "type": 3}],
    [{"name": "a", "type": "int"}, {"name": "a", "type": "int"}], [1], 3, None])
def test_a_bad_column_list_is_an_error(bad):
    with pytest.raises(TemplateError):
        read_schema(bad)


def test_a_missing_schema_file_says_so(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_schema(str(tmp_path / "none.sql"))
