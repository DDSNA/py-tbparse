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


# --- review findings (#31) ---------------------------------------------------------------------------------------


def test_columns_named_key_index_check_like_are_kept():
    _, cols = parse_ddl("CREATE TABLE s (key text, value text)")
    assert [c["name"] for c in cols] == ["key", "value"]
    _, cols = parse_ddl("CREATE TABLE s (index int, v int)")
    assert [c["name"] for c in cols] == ["index", "v"]
    _, cols = parse_ddl("CREATE TABLE s (check int, primary text, like varchar(5), unique int, constraint int, a int)")
    assert [c["name"] for c in cols] == ["check", "primary", "like", "unique", "constraint", "a"]
    assert cols[2]["type"] == "varchar(5)"


def test_real_constraints_are_still_skipped():
    _, cols = parse_ddl("""CREATE TABLE s (a int, b text, KEY idx (a), UNIQUE KEY u (a, b), INDEX (b), UNIQUE (a),
        FULLTEXT KEY ft (b), PRIMARY KEY (a), FOREIGN KEY (a) REFERENCES o (id), CONSTRAINT c1 CHECK (a > 0),
        CONSTRAINT c2 UNIQUE (b), CHECK (a < 9), EXCLUDE USING gist (a WITH =), LIKE other INCLUDING ALL,
        KEY `k2` (a), `key` text)""")
    assert [c["name"] for c in cols] == ["a", "b", "key"]


def test_bracket_identifiers():
    _, cols = parse_ddl("CREATE TABLE t ([a]]b] int, [it's] int, [a--b] text, [x(y] int, [z)] int)")
    assert [c["name"] for c in cols] == ["a]b", "it's", "a--b", "x(y", "z)"]
    assert cols[0]["type"] == "int"


def test_array_types_are_not_brackets():
    _, cols = parse_ddl("CREATE TABLE t (a int[], b text[3], c int)")
    assert [c["name"] for c in cols] == ["a", "b", "c"]


def test_mysql_show_create_table_with_engine_and_partition():
    table, cols = parse_ddl("""CREATE TABLE `orders` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `name` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL COMMENT 'a;b, (c)',
  PRIMARY KEY (`id`),
  KEY `idx_name` (`name`)
) ENGINE=InnoDB AUTO_INCREMENT=5 DEFAULT CHARSET=utf8mb4 COMMENT='x;y'
PARTITION BY RANGE (id) (PARTITION p0 VALUES LESS THAN (10), PARTITION p1 VALUES LESS THAN MAXVALUE);
""")
    assert table == "orders"
    assert [c["name"] for c in cols] == ["id", "name"]
    assert parse_ddl("CREATE TABLE a (x int) ENGINE=InnoDB;")[1] == [{"name": "x", "type": "int"}]
    assert parse_ddl("CREATE TABLE a (x int) WITH (fillfactor=70) TABLESPACE ts")[1][0]["name"] == "x"


def test_second_table_is_still_refused():
    with pytest.raises(TemplateError, match="a second table"):
        parse_ddl("CREATE TABLE a (x int) CREATE TABLE b (y int)")
    with pytest.raises(TemplateError, match="line 2") as e:
        parse_ddl("CREATE TABLE a (x int) ENGINE=InnoDB;\nSELECT 1;")
    assert "second table" not in str(e.value)
    assert "after the table definition" in str(e.value)


def test_character_set_in_a_type_is_still_a_string():
    assert sql_family("varchar(20) CHARACTER SET utf8mb4") == "string"
    assert sql_family("text CHARSET utf8 COLLATE utf8_bin") == "text"
    assert sql_family("character varying(5)") == "string"


def test_mysql_backslash_escape_in_a_default():
    # issue #39: `\'` inside a string is an escaped quote in MySQL
    table, cols = parse_ddl("CREATE TABLE s (a varchar(5) DEFAULT 'it\\'s')")
    assert table == "s" and cols == [{"name": "a", "type": "varchar(5)"}]
    table, cols = parse_ddl("CREATE TABLE s (\n  a varchar(5) DEFAULT 'it\\'s, (not) -- a comment',\n  b int COMMENT 'x\\\\'\n) ENGINE=InnoDB;")
    assert [c["name"] for c in cols] == ["a", "b"]
    assert [c["name"] for c in parse_ddl("CREATE TABLE s (a varchar(5) COMMENT 'it\\'s /* x */', b int);")[1]] == ["a", "b"]


def test_a_trailing_backslash_in_a_standard_string_is_still_a_complete_string():
    # PostgreSQL and SQL Server read `\` as a plain character: this default is `C:\`, and the statement is fine
    table, cols = parse_ddl("CREATE TABLE s (a varchar(20) DEFAULT 'C:\\', b int)")
    assert [c["name"] for c in cols] == ["a", "b"]


def test_a_really_unclosed_string_is_still_an_error():
    with pytest.raises(TemplateError, match="unclosed parenthesis"):
        parse_ddl("CREATE TABLE s (a varchar(5) DEFAULT 'oops, b int)")


def test_json_columns_case_insensitive_duplicates():
    with pytest.raises(TemplateError, match="twice"):
        read_schema([{"name": "ID", "type": "int"}, {"name": "id", "type": "int"}])
