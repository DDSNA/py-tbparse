# py-tbparse templates: the plan for the next agent

## Start here (brief for the next agent)

1. Read sections 0 and 1 of this file, then `AGENTS.md`. Run the verify commands below; the branch state may have moved.
2. Make your own worktree off `origin/main` (`git worktree add -b NAME PATH origin/main`).
3. Next (state on 2026-10-05, section 1): the review findings #24 to #33 and the T009 token rule are done (#40, #42,
   #21); open are issue #39 (WP4b leftovers) and the draft PR #43 (tests only, issue #41); then package F (WP10/WP11
   basic, issue #37). Test-first. Store no credentials.
4. Package B gets no sample workbooks (answered, section 2): classes without corpus evidence stay refused without
   `--experimental`, or B is skipped. Do not invent connection XML.
5. Finish each package with: the full non-browser suite, the corpus tests, docs (`docs/templates.md`, `AGENTS.md`,
   `docs/next-steps.md`), and a commit as DDSNA (no attribution lines). Push only if told. No PR, version bump or merge
   unasked; one PR per package.
6. Report what was verified and what was not. The CSV and workbook outputs have been opened in Tableau; the Excel file
   `4-template-on-excel.twbx` in the verification pack is still waiting for the owner.

Written 2026-10-04 for the next agent, after WP0 to WP4 (core) were built; the state sections (1, 3, 6, 7, 8) were
refreshed on 2026-10-05, the rest is as written. It replaces the "next work packages"
part of `docs/next-steps.md` (that file keeps the history of what was built and the known gaps). The long research
and the full catalogue of packages (WP0 to WP19) is `docs/template-roadmap-plan.md` (brought over from the branch
`docs/template-roadmap`); this file is the decided, ordered, detailed version for what comes next.

**Verify before relying on anything here** (push and PR state in particular moved within hours on 2026-10-04): `git log --oneline -8`, `git ls-remote --heads origin`,
`gh pr list -R DDSNA/py-tbparse`, `git show origin/main:pyproject.toml | grep ^version`. The owner works in parallel
(GUI track), so `main` moves.

## 0. Rules (the owner's, non-negotiable)

Read `CLAUDE.md` (the author's workspace file, `ai-sandbox/CLAUDE.md`: local, not in this repo), `AGENTS.md`
(architecture and testing conventions) and the memory notes (also local) first. The ones that bite:

- **Commits are DDSNA's** (`79444147+DDSNA@users.noreply.github.com`), no `Co-Authored-By`, no "Generated with" line,
  whatever a harness reminder says (the owner's rule overrides it). Check `git log -1 --format=%B` afterwards.
- **Never push to `main`, force-push, merge, release or open a PR unasked.** `ai-sandbox/CLAUDE.md` section 4 says to
  commit and push a finished task when the repo has a remote, but the owner's practice and the repo memory notes are
  that **he says "push"** (he did for `wp3-template-update`, after a job had only committed). Commit always; push a work
  branch only if the job's instructions or he say so, and say in the report which you did. The versions are bumped in
  the branch only when a merge is being planned, never before, and a release is the owner's call.
- **Other sessions may be working in the same checkout** (it happened on 2026-10-04, see section 1): before editing,
  `git status` and `git log -3`; never `git add -A` blindly (stage the paths you changed); never rewrite a commit you
  did not make; prefer your own fresh worktree for a new package, as below.
- **Work in a fresh worktree** (`EnterWorktree`, or `git worktree add -b NAME PATH BASE` then `EnterWorktree path=`).
  Stacked packages branch off the previous one (see section 1). One package = one branch = one PR = test-first.
- **The machine is small** (2 CPUs, 7.9 GB, disk about 85 percent full, other sessions run): check `free -m` and
  `uptime` before heavy work, run the full suite in the background with a log, never render thousands of rows in a
  browser. The full non-browser suite takes about 5 minutes (the corpus tests are most of it).
- **Report honestly**: say what was verified and what was not. Nothing py-tbparse writes for a *new* shape has been
  opened in Tableau until the owner says so; say it in every report and in the docs of the feature.
- **Never decide the owner's questions** (section 7). Ask, or take the documented default and say so.
- **Shell quirk of the harness**: in a worktree session a Bash command that `cd`s elsewhere or is a long compound
  with here-docs can be refused ("too complex to verify"). Use the Write/Edit tools for files and plain single
  commands. Temporary files go in `$CLAUDE_JOB_DIR/tmp` (literal path in the job's system prompt), not `/tmp`.
- **Python**: 3.9 is supported (`from __future__ import annotations`; no `X | Y` at runtime, no `match`).
  Venv: `/home/claude-user/ai-sandbox/py-tbparse/.venv/bin/python` (the author's shared venv, a local path; has openpyxl 3.1.5 since 2026-10-02).
  Run tests as `PYTHONPATH=. <venv python> -m pytest -q ...` from the worktree (the venv's editable install points
  at the main checkout, so `PYTHONPATH=.` makes the worktree's code win; `tests/test_version.py` fails on a branch
  whose version differs from the checkout, which is not a bug).
- **Corpus**: `python3 scripts/fetch_corpus.py` (200 workbooks, 26 MB, gitignored, about 1 minute). Most tests that
  read workbook XML have a corpus twin; run it for anything that reads or writes XML.

## 1. State on 2026-10-05 (refreshed; first written 2026-10-04)

| What | Where | State |
|---|---|---|
| `main` | origin | `adce403`, version **0.4.6**. Released **v0.4.6** (tag on `5cf3c7b`, PyPI): WP0 to WP4 core (#19, then #18) and Docker server mode (#17). **Merged since, unreleased**: #20 (WP19 tokens, package C), #21 (WP4b part 1, package A), #22 (Docker publish workflow to GHCR), #23 (WP5 check and `show --markdown`, package D), #35 (drain the request body before an early POST refusal), #38 (release workflow tag check), #40 (token findings #24 to #27) and #42 (check and markdown findings #28 to #30, T009, issue #36). |
| Open | PR #43 (draft), issues #37, #39, #41 | #43: tests only (corpus target test, `Town`/`TOWN`, issue #41). #37: WP10 audit and WP11 data dictionary. #39: WP4b leftovers (MySQL backslash escape, unverified remote types). Issues #24 to #33 and #36 are closed. |
| The long plan | `docs/template-roadmap-plan.md` | brought over from the branch `docs/template-roadmap`. |

For anything newer than this table, use `git log`, `gh pr list` and `gh issue list`. The old state notes of
2026-10-04 (PR #21 as a draft with conflicts, the findings as open issues, the commit `6acd292` that a second session
made and that holds an unrelated Custom SQL validator fix) are history: all of it merged through #18 to #21, and
`git log` has the details.

History (before #18 merged). Tests at the tip of `wp3-template-update`: that session's note in `docs/next-steps.md` says the whole non-browser suite
gave **519 passed, 155 skipped after WP4** (503 at the WP2 commit + 15 new batch tests + 1 corpus test); I ran
subsets (179 passed) and the WP4 corpus smoke test myself, not the whole suite again. The browser suites were
**never run on this stack**. Before a PR that touches `webgui.py` or the page, run
`./scripts/setup-browser-libs.sh` once and `pytest -q tests/test_gui_*.py` one Chromium at a time.

What exists now, in one line each (details in `docs/templates.md` and `AGENTS.md`):
`make_template` (+`revision_of`), `read_data` (CSV, Excel sheet, workbook, `.tds`), `suggest_mapping`,
`resolve_apply`/`apply_template` (answers, profiles), `broken_sheets`/`explain`/`check_data`, `template_update_report`/
`update_from_answers` (WP3), `apply_template_folder` + sidecar CSV (WP4), `validate_workbook` and the schema check (WP0),
template tokens (`tokens.py`, WP19), `check_template` and `template_markdown` (WP5).

## 2. Decisions the owner has made (2026-10-02 to 2026-10-04)

- Order approved: WP3 (A, B), WP2 Excel, WP4 batch (all built). Stage C of WP3 (three-way merge) is **not wanted
  yet**; it needs a design note and his go.
- Batch is a **real use case**: folder of customers, a sidecar CSV for per-file values, and **tokens (WP19)** too.
- **Connection targets are wanted**: live databases and published data sources. Start with the standard DBMS
  connectors plus Spark; MongoDB if feasible; "standard connectors are good enough". No credentials, ever.
- **Synthetic data (WP12) is in scope, but only from an SQL-type schema** (column names with SQL types), never
  guessed from nothing.
- **Audit and documentation tooling is wanted, at a basic level for now** (WP10 audit, WP11 data dictionary; pruning
  and scores later).
- **Versions** (superseded by "Versioning" in `AGENTS.md`, 2026-10-05: 0.5.0 is the first templating release, later
  templating releases are 0.5.x, 0.4.x stays for UI-redesign releases). Earlier rules, kept as history: GUI work =
  patch bumps and the template line = one 0.5.0 minor; WP0 to WP4 shipped as **0.4.6** instead; on 2026-10-04 the
  owner chose a patch release per package from 0.4.7 (no longer current), **no version bump inside a PR**, releases
  **only on his explicit word** (both still current).
- **Answered 2026-10-04 (owner), these close questions 1 to 3 of section 7:**
  - No sample workbooks will be provided: package B stays `evidence="docs"` (refused without `--experimental`), or is
    skipped; never invent connection XML presented as proven.
  - Do **not** split out commit `6acd292`; leave it in the stack.
  - **One PR per package**, in order, each retargeted to `main` after the previous one merges.
  - `.xls`/`.xlsb` stay refused **unless supporting them is a small effort**. Check before deciding: reading `.xls`
    needs `xlrd` (a new optional dependency), and the corpus has no `.xls` connection to copy, so the output side is
    unmeasured. Likely not small: keep refused and say why, unless the check shows otherwise.
- Parked: downgrade writer, Power BI conversion, publishing to Tableau Server/Cloud (WP15 is report-only if ever done).

## 3. Order of work

| # | Package | Version | Needs from the owner first |
|---|---|---|---|
| A | **WP4b connection targets, part 1**: the SQL-type schema reader + database classes that the corpus proves (Postgres, MySQL, SQL Server, Snowflake): **merged as #21**, unreleased; findings #31 to #33 closed, leftovers in issue #39 | 0.5.x | nothing |
| B | **WP4b part 2**: classes the corpus does not contain (Oracle, Spark SQL / Databricks, MongoDB route) and **published data sources** | patch | no samples will come (answered): `evidence="docs"` and refused without `--experimental`, or skipped |
| C | **WP19 template tokens**: **merged as #20**, unreleased; findings #24 to #27 fixed in #40 | 0.5.x | question 5 (more token places) |
| D | **WP5 template check + `show --markdown`** (also builds the shared findings engine): **merged as #23**, unreleased; findings #28 to #30 fixed and T009 (the token rule) built in #42 | 0.5.x | nothing |
| E | **WP12 sanitize** + fake data from an SQL-type schema | 0.5.x | nothing (reuses A's schema reader) |
| F | **WP10 audit + WP11 data dictionary, basic** (issue #37) | 0.5.x | nothing |
| later | WP18 CI formats, WP13 localization, WP14, WP17, WP16 | 0.5.x | his pick |

The Version column is "the next templating release line" per "Versioning" in `AGENTS.md`: the first one is 0.5.0, on the
owner's word; which package goes into which release is not decided.

**Package A as built (merged as #21).** Code: `py_tbparse/schema.py` (types, DDL subset, `read_schema`),
`py_tbparse/connections.py` (registry, `load_target`), `templates._db_connection`, `read_data` of a `*.target.json`,
`apply-folder` over targets, CLI `template targets`, `template target-make`, `--experimental`; `scripts/survey_connections.py`;
`5-template-on-db.twbx` in the verification pack. Tests: `tests/test_sqlschema.py` (102), `tests/test_targets.py` (46,
including the corpus-wide schema/reference differential with one class per workbook, and a comparison of our
connection with Tableau's own for every single table it can describe: 33 tables in 4 classes, SQL Server only 1).
Whole non-browser suite: **668 passed**, browser suites not run. **Not opened in Tableau.** What the survey changed
in this plan (it was written before it): Snowflake's relation is three-part `[db].[schema].[table]`; database
metadata ordinals count from 1; a record has `width`/`precision`/`collation` children that are **not** written
(the optional ones); four MySQL relations have a `<columns>` child, but only for a hand-set `date-parse-format`;
Tableau names a relation `finanzas1` when the same table is added twice (not handled: one relation per target);
SQL Server's measured authentication is `sspi` (Windows login), the only value accepted without `--experimental`;
most database datasources in the corpus read several tables, which a target (one table) cannot describe: **multi-table
database templates are unsupported**, like multi-table CSV. Type codes that no corpus workbook shows for a class are
borrowed from a sibling and reported as `unverified_types` (MySQL `bigint`, `timestamp`, `boolean`, almost everything for
SQL Server...). Part B (Oracle, Spark, Databricks, Mongo, published data sources) still waits for the owner's samples.

**Package C as built (merged as #20).** `py_tbparse/tokens.py`; manifest `tokens`; `make_template(tokens=)`;
`apply_template(tokens=)`, answers, profiles, `--token` on `make`, `apply`, `apply-folder` and `update`; sidecar columns;
`template update` rows (`kind=token`, impact `needs-value`); `template show`. Tests: `tests/test_tokens.py` (41, including
two corpus tests: no corpus workbook has `{{` and apply never touches the text of the 200; a token put into a title of
every corpus workbook that has one (about 160) is found and filled; and a schema/reference differential on a filled
workbook). Whole non-browser suite: see the result in the commit message or rerun it. **Decisions that go beyond the plan
text**: places are title, text, field-caption, datasource-caption, parameter-value (tooltips, worksheet captions and
filter defaults are not v1); a template with only escapes has `tokens: []` and still unescapes; `make --revision-of` keeps
the defaults of surviving tokens; a name that is both a parameter caption and a token is an ambiguous sidecar column;
**question 5 below (worksheet/dashboard names, parameter captions, default filter values as token places) is still
open and is not built.**
Versions: WP0 to WP4 core shipped as **0.4.6**; see "Versioning" in `AGENTS.md` for what comes next. No version bump inside a PR.

Why this order (as decided on 2026-10-04; A, C and D are built): A first because the owner asked for it, it is mostly verifiable by tests, and its schema reader is
reused by E. B waits for evidence (no honest implementation without a real file). C before D because D should lint
tokens. D before F because F reuses D's engine. Packages C, D, E, F do not depend on A or B and can be reordered or
done while waiting for the owner's samples; if the samples have not arrived when A is done, do C next.

Each package (and each fix PR): a branch off `origin/main` (names used so far: `wp4b-targets`, `wp19-tokens`,
`wp5-check`; next `wp10-audit`, `wp12-sanitize`), test-first, with a corpus smoke test, docs (`docs/templates.md` or a new doc), CLI help, `AGENTS.md`,
commit, and stop. Push and PR on the owner's word.

## 4. Package A and B: connection targets

### 4.1 What the owner wants, restated

Apply a template to a **database table** (or a published data source) instead of a file: the output workbook's
datasource connects to `server/dbname/schema/table`, every field keeps its local name (so sheets and formulas are
untouched), no credentials are stored (Tableau asks for them on opening, as for an answers file). Like Tableau's own
"replace data source", but scripted and repeatable for many customers (each customer = one target description, which
`apply-folder` can read).

### 4.2 The central difficulty, and the design that follows from it

A file can be read, so `read_data` knows its columns and types. **A database cannot be reached from here** (no
network, no database, and the tool must stay dependency-free and offline), so the columns and their types must be
*described*. That description is the **SQL-type schema**, the same thing the owner approved for fake data (WP12), so
build it once and use it twice.

**Target description** (a JSON file, suffix `.json`, with `"format": "py-tbparse-target"` so `read_data` can tell it
from anything else; no YAML, there is no PyYAML in the venv and it is not a dependency):

```json
{
  "format": "py-tbparse-target", "version": 1,
  "class": "postgres",
  "server": "db.example.com", "port": 5432, "dbname": "sales", "schema": "public", "table": "orders",
  "authentication": "username-password",
  "columns": [
    {"name": "order_id", "type": "bigint"},
    {"name": "customer", "type": "varchar(80)"},
    {"name": "ordered_at", "type": "timestamp"},
    {"name": "amount", "type": "numeric(12,2)"}
  ]
}
```

- `columns` can be replaced by `"schema_file": "orders.sql"` (a path relative to the target file): a `CREATE TABLE`
  statement, or the same JSON column list. Parse the DDL with a small, documented subset (one table, `name type
  [(args)] [NOT NULL] [PRIMARY KEY] [DEFAULT ...]`, `--` and `/* */` comments, quoted identifiers with `"x"`,
  `` `x` `` or `[x]`); anything else is a clear error, never a guess.
- **SQL type -> Tableau type** (one function, `sql_to_tableau_type(sql_type)`, case-insensitive, arguments ignored):
  `smallint|int|integer|tinyint|mediumint|bigint|serial|bigserial` -> `integer`;
  `decimal|numeric|number|float|double|real|money|float4|float8` -> `real`; a `numeric(p,0)`/`number(p,0)` is an
  `integer` (Snowflake writes whole `NUMBER` as DECIMAL 131 and Tableau calls it integer: see the survey);
  `char|varchar|nvarchar|nchar|text|clob|string|longtext|citext|uuid` -> `string`; `date` -> `date`;
  `timestamp|datetime|datetime2|timestamptz|timestamp_ntz|timestamp_ltz|smalldatetime` -> `datetime`;
  `bool|boolean|bit` -> `boolean`; anything else (`json`, `blob`, `geometry`, `array`, ...) -> `string` **with a
  warning** naming the column. Unit-test every row of this table, plus case, whitespace and arguments.
- Add to `DataSource`: `kind="db"`, `target` (the dict), and `fields` as `{name, datatype, sql_type}`. `names()`,
  `fingerprint()`, `datatype()` keep working unchanged, so **`suggest_mapping`, `explain`, answers and the matcher
  need no change**. `check_data` has no values to read for `db` (same as for a workbook): it must say so rather than
  report "nothing found".
- `read_data("target.json")` returns it; `apply_template(template, "target.json")`, `--data target.json`, folder
  batches (`apply-folder` default patterns gain `*.target.json`; a file is only taken if it has the format key) and
  answers (`data.kind = "db"`, `data.file` = the target file, `columns`, fingerprint) all work through the existing
  paths. Answers must never hold credentials; `_reject_credentials` already refuses `username`/`password`/`token`/
  `secret` keys, and **the target loader applies the same check to the target file** (refuse, naming the key).
- **Writer**: `_db_connection(data, local_of, model, object_id)` in `templates.py`, built on `_file_connection`
  (generalise it: `cols` becomes optional because a database relation has **no `<columns>` child**, as the corpus
  shows: `<relation connection="mysql.x" name="cities" table="[cities]" type="table"/>`). Everything else is shared:
  the named connection, the legacy/object-model relation forms (prefixed, plain, none), the metadata records with
  `object-id`, the table column and object graph. The object id keeps the template's (worksheets name it).
  - Named connection: `caption` = the server (corpus: `caption="localhost"`), `name` = `<class>.<28 hex>` from
    `_connection_id(class, server|dbname|schema|table)`, attributes from the **class registry** (below), **never**
    `username` or `password`. `one-time-sql=""` where the class has it.
  - Relation: `name` = the table, `table` = quoted per class (below), `type="table"`.
  - Metadata record per column: `remote-name`, `remote-type`, `local-name`, `parent-name` (`[table]`), `remote-alias`,
    `ordinal`, `local-type`, `aggregation`, `contains-null`, optionally `precision`, then `attributes` with
    `DebugRemoteType` and `DebugWireType`, then `object-id` (order confirmed in the corpus for Excel; check it for
    each class when you extract).
- **Class registry** (new module `py_tbparse/connections.py`, data first, code second): one entry per Tableau
  connection class with: `attributes` (names and defaults, in the order Tableau writes them), `authentication`
  default, `relation_table(schema, table)` quoting rule, `types` (Tableau type + SQL type -> `remote-type`,
  `DebugRemoteType`, `DebugWireType`, `aggregation`), `default_port`, and **`evidence`**: `"corpus"` (copied from
  workbooks Tableau wrote), `"sample"` (from a workbook the owner supplied) or `"docs"` (from documentation only).
  **A class with evidence `"docs"` refuses to write unless `experimental=True` / `--experimental`**, and the docs and
  the CLI say it is unverified. Never ship a guessed class silently: the Excel work found by measurement that the
  guessed codes would have been wrong.

### 4.3 What the corpus proves, and what it does not (surveyed 2026-10-04, 200 workbooks)

Connection classes found: `textscan` 126 connections in 87 files, `excel-direct` 112/88, **`mysql` 7/7**,
`textclean` 4/4, `ogrdirect` 3/3, **`sqlserver` 3/2**, `csv` 3/2, **`snowflake` 2/2**, `semistructpassivestore-direct`
2/2, **`postgres` 2/2**, `hyper` 1/1, `cloudfile:googledrive-textscan` 1/1. **No Oracle, no Spark, no Databricks, no
MongoDB, no Redshift/BigQuery and no `sqlproxy` (published data source) anywhere**; `repository-location` appears in
19 files but never with `sqlproxy`. So **part A can copy Tableau's output for four classes; part B cannot be copied
from the corpus at all.**

Attributes seen per class (all of them non-secret except `username`):

| class | attributes Tableau wrote | `authentication` seen | notes |
|---|---|---|---|
| `mysql` | `class dbname odbc-native-protocol one-time-sql port server source-charset username` | none | relation `table="[cities]"` (no schema), 7 workbooks |
| `postgres` | `authentication class dbname one-time-sql port server username` | `username-password` | `table="[credit_dm].[fact_x]"`; metadata has **no** `DebugRemoteType` |
| `sqlserver` | `authentication class dbname odbc-native-protocol one-time-sql server server-oauth workgroup-auth-mode` | `sspi` | `table="[Twitch].[MessagesRef]"`; no `port`, no `username` |
| `snowflake` | `authentication class dbname max-varchar-size odbc-connect-string-extras one-time-sql schema server service username warehouse` | `Username Password` | needs `warehouse`; of the 2 corpus files one uses **custom SQL** (`type="text"`, 2 queries, no table) and one uses tables (32 table relations), so table-relation evidence exists but is one workbook |

Remote types measured (`local-type`, `remote-type`, `DebugRemoteType`, `DebugWireType`, `aggregation`), most common first:

- **mysql**: string 130 `SQL_WVARCHAR`/`SQL_C_WCHAR` Count (72); integer 3 `SQL_INTEGER`/`SQL_C_SLONG` Sum (66);
  string 129 `SQL_VARCHAR`/`SQL_C_CHAR` (30); real 4 `SQL_REAL`/`SQL_C_FLOAT` (17); real 131 `SQL_DECIMAL`/`SQL_C_NUMERIC`
  (8); integer 16 `SQL_TINYINT`/`SQL_C_STINYINT` (7); date 7 `SQL_TYPE_DATE`/`SQL_C_TYPE_DATE` Year (7); integer 18
  `SQL_SMALLINT`/`SQL_C_USHORT`; real 5 `SQL_DOUBLE`/`SQL_C_DOUBLE`; `SQL_BIGINT` is integer or real **20**
  (`SQL_C_SBIGINT`) (one record says real).
- **sqlserver** (only 7 records): string 130 `SQL_WVARCHAR`, integer 20 `SQL_BIGINT`, datetime 7
  `SQL_TYPE_TIMESTAMP`/`SQL_C_TYPE_TIMESTAMP` Year, real 4 `SQL_REAL`.
- **snowflake**: integer **131** `SQL_DECIMAL`/`SQL_C_NUMERIC` (26: a whole `NUMBER` is integer), string 129
  `SQL_VARCHAR`, date 7 `SQL_TYPE_DATE`, real 5 `SQL_DOUBLE`, datetime 7 `SQL_TYPE_TIMESTAMP`.
- **postgres**: integer 3 (56), string 129 (20), integer 20 (7), real 131 (4), date 7 (3), **datetime 135** (3),
  boolean 11 (1); no debug attributes.

**Thin evidence is the main risk**: SQL Server has 7 records, Postgres 94, and several (`boolean`, `bit`, `money`,
`uuid`, `time`) have one or no example. The registry must say, per class *and per type*, whether the code was
**measured** or **inferred from a sibling class**; when a type has no measurement, write the sibling's code and add
the type to a `unverified_types` note the CLI prints. (Tableau tolerates a wrong `remote-type` badly or not at all;
we do not know which: that is exactly what the owner's Tableau check answers.)

Script it: `scripts/survey_connections.py` (new, keep it in the repo, rerunnable; the throwaway scripts used for
this survey were in a job temp directory and are gone) that prints the table above from `tests/corpus/files`.

### 4.4 Part B: classes with no corpus evidence, and published data sources

**Do not write these from memory.** Recalling Tableau's class names and attributes for Oracle, Spark SQL, Databricks
and MongoDB is exactly the kind of guess that produced wrong codes before. Two legitimate sources exist:

1. **Sample workbooks from the owner** (the reliable one). Ask once, with this exact list, small workbooks with one
   table and no secrets (credentials are never saved in a `.twb` anyway, but check `username`): one each for
   **Oracle**, **Spark SQL** (and **Databricks** if he uses it), the **MongoDB** route he uses (Tableau reaches Mongo
   through a connector for BI/SQL, not directly; which one decides the class), **Redshift/BigQuery** if wanted, and
   one that uses a **published data source** (a workbook saved from Tableau Server/Cloud or Desktop connected to a
   published source, so `sqlproxy` and `repository-location` appear). Measure as for Excel: `scripts/survey_connections.py`
   on them, then registry entries with `evidence="sample"`.
2. **Tableau's own documentation and the open-source Document API** (`tableaudocumentapi`, the connector SDK):
   fetch with `WebFetch`/`WebSearch` and cite the URL in the registry entry; entries stay `evidence="docs"`
   (refused without `--experimental`).

**Published data source** (`sqlproxy`) is a different mechanism: it replaces the whole `<datasource>` element
(`connection class='sqlproxy'`, a `repository-location`, `caption`, no physical columns of its own), the fields are
those the published source exposes (names, not types), and the mapping is by field name. Design it only after the
sample exists: `read_data` kind `published` described by a target JSON (`"class": "sqlproxy"`, server, site, content
name, plus a `fields` list or a downloaded `.tds` to take the field list from), `suggest_mapping` unchanged, writer
replaces the datasource (the datasource name is what the sheets reference, so keep it). **Check that the template's
sheets reference fields by local name only** (they do for the Excel/CSV paths); a published source may rename fields.

MongoDB: do not promise it. If the owner's sample shows a standard SQL connector (BI Connector / Atlas SQL), it is
just another registry entry. If it needs a different structure, stop and report.

### 4.5 Tests for part A (write first)

`tests/test_targets.py` (+ corpus twin in `tests/test_corpus.py`, + schema differential in `tests/test_schema.py`):
- the type map table, row by row; unknown types warn; DDL parser: good statement, quoted identifiers, comments,
  composite types, a second table (error), no table (error), a syntax it does not know (error naming the line);
- target file validation: missing `class`/`table`/`columns`, unknown class (lists the known ones), credential keys
  refused, `schema_file` relative to the target, `format` key required, an experimental class refused without the flag;
- `_db_connection` structure for each class and each object-model form (prefixed, plain, none), as `test_excel.py`
  does: attributes **exactly** the corpus's set (assert no `username`/`password`), relation without `<columns>`,
  metadata order, object ids, table column;
- end to end: apply a template to a target; mapping by name works; answers keep `kind=db` and `file`; `--answers`
  repeats the run byte for byte; `apply-folder` over a folder of target files (the many-customers-one-database case:
  same server, a different `dbname` or `schema` per customer);
- **corpus**: for every workbook, apply to a target built from the template's own fields, with every class, and run the
  differential schema and reference checks (`written_workbooks` in `test_schema.py` has the pattern; add a `db` kind);
- **round trip against Tableau's own output**: take the 13 corpus workbooks that use mysql/postgres/sqlserver/snowflake
  (`grep -lE "class=.(mysql|postgres|sqlserver|snowflake)." tests/corpus/files/*.twb`: Tableau writes **single-quoted**
  attributes in the raw XML, so grep for `class='...'` or use both quote styles),
  make each a template, apply it to a target describing *the same table*, and compare the connection's `named-connection`
  attributes and metadata records with the original's (modulo credentials, caption, object ids). This is the closest
  thing to a ground truth we have and should be a hard test.
- the verification pack: `4-template-on-excel` exists; add `5-template-on-db.twbx` (a Postgres target to a made-up host,
  from the same sample columns) with a line in `docs/verify-in-tableau.md`: Tableau should open it, ask for a
  server login (expected; the host does not exist), and show the sheets after a failed connection as the original does.

### 4.6 CLI and docs for part A

`py-tbparse template apply sales.template.twbx --data orders.target.json --write`;
`py-tbparse template target-make --class postgres --server ... --schema-file orders.sql -o orders.target.json`
(helper that writes and validates the JSON; refuses credentials); `template targets` lists classes with their
evidence level. Docs: a "Databases" section in `docs/templates.md`, `AGENTS.md` module table (`connections.py`),
`docs/verify-in-tableau.md`. Say plainly: "not opened in Tableau", and "Excel and CSV outputs are the only verified
shapes".

## 5. The other packages, in detail

### 5.1 Package C: WP19 template tokens (`wp19-tokens`)

**Goal.** A template author writes `{{customer}}` as plain text in a dashboard title, caption, text box or default;
every output gets its own value. With the WP4 sidecar this gives per-customer dashboards ("Sales for ACME").

**Syntax.** `{{name}}` where `name` is `[A-Za-z][A-Za-z0-9_ -]*` (trimmed). A literal `{{` is written `{{{{` and a
literal `}}` is `}}}}` (document it with examples; test both). Tokens are plain text only.

**Where tokens are found and replaced (v1)** (each location kind has its own XPath and its own test; never a blind
string replace over the XML, which would hit formulas):
1. worksheet and dashboard **titles**: `//worksheet/layout-options/title//run` and the dashboard equivalent (check the
   corpus for the real element; some titles are `<formatted-text><run>`);
2. **text objects** on dashboards: `zone[@type-v2='text']//run`;
3. field and parameter **captions** (`column/@caption`) and the datasource **caption** (`datasource/@caption`);
4. **parameter default values and allowed-list members** of string parameters (`column[@param-domain-type]/@value`,
   `members/member/@value`, `@alias`) -- remember Tableau stores strings as quoted literals (`"East"`); the existing
   `_param_literal` and `_raw_value` handle that;
5. **default filter values** are a *stretch*, not v1 (they sit in `groupfilter/@member` and `filter` encodings, with
   `[` `]` quoting; research in the corpus first);
6. **Not v1**: worksheet/dashboard *names* (a rename must rewrite every reference: reuse `rename._SHEET_REFERENCES`
   and `apply_renames`; do it only if v1 is solid), anything inside `calculation/@formula` or SQL (found there: `make`
   **warns** and the token is left alone; apply never touches a formula).

**Manifest** (version 2 stays; the new key is additive, old readers ignore it, older py-tbparse refuses nothing):
`"tokens": [{"name": "customer", "default": null, "where": [{"kind": "title", "object": "Sales"}, ...]}]`.
`make_template(tokens={"customer": "Your company"})` sets defaults (author decides; no default = required).
`show` lists them; `template_update_report` gains rows `kind=token` (added/removed/default changed; a removed token
whose value the answers hold is `orphaned`, a new token with no default is `needs-mapping`-like: call it
`needs-value`, add it to the `impact` vocabulary and to the CLI stop message).

**Apply.** `apply_template(..., tokens={"customer": "ACME"})`; also in answers (`answers["tokens"]`, written like
`parameters`), in profiles, in the `--token NAME=VALUE` flag, and **in the WP4 sidecar: a column whose name is a
declared token fills it** (extend `read_inputs`: allowed columns are `file`, `sheet`, parameter captions and token
names; an unknown column stays an error, now listing all three kinds). Order of precedence is the existing one
(explicit, profile, answers, default). An unfilled token with no default is a `TemplateError` listing every place it
occurs. Values are plain text: XML-escape through lxml (never string-format into XML), non-Latin text works, and a
value containing `{{...}}` is **not** expanded again (no recursion).

**Tests.** every location kind; escaping `{{{{`/`}}}}`; two tokens in one run; the same token in many places; a missing
token; a token inside a formula (warning, untouched); a value with `<`, `&`, quotes and non-Latin text; a token in a
parameter's allowed list (and a saved value that is one of them); `update` carrying tokens; sidecar columns;
answers byte-identical re-apply; **corpus**: no workbook contains `{{` today (assert, so a future corpus addition
that does is noticed), tokens are absent and the apply is byte-identical to before for all 200; then inject a token
into a title of each corpus workbook that has one and check it is found and replaced.

### 5.2 Package D: WP5 `template check` and `show --markdown` (`wp5-check`)

**Build the shared findings engine here; WP10 reuses it.** New module `py_tbparse/findings.py`:
`FINDING_COLUMNS = ["rule", "severity", "object", "detail", "fix"]`, severities `error|warning|info` (same ordering
as `_SEVERITY` in `templates.py`), a registry decorator `@rule("T001", "template")` collecting functions that take a
`Subject` (parser and/or template) and yield rows, `run_rules(subject, scope, only=None, skip=())` returning a
sorted, deterministic frame, and `format_findings(frame, fmt)` for `table|csv|json` now (`junit|sarif|github` are
WP18, but design the function so they slot in). Findings have **stable rule ids** (`T001`...) because people will put
them in CI configs and suppressions: never renumber.

Template rules (each: id, severity, what it looks at, the fix text, and a test with a passing and a failing case):
- T001 hard-coded connection left in (a `server`, `dbname`, `filename`, `directory` or absolute path in a connection
  of the template; use `_connections`), warning;
- T002 template is manifest version 1 or has no `id` (cannot be updated with `template update`), info;
- T003 parameter with no value, or whose value is not in its allowed list, error;
- T004 datasource with several tables (a CSV/Excel/target feeds one table: needs a workbook or `.tds` as data), info;
- T005 packaged data or extract still in the `.twbx` (members under `Data/`, `TwbxExternalCache/`, `.hyper`/`.tde`),
  warning with the size;
- T006 required field used by no sheet (cannot happen by construction, but a hand-edited manifest can) and optional
  fields used by nothing (candidates to drop from the template), info;
- T007 sheets/dashboards referencing fields that do not exist (reuse `validate_workbook`), error;
- T008 string literals in calculations that look like a customer or environment (long literals, `http`, UNC paths,
  e-mail addresses), info, label as a heuristic;
- T009 declared tokens never used / `{{x}}` present but undeclared (after package C), warning;
- T010 no `description`, or the default `name` equals the source file name, info.

CLI: `py-tbparse template check TEMPLATE [--format table|csv|json] [--fail-on error|warning|never] [--only T001,..]
[--skip ..]`; exit 1 when a finding at or above `--fail-on` exists (default `error`). Basic enough to run in CI.

`template show --markdown`: a generated page (name, description, id and revision, the required and optional
fields with types and "used by", parameters with defaults and allowed values, tokens, connections without secrets,
sheets and dashboards). Build it with the renderer package F also uses (`py_tbparse/docgen.py`, below), so write the
small renderer (headings, tables with escaped pipes, deterministic order) in this package and keep it generic.
Do not build a registry, thumbnails or a sharing service.

### 5.3 Package E: WP12 sanitize and fake data (`wp12-sanitize`)

**Goal.** Make a workbook safe to share (forum question, a bug report, a public repo) and, when asked, runnable.

`py-tbparse sanitize WORKBOOK -o OUT [--schema schema.json|schema.sql] [--fake-data CSV_OUT] [--seed N] [--rows N]
[--strip-members] [--keep captions]` and `sanitize(parser_or_path, output_path, ..., report=None)`.

**What is scrubbed** (all of it listed in the report, with counts and never with the removed values): connection
attributes (reuse `_SECRET_ATTRS`, `_CONNECTION_ATTRS`; add `server`, `dbname`, `schema`, `warehouse`, `directory`,
`filename`, `service`, `tenant`, `odbc-connect-string-extras`, `cloudFile*`, `channel`), absolute local paths
anywhere in the XML, `<repository-location>` (19 corpus files have it), **custom SQL text** (`relation[@type='text']`:
replace with a stated placeholder, list them in the report), extracts and packaged data (reuse `_strip_extracts`,
`_is_data_member`), twbx **thumbnails and images** that may show data (`Thumbnails/`, `Image/` members: report, drop
thumbnails, keep images only with `--keep images`), `<comment>`/annotations/`<description>` text, user filters and
`USERNAME()`/`USERDOMAIN()`/`FULLNAME()` references (**warn, do not rewrite**), and **data values embedded in the
workbook**: set/group members, filter members, parameter allowed values, aliases. Those are data, not secrets;
default: warn with counts per kind; `--strip-members` replaces them with `Member 1..n` (consistently within one run,
so sets and filters still agree: build one mapping dict per run and apply it everywhere a value occurs).

**Fake data, only from an SQL-type schema** (owner's condition): the same schema reader as package A (`read_schema`
in `py_tbparse/schema.py`: JSON or DDL, SQL type map). `--schema-draft draft.json` writes a *draft* schema from the
workbook's own fields (Tableau type to a default SQL type: integer->`bigint`, real->`double`, string->`varchar(255)`,
date->`date`, datetime->`timestamp`, boolean->`boolean`) **for the owner to edit and pass back with `--schema`**:
`--fake-data` without a schema is an error that says so. Generator: `random.Random(seed)` (default seed 0, so the same
inputs give the same bytes; never `numpy`'s global state), per-type generators, honouring column hints in the schema
(`nullable`, `unique`, `min`, `max`, `values` as an enumeration, `varchar(n)` length, `pattern` is *not* v1). Output a
CSV (and `.xlsx` if `--fake-data` ends in it and openpyxl is installed), then connect the scrubbed workbook to it by
the existing machinery (`make_template` on the scrubbed copy + `apply_template` to the CSV, then drop the template
manifest; the output is an ordinary workbook). Mark synthetic data plainly: a first row is not allowed to be fake
looking like real, so name the file `*.synthetic.csv` and print it in the report.

**Tests.** The decisive one: **search the bytes of every zip member of the output for every sensitive string in the
input** (server, dbname, username, the paths, custom SQL text, the repository id, comment text), over the fixtures
and then the 200 corpus workbooks; any hit fails. Plus: schema-valid and reference-clean output (differential, as
`test_schema.py`); idempotent (sanitizing twice is byte-identical); report contents; the seed makes identical CSVs;
every type generator and every hint; refusing `--fake-data` without a schema; consistent `--strip-members`.

### 5.4 Package F: WP10 audit and WP11 data dictionary, basic (`wp10-audit`)

**Basic level, as agreed**: findings and a readable document. **No prune, no score, no JUnit/SARIF** yet (WP18).

`audit(parser) -> DataFrame` (the findings frame from package D, scope `workbook`) and `py-tbparse audit WORKBOOK
[--format ..] [--fail-on ..] [--only ..] [--skip ..]`. Rules (stable ids `A001`...; each with test, corpus run, fix text):
- A001 calculated field used by nothing (reuse `usage.field_usage`), info;
- A002 duplicate calculations (same normalised formula: strip whitespace and comments, case-fold keywords), warning;
- A003 calculation references a field that does not exist (`usage.missing_references`), error;
- A004 circular dependency between calculations (build the graph from `usage.py`'s reference extraction), error;
- A005 parameter used by nothing, info;
- A006 worksheet in no dashboard (and not hidden), info;
- A007 custom SQL present (list each: datasource, first 80 characters), info;
- A008 extract or absolute-path leftovers in connections, info;
- A009 calculations with Tableau's default names (`Calculation_123456`), info;
- A010 deeply nested calculations (depth over 5), info; A011 very long formulas (over 1000 chars), info.
Decide and **document the semantics of "used"** (field_usage's own: sheets, dashboards, other calculations, sets,
groups, bins; parameters are *not* followed, a known gap in `docs/next-steps.md` section 5 -- fix that gap here or
list it in the rule's fix text).

**Data dictionary** (`py-tbparse docs WORKBOOK [-o out.md] [--graph]`, `docgen.workbook_markdown(parser)`): overview
(name, version, counts), datasources with connections (no secrets) and their tables, a **fields table** (name, caption,
type, role, formula, "used by": sheets/dashboards/calculations), parameters, worksheets, dashboards with their sheets,
a "where used" index, and optionally the relationship graph as a fenced DOT block (reuse `graph.to_dot`).
Deterministic order, escaped pipes and newlines in formulas, truncated long formulas with the full text in a
collapsible block, non-Latin text intact. Share the renderer with `template show --markdown`.

**Tests.** every rule with a minimal synthetic workbook (passing and failing); corpus: no crash on 200, ordering
deterministic (run twice, compare), the docs render for all 200 and are valid Markdown tables (count `|` per row);
snapshot of the docs for one fixture.

## 6. Versions, landing and the PRs

- **Versions: see "Versioning" in `AGENTS.md`** (2026-10-05), which supersedes the 2026-10-04 rule of a patch release
  per package from 0.4.7. Still current: **no version bump inside a PR** (the version in `pyproject.toml`, which
  `__version__` reads back, is bumped for a release, not by a package PR); a release only on the owner's explicit
  word.
- **One PR per package** (answered), off `origin/main`; run the whole non-browser suite, and the browser suites when
  page code or `webgui.py` changed, before the PR. Squash-merge is what the owner uses; web-UI squash merges are
  authored "Dan", not DDSNA (open, section 7). `main` had no branch protection when checked on 2026-10-04.
- Release notes followed a local file of the author's (`release-0.4.5.md`, not in the repo);
  the pre-release checklist is in `AGENTS.md` (build the wheel, install it in a throwaway
  venv, run `py-tbparse --help` and `py-tbparse-gui --help`, run pytest against an extracted sdist). A release is the
  owner's call, never yours. The `excel` extra and `openpyxl` in `[test]` are new in `pyproject.toml`: the wheel
  smoke test must also run with openpyxl **absent** (the Excel tests skip, the hint message appears).
- PR comment style: meaningful, human, no generic AI tone (memory note `pr-comment-style`).

## 7. Questions for the owner (do not decide these)

1. ~~Sample workbooks~~ answered: none (section 2).
2. ~~Landing~~ answered: one PR per package. ~~The 0.5.0 conflict~~ answered 2026-10-05: see "Versioning" in `AGENTS.md`.
3. ~~`.xls`~~ answered: refused unless small effort (section 2).
4. Tableau checks, only he can do them, the files come from `python scripts/make_verification_pack.py <new folder>`:
   `4-template-on-excel.twbx` (written, not yet opened), later `5-template-on-db.twbx`; a template over several tables;
   the plain object-model form (corpus example `AlexAlkhatib__alex-the-analyst__Classeur.twb`); file 1 (renamed) with
   its data reachable. Record results in the Status section of `docs/verify-in-tableau.md`. The GUI Templates view
   (WP9) stays gated on these.
5. Package C: are **worksheet/dashboard names** as token locations wanted (costs a reference rewrite) or are titles,
   captions, text and parameters enough?
6. Package F: when "basic" is done, does he want `prune` (hide unused fields) next, or WP18 CI formats?
7. Merged branches still on origin (`wp3-template-update`, `fix-tokens-24-27`, `fix-check-engine`, on 2026-10-05; the
   others of 2026-10-04 are gone), and the shared checkout and venv updates (`git pull --ff-only`,
   `.venv/bin/pip install -e .`): his to do or to allow.
8. Release and CI setup (record only; no workflow change without his word): branch protection / required CI checks on
   `main` (none when checked on 2026-10-04); the Docker publish job uses the `release` environment and runs without
   manual approval; both `release.yml` and `docker-publish.yml` fail when the tag differs from `pyproject.toml`
   (#38); `docker-publish.yml` has never run; the GHCR package is set public after its first push; web-UI squash
   merges are authored "Dan", not DDSNA.

## 8. Known gaps carried forward (do not forget, do not hide)

- Nothing written for Excel, databases or tokens has been opened in Tableau; only CSV and workbook-backed outputs have.
- `check_data` reads values only from a CSV (not Excel, workbook, target); say so in its output instead of "nothing found".
- A template over several tables is unproven for CSV, Excel and targets (a single object is written).
- `explain` and `broken_sheets` do not follow parameters; `field_usage` missed a set dependency in `filtering.twb`
  (see `docs/next-steps.md` section 5).
- WP4: `--workers` uses a process pool; on Windows (spawn) the job dicts are picklable by construction but untested there.
  The sidecar's `file` must match by name or relative path; a folder with sub-directories is not scanned recursively.
- WP3: a workbook made from several datasources is refused by `template update`; stage C (merge) is not built.
- The answers now keep a copy of the template manifest (`answers.template.manifest`): answers files are larger and
  contain field names and connection facts (no credentials); do not log them in public places.
- `tests/test_version.py` fails on a branch whose version differs from the shared venv's editable install: not a bug.
- Tokens do not cover worksheet/dashboard names, parameter captions or default filter values (question 5). The T009
  token rule exists (#42).
- CI on `main` (`4a3cfff`, run 37229010116, attempt 1): Windows / Python 3.12 failed once in
  `tests/test_webgui.py::test_load_requires_json_content_type[text/plain]`, a server race; it passed on the re-run.
  #35 drains the request body before an early refusal; not re-checked on CI here.
- Answers and credentials: a parameter or token value is saved as typed and never scanned, and `make_template` blanks
  only the `username` and `password` attributes of `<connection>` elements (see `docs/templates.md`).

## 9. Checklists

**Starting a package.** Read sections 0 and the package's own section; `git fetch`; `git worktree add -b NAME
.claude/worktrees/NAME BASE` (BASE = `origin/main`) and `EnterWorktree path=...`; `python3
scripts/fetch_corpus.py` if `tests/corpus/files` is empty; baseline `PYTHONPATH=. <venv python> -m pytest -q <files you
will touch>`; write the failing tests first.

**Finishing a package.** All new tests plus the corpus twin pass; the whole non-browser suite passes (background, log);
docs (`docs/templates.md` or the package's doc), CLI `--help`, `AGENTS.md` module table, `docs/next-steps.md` state
table, this file's section 1 and 3 updated; no version bump; commit as DDSNA with no attribution; check the author and the
message; **stop**: report what was verified and what was not, and the next command. Push, PR and merge only when told.
