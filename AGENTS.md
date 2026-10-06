# AGENTS.md

## What this is

`py_tbparse` is a native Python port of the R package
[`twbparser`](https://github.com/PrigasG/twbparser) (mirrored at
`DDSNA/twbparser`): it parses Tableau `.twb`/`.twbx` workbook files into
`pandas` DataFrames. Pure `lxml` XML parsing — no R runtime, no `rpy2`.

Current scope is a **v1 subset** of the original R package's ~50 exported
functions. Ported: workbook loading (`.twb`/`.twbx`), datasources,
parameters, raw/calculated fields, joins, relationships (legacy `<relation
type="join">` and 2020.2+ `<relationships>`), inferred relationships,
dashboards/dashboard-sheets, `validate_relationships`, custom/initial SQL,
and published-source detection. **Not yet ported** (v2): formatting,
tooltips, colors, axes, sorts, dashboard layout/actions, analytics
helpers (calc complexity, replication brief), and the
Shiny-inspector equivalent.

Also added, with no R equivalent (Python-native extras -- see "Non-R
modules" below): Graphviz DOT export of the relationship graph
(replaces the R package's igraph/ggraph-based plotting with a
dependency-free alternative), workbook-to-workbook diff, folder/batch
analysis across many workbooks, field renaming, field usage, workbook
templates, and Jupyter rich display.

## Setup

No system-wide `pip`; use the project venv.

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[test]"     # includes openpyxl, for the Excel tests (tests/test_excel.py skips without it)
```

## Build / test / lint commands

```bash
.venv/bin/python -m pytest -q          # run the full test suite
.venv/bin/python -m pytest -q tests/test_joins.py   # single file
.venv/bin/python -m py_compile py_tbparse/*.py     # syntax check
```

Browser (GUI) tests need a one-time setup; without it they skip and the
rest of the suite still runs:

```bash
.venv/bin/pip install -e ".[browser]"
.venv/bin/playwright install chromium
./scripts/setup-browser-libs.sh        # only on a machine without root
.venv/bin/python -m pytest -q tests/test_gui_browser.py
```

There is no linter/formatter configured yet — match existing style
(no trailing comments unless explaining non-obvious behavior, type hints
via `from __future__ import annotations`).

## Server mode / Docker

`Dockerfile`, `docker-compose.yml` and `docs/deployment.md` run the GUI behind a TLS-terminating proxy. The
app side is `webgui._CONFIG` (`--server-mode`, `--allowed-host`, `--trust-proxy`, `--max-sessions`,
`--session-ttl`, each with a `PY_TBPARSE_*` env var). Rules to keep:

- `_STATE` and `_UPLOAD` are `_Scoped` mappings: in server mode they read the current request's session
  (a thread-local set by `Handler._bind_session`), otherwise the one global dict. New per-user state goes in
  `_STATE_DEFAULTS` / the session dict, never in a new module-level global, or users will see each other's data.
- Origin checks go through `_origin_ok()`, not an inline comparison. POST routes are listed in `_UPLOAD_ROUTES`,
  `_PATH_ROUTES` and `_JSON_ROUTES`; every route in `_PATH_ROUTES` (`/load`, `/create-workbook`, `/template/open`,
  `/template/open-data`, `/template/save`) stays refused in server mode (they touch the server's disk), and no
  other route may take a path from its body. Every refusal before the body is read goes through `_refuse_post`.
- The Templates view's endpoints (`/template/*`, built on `template_gui.py`) keep their state in
  `_STATE["tpl"]` (one template slot, one data slot, one output, in a per-session temp folder deleted by
  `_drop_session`). Their JSON bodies are capped at `MAX_JSON_BYTES`, accept only the keys in `_TEMPLATE_KEYS`,
  and every answer goes through `_scrub()`, so no server temp path reaches the page. `POST /template/make`
  (`{name, description}` only) writes `make_template` output into the session folder (`made`, one at a time; the file
  name comes from `_template_file_name`, never a path from the page) and is allowed in server mode, because it takes
  the open workbook and no path; `POST /template/use-made` copies it into the template slot; `GET /template/made`
  downloads it. `/template/state` also says which workbook is open (`workbook`, a file name) and what was made.
- A POST handler that refuses a request before reading its body (wrong host, origin or content type, unknown
  path) must drain the body first with `Handler._drain(length)` (`_refuse_post` does it). Answering and closing
  while bytes still arrive can make the client, Windows in particular, see a connection reset instead of the
  error message (#35). A body over the drain limit is not read; the connection is closed instead.
- Tests: `tests/test_server_mode.py` (HTTP) and `tests/test_gui_server_mode.py` (Chromium); the `docker` CI job
  builds the image and drives it like a proxy. There is no Docker daemon in the usual sandbox, so the image
  itself is only built in CI.

## Release / packaging

```bash
.venv/bin/pip install -e ".[dev]"     # build + twine
rm -rf dist build py_tbparse.egg-info
.venv/bin/python -m build              # produces dist/*.whl and dist/*.tar.gz
.venv/bin/twine check dist/*           # validates metadata/README rendering
```

Version is single-sourced from `pyproject.toml`'s `[project].version`;
`py_tbparse.__version__` reads it back via `importlib.metadata` at
runtime (see `__init__.py`), so don't hardcode a second copy.

Before bumping the version for a release: bump `version` in
`pyproject.toml`, then rebuild and smoke-test the wheel in a
throwaway venv (`pip install dist/*.whl`, run `py-tbparse --help` and
`py-tbparse-gui --help`, run pytest against an extracted sdist) — this
catches packaging bugs (missing files, wrong entry points) that an
editable install won't.

CI (`.github/workflows/ci.yml`) runs pytest across Python 3.9–3.13, runs
the browser GUI tests in real Chromium (`gui` job), and builds+checks the
distribution on every push/PR. `build` depends on both `test` and `gui`
— don't drop `gui` from `build`'s `needs`, or a broken-page build can
succeed and publish an artifact while the one job that would have caught
it fails off to the side. Release
(`.github/workflows/release.yml`) publishes to PyPI via trusted
publishing (OIDC, no stored token) when a GitHub Release is published —
this needs to be configured once on the PyPI project's "Trusted
Publishers" settings page before the first release, and needs a
`release` GitHub Environment created in repo settings. It also fails
(before the tests) if the release tag, minus the `v`, differs from
`pyproject.toml`'s version (#38).

`.github/workflows/docker-publish.yml` (same trigger) builds the `Dockerfile`, checks that it starts and answers
`/healthz`, and pushes `ghcr.io/ddsna/py-tbparse:<version>` (tag minus the `v`; `latest` only for non-pre-releases)
with `GITHUB_TOKEN`. It fails if the release tag differs from `pyproject.toml`'s version. It does not depend on the
PyPI job (the image is built from the checkout). It uses the `release` environment and runs without manual
approval. It has not run yet; the first release will be its first test.

## Versioning

The owner's policy (2026-10-05); older statements in other docs are superseded by it:

- 0.5.0 is the first templating release. It is cut only on the owner's explicit word, after the token and
  `template check` fixes, a full corpus run and the browser suites.
- Later templating releases are 0.5.x.
- 0.4.x stays reserved for UI-redesign releases.
- No version bump inside a PR; the version is bumped for a release.
- **Hotfixes are `.postN` releases: `x.x.x.postN`** (owner, 2026-10-06), for example `0.5.2.post1` is the first hotfix
  of 0.5.2. A hotfix is a fix to something already released, with no new feature; a feature or a changed CLI, API or
  rule id is a normal patch or minor. The owner first wrote "x.x.x.hotfix": a literal `.hotfix` suffix is not valid
  PEP 440 and PyPI would refuse it, so the owner chose `.postN`. The hotfix PR changes only `pyproject.toml` like any
  release, the tag is `v0.5.2.post1`, and the release workflows accept it because they compare the tag with
  `pyproject.toml` as text (not tried end to end). Cut it only on the owner's explicit word. The next normal release
  (0.5.3) goes on top, never from the hotfix branch. Fixes merged to `main` that are not released are not hotfixes:
  they ship in the next normal release unless the owner asks for a hotfix.

### Release rules

These add to the steps above; practices were collected from popular release and git skill files on 2026-10-05
(`handover-issues/AGENTS-RELEASE-PROPOSAL-2026-10-05.md`, a judgment sample read through a summarising fetch tool, so
treat the sources as unverified). Owner rules are marked (owner).

- **Merged is not released.** A release is cut only on the owner's explicit word. (owner)
- **Agents never publish a release, push to `main`, force-push or merge.** An agent prepares the PR; the owner
  merges it and publishes the GitHub Release. (owner)
- **The release commit changes only `pyproject.toml`**; there is no `CHANGELOG.md`, so the notes go in the PR and the
  GitHub Release body. Start from a clean `main` that matches `origin/main`.
- **Pick the bump from the change, not the calendar.** While we are 0.x, a breaking change to the CLI, the Python
  API or a stable rule id needs a new minor, and the PR says so.
- **Check CI on the exact release commit** (`test`, `gui`, `build`, `docker`), not from memory of an earlier run.
- **Release notes**: one short entry per user-visible change, grouped Added / Changed / Fixed, written for someone who
  runs the CLI or the GUI. Leave out tests, CI and pure refactors. Edit by hand, do not paste the commit log, and link
  only issues and PRs that exist.
- **The release PR states what is not verified** (an agent never opens generated workbooks in Tableau; the Docker
  image is built only in CI) **and how to undo it**: yank on PyPI, delete the GHCR tag, ship the next patch. PyPI
  files cannot be replaced.
- **After the owner publishes, an agent only reads**: check that the `release` and `docker-publish` runs finished and
  that the version and the GHCR tag exist, and report what could and could not be seen. A failed publish job is
  reported to the owner; do not re-run it, re-tag or delete a release.
- **Commits**: no `--no-verify`, no changes to git config; if a hook fails, fix the cause and make a new commit. Read
  `git diff --staged` for secrets, tokens and local paths before each commit. One logical change per commit.

Open owner questions: whether to add a `CHANGELOG.md`, whether to test-publish to TestPyPI first, and whether a hook
should block pushes to `main`.

## Architecture

Each `py_tbparse/*.py` module is a direct port of one R source file in
the upstream package, function-for-function:

| Python module | Ported from (R) | Notes |
|---|---|---|
| `_clean.py` | `R/utils.R` (`.twb_clean_table`, `.twb_clean_field`, `attr_safe_get`, `.strip_brackets`) | Regex-based name cleaners shared by everything else |
| `_xml.py` | `R/utils.R` (`twbx_list`, `extract_twb_from_twbx`, `twbx_extract_files`) | `.twbx` zip handling |
| `datasources.py` | `R/datasources.R` | `extract_named_connections`, `extract_datasource_details`, `extract_parameters`. The Datasources table has one row per logical table of the object graph (per datasource when there is no graph), each tied to the `<datasource>` it sits in (never matched on `primary_table`, never a row for the internal `Parameters` datasource); a value the workbook does not hold reads "not stored in the workbook", never NaN (`connection_id` stays None) |
| `fields.py` | `R/fields.R` | `extract_columns_with_table_source`, `infer_implicit_relationships` |
| `calculated_fields.py` | `R/calculated_fields.R` | `extract_calculated_fields`, `extract_raw_fields` |
| `joins.py` | `R/joins.R` | `extract_joins` (legacy `<relation type="join">`) |
| `relationships.py` | `R/relationships.R` | `extract_relations`, `build_object_table_mapping`, `extract_relationships` (2020.2+ model) |
| `dashboards.py` | `R/dashboard_details.R` (subset) | `list_dashboards`, `dashboard_sheets` |
| `validators.py` | `R/validators.R` | `validate_relationships` |
| `sql.py` | `R/sql.R` | `extract_custom_sql` (`twb_custom_sql`), `extract_initial_sql` (`twb_initial_sql`) |
| `published.py` | `R/published.R` | `extract_published_refs` (`twb_published_refs`) |
| `parser.py` | `R/twb_parser.R` (`TwbParser` R6 class) | The `TwbParser` façade tying every module together |

`parser.py`'s `TwbParser.__init__` mirrors the R6 constructor: it eagerly
computes every cached DataFrame, guarding each with `_safe_call` (the port
of R's `safe_call`/`tryCatch`) so a malformed workbook degrades to empty,
correctly-columned DataFrames instead of raising.

### Non-R modules

These have no upstream R source to track — they're either the
Python-native user-facing layer on top of `TwbParser`, or features added
beyond the R package's scope:

| Python module | What it is |
|---|---|
| `_tables.py` | Name → `TwbParser`-accessor registry shared by `cli.py`, `webgui.py`, `diff.py`, and `batch.py`. Adding a new extractor to `TwbParser`? Add it here too so it's automatically available everywhere else. |
| `cli.py` | `py-tbparse` command-line entry point, plus the `diff`/`batch`/`rename`/`template`/`library`/`style`/`audit`/`docs` (`dictionary`) subcommands (dispatched on `sys.argv[1]` before the normal single-workbook argparse parser runs) |
| `webgui.py` + `webui/` | `py-tbparse-gui`: stdlib-only (`http.server` + vanilla JS) local browser GUI, no GUI toolkit dependency. The server is `webgui.py`; the page is `webui/` (`index.html`, `tokens.css`, `themes.css`, `app.css`, `table.js`, `graph.js`, `rename.js`, `app.js`). Loosely fills the role of the R package's `run_twbparser_app`/Shiny inspector. |
| `graph.py` | `to_dot()`: Graphviz DOT export of joins/relationships (+ optional inferred, as dashed edges); `graph_data()` is the same edges as plain data, which the GUI lays out and draws itself (`webui/graph.js`: layered layout, SVG, pan/zoom, keyboard). Replaces the R package's igraph/ggraph-based `plot_dependency_graph`/`plot_relationship_graph` with a dependency-free text format any Graphviz-compatible tool can render. |
| `diff.py` | `diff_tables()`/`diff_workbooks()`: row-level added/removed diff between two workbooks' same-named table, via `_tables.TABLE_SPECS`. No "changed" classification without a natural key — a changed row shows as one removed + one added row. |
| `rename.py` | `suggest_field_renames()` (clean-name suggestions, optionally matched against a "before" reference), `suggest_renames()` (the same for every kind of object: field, parameter, worksheet, dashboard, datasource, folder, hierarchy; adds a `kind` column), `load_rename_mapping()` (read an edited CSV back), `compare_field_schemas()` (fields with no counterpart across a datasource switch) and `apply_field_renames()`/`build_renamed_workbook()` (write a copy with captions set; never overwrites). Also the `field-renames` and `report-renames` tables in `_tables.py`. A worksheet/dashboard rename must rewrite every reference (`_SHEET_REFERENCES`); if you learn of another place Tableau writes a sheet name, add it there. |
| `report.py` | `workbook_report()`: the overview's report card (summary sentence, health checks, dashboards with their sheets) built from `validate_relationships`, `field_usage` and `usage.missing_references`. Every health item names the table and column filters that list exactly the rows it counted; a test keeps count and rows equal on all 200 corpus workbooks. |
| `usage.py` | `field_usage()`: for every field, the worksheets, dashboards and calculations that use it, followed through calculations, groups/sets and bins (the `field-usage` table). Python-native rather than a port of the R package's field-usage helper. |
| `templates.py` | Workbook templates. `make_template()` writes a `.twbx` with a `template.json` manifest (required fields from `usage.py`, parameters, connections; extracts and packaged data stripped; the `username` and `password` attributes of every `<connection>` element blanked, and nothing else scanned for secrets: a server name, custom SQL or a calculation is kept as written); `read_data()` describes new data (CSV; one sheet of an `.xlsx`/`.xlsm` via the optional `openpyxl`, imported lazily; a `*.target.json` for a database table, see `connections.py`; or a `.twb`/`.twbx`/`.tds`); `suggest_mapping()` pairs fields with columns (reuses `rename._match_key`, type checks against the field's *physical* type, `datatype-customized` fields keep their type); `apply_template()` replaces the datasource's connection, keeping every field's local name, sets parameters and stores `template-answers.json`. `_file_connection()` builds both file connections: `_csv_connection` (`textscan`) and `_excel_connection` (`excel-direct`: relation `[Sheet$]`, `gridOrigin`, the Excel driver's remote types in `_EXCEL_REMOTE_TYPE`, all measured from the corpus; the answers keep `data.sheet`). A file connection is written in the 2020.2+ object-model shape when the template uses it, in the template's own dialect (`_object_model()`: *prefixed* `_.fcp.ObjectModelEncapsulateLegacy.*` tags with both relations, or *plain* `<object-graph>`/`<column datatype='table'>`; both occur at version 18.1) -- object graph, table column and `object-id` per record, keeping the template's object id (worksheets name the table column by it) and placing the table column after `<aliases>`; keep those in step if you touch one. Opened in Tableau once for one workbook shape (see `verify.py`, `docs/verify-in-tableau.md`). Manifest version 2 adds a template `id`/`revision` and a `uid` per field (`field_uid()`: datasource, local name, role, type; a caption change keeps it); version 1 still loads (`_fill_version_1`). Answers version 2 (`load_answers`, `resolve_apply` -> `ApplyPlan`, which `apply_template` and the CLI both use) hold per-datasource entries, `profiles` and a schema fingerprint; precedence is explicit argument, then profile, then saved answers, and `_reject_credentials` refuses a `password`, `username`, `token` or `secret` key in answers, except under `parameters`, `mapping` and `tokens`, whose keys are names the user chose and whose values are never scanned. A parameter or token value is saved as typed, so never pass a password as one. `check_data()` (findings on the data, never blocking) and `explain()` (every consequence besides the connection; `broken_sheets()` is its short form) report before an apply. `DataSource.column()` maps a mapping's trimmed column name back to the data's real one. Zip members are written with a fixed timestamp so the same inputs give the same bytes (tests rely on it). |
| `verify.py` | `validate_workbook()`: dangling-reference checks on the XML (`sheet-field`, `calc-reference`, `dashboard-sheet`, `window-name`, `local-type`, and for text files `remote-name`/`remote-type`; one row per finding). Judge a written workbook by what it has that its input did not: real workbooks have findings of their own. Not a claim that Tableau opens the file. |
| `connections.py` | The registry of database connection classes (`CLASSES`: `mysql`, `postgres`, `sqlserver`, `snowflake`) and `load_target()` for the target files that describe a table in one (`"format": "py-tbparse-target"`). **Data first, copied from the corpus** (`scripts/survey_connections.py`; `tests/test_targets.py` checks the table against it and compares our connection with Tableau's for every table it can): the named connection's attributes in Tableau's order (never `username`/`password`; a target file or answers holding credentials are refused), the relation's `table` form (`[t]`, `[schema].[t]`, Snowflake `[db].[schema].[t]`), which classes write `DebugRemoteType`/`DebugWireType`, and remote-type codes per SQL type *family*, each `measured` or borrowed from a sibling class (`remote_type()`; borrowed ones are reported as `unverified_types`). `evidence` is `corpus`, `sample` or `docs`; a `docs` class refuses without `experimental=True`. Add a class only from a workbook Tableau wrote (Oracle, Spark, Databricks, Mongo, `sqlproxy` are not in the corpus). The writer is `templates._db_connection` on `_file_connection` (a database relation has no `<columns>`, ordinals count from 1). |
| `schema.py` | SQL-type schemas: `sql_family()`, `sql_to_tableau_type()` (arguments, case and spacing ignored; `numeric(p,0)` is an integer; unknown types are strings with a warning), `parse_ddl()` (one `CREATE TABLE`, a documented subset, errors name the line; a backslash in a string is plain text, and only a statement that fails that way is read again with MySQL's `\'` escape) and `read_schema()` (JSON list or DDL file). Reused by connection targets and, later, fake data (WP12). |
| `tokens.py` | Template tokens (`{{name}}`, escapes `{{{{` and `}}}}`): `places()` finds every piece of text that can hold one (worksheet and dashboard titles, dashboard text zones, field and datasource captions with the copies in `datasource-dependencies` and worksheet datasource references, string-parameter value + `calculation/@formula` mirror + members/aliases, which are Tableau string literals so a `Place` has `quoted`), `declared()` lists the tokens with `where`, `expand()`/`render()` fill them in one pass (a value is never expanded again), `formula_hits()`/`broken_hits()` feed the warnings of `make_template`. Never a blind replace over the XML and never inside a formula. The manifest key `tokens` is additive and present only when some place has token syntax (so every workbook without it is untouched byte for byte); `templates._fill_tokens` applies it (precedence: explicit, profile, answers, default; missing -> `TemplateError` listing the places); answers keep `tokens` (a free key: neither its names nor its values are scanned for credentials); `template_update` has `kind=token` rows and `needs-value`; `read_inputs` takes token names as sidecar columns. |
| `findings.py` | The shared findings engine: `@rule(id, scope, severity=, fix=)` registers a function that yields `finding(object, detail)` rows for a `Subject` (parser and/or template); `run_rules(subject, scope, only=, skip=)` returns the sorted, deterministic frame (`FINDING_COLUMNS = rule, severity, object, detail, fix`); `format_findings` goes through the `FORMATS` registry (`table`, `csv`, `json`; WP18's JUnit/SARIF/GitHub formats are more entries); `exceeds`/`summary` serve `--fail-on`. **Rule ids are stable: never renumber or reuse one** (people put them in CI configs). A rule that raises becomes one `error` finding (path-scrubbed) and is listed in `df.attrs["crashed"]` with its traceback in `df.attrs["tracebacks"]`; `only`/`skip` take a list or one id as text, an empty `only` or a selection that leaves no rule is a `ValueError`; the csv format guards against spreadsheet formulas. WP10's audit (`workbook_audit.py`, scope `workbook`, ids A001+) reuses it. |
| `template_check.py` | `check_template()` (CLI `template check`): the template rules T001 to T010 (hard-coded connection: server/database, or an absolute file path, read from the manifest and the workbook; version 1 manifest; parameter values; several tables; packaged data; unused fields; dangling references via `validate_workbook`; literals in calculations (never echoed: kind, `***`, length); tokens (T009: declared without default, token in a formula, broken `{{` syntax, from `tokens.py`'s `formula_hits`/`broken_hits`); no description/name). Exit codes of the CLI: 0, 1 finding at `--fail-on`, 2 unreadable template or bad option (`--only ' '` is one), 3 a rule crashed (`df.attrs["crashed"]`, traceback on stderr). `RESERVED` is empty: put an id there to keep a number for a rule not written yet. Add a rule as one more `@rule("T0xx", "template")` function and add the id to the list in `tests/test_template_check.py`. `safe_connection()` (in `templates.py`) is the allowlist for printing a connection (T001, `docgen`). `rules_help()` feeds the CLI help. |
| `docgen.py` | A generic Markdown renderer (`escape_cell`, `inline_code`, `heading`, `code_block`, `md_table`, `render`; deterministic; `escape_cell` escapes pipes, newlines, `<`, `&`, backticks, brackets and line-start `#`/`-`/`+`/`=`/numbers so untrusted workbook text cannot open a fence, heading, link or image; `clip` caps descriptions) and `template_markdown()` (CLI `template show --markdown`). `workbook_markdown()` is the workbook data dictionary (WP11 basic; CLI `docs`/`dictionary`, doc `docs/audit.md`): the same functions, and `_connection_text` (the `safe_connection` allowlist) shared with `template_markdown`; formulas are cut at 120 characters in the table with the full text in a `<details>` block; the page is deterministic and never prints a folder or SQL text. |
| `workbook_audit.py` | The workbook audit (WP10 basic; CLI `audit`, `audit(parser_or_path, only=, skip=)`, doc `docs/audit.md`): rules A001 to A011 registered with the findings engine in the scope `workbook` (unused calculation, duplicate calculation by `normalise_formula`, missing reference via `usage.missing_references`, circular dependency (iterative Tarjan), unused parameter, worksheet in no dashboard, custom SQL, absolute-path leftovers of file connections and extract files, never an extract alone, default names, nesting depth over 5, formula over 1000 characters). Ids are stable like the T-series; add a rule as one more `@rule("A0xx", SCOPE)` function and its id to `tests/test_audit.py`. `_Facts` computes what the rules share once per run. A005 follows parameters through formulas itself because `usage.field_usage` does not (it reads references from a set, losing the order of `[Parameters]` and the name after it). Exit codes of the CLI are those of `template check`. Not built: `prune`, a score, JUnit/SARIF (WP18). Nothing is opened in Tableau. The module is not called `audit.py` because `py_tbparse.audit` is the function. |
| `template_gui.py` | The service layer of the GUI's Templates view (no HTTP, no state; WP9 9a): `template_summary()`, `data_summary()`, `excel_sheets()`, `tableau_datasources()`, `column_choices()`, `mapping_frame()`, `plan()`, `output_data_path()`, `apply()`. Takes loaded `Template`/`DataSource` objects, returns plain dicts and lists `json.dumps` accepts, caps tables at `_CAP` rows, and turns a person's mistake into a message in `problems` instead of an exception. `webgui.py`'s `/template/*` endpoints call it, and `webui/templates.js` draws the answers. It calls the template API with keyword arguments only. |
| `template_update.py` | `diff_template_revisions()`, `template_update_report()` (stage A: a newer template revision against the answers a workbook kept, impact per change) and `update_from_answers()` (stage B: re-apply with those answers, stop on `needs-mapping`). The "before" is `answers["template"]["manifest"]` (a snapshot `apply_template` writes, with `data.columns`), or `old=`. Three-way merge is not built; it needs a design note and the owner's go. |
| `template_batch.py` | `apply_template_folder()` (CLI `template apply-folder`): one workbook per data file in a folder, a `summary.csv`, a sidecar CSV (`read_inputs`: `file`, `sheet`, then one column per parameter caption or declared token) for per-file values, and a tolerance gate (`min_mapped`; default all required fields must map). Each file runs `resolve_apply` + `broken_sheets` + `apply_template`; a bad file is a summary row, never an exception (except `on_error="stop"`). `workers>1` uses a process pool, so jobs carry the template *path*, not the loaded template. |
| `library.py` | Calculated-field and parameter libraries (WP6 first slice; CLI `library export/show/import`, doc `docs/libraries.md`, design `docs/wp6-library-design.md`). `export_library()` reads `<column><calculation class='tableau'>` and the `Parameters` datasource into a `py-tbparse-library` dict (`save_library`/`load_library`, version 1); `plan_import()` decides per entry (`skip-identical`, `add`, `add-renamed`, `skip-clash`, `fail-unmapped`, `fail-dependency`) and `build_imported_workbook()` carries the plan out. Formulas are rewritten with `rewrite_formula()` on `usage._code_ref_spans` (string literals are skipped; never use the `_refs` regex for this). Required fields go through `templates._match_fields` (the body of `suggest_mapping`). Corpus-measured shapes differ from the design doc in one place: `<table-calc>` is a child of `<calculation>`, not of `<column>`. Not covered: sets, groups, bins, `overwrite`, folders on import, cross-datasource calculations, the GUI. Never opened in Tableau; keep saying so. |
| `style.py` | Colour palette library (WP7 slice 1; CLI `style show/export/import/check`, doc `docs/styles.md`, plan `docs/wp7-style-plan.md`, evidence `docs/style-model.md`). Reads `/workbook/preferences/color-palette` from a workbook, a `Preferences.tps` (hardened parser: no entities) or a `py-tbparse-style` v1 JSON; `_plan()` decides every palette first (`add`, `skip-identical`, `skip`, `rename`, `replace`, `invalid`, `fail`), `build_with_palettes()` writes only `<preferences>` and keeps everything else; workbook output goes through `rename._serialize_workbook`. Owner decisions 2026-10-06: default clash policy `fail`; output is always a new file, never over the input or an existing `Preferences.tps` (no in-place flag). Adds palettes to the picker only; marks are never recoloured. Never opened in Tableau; keep saying so. |
| `batch.py` | `scan_folder()`: runs one table across every `.twb`/`.twbx` in a directory, concatenated with a `workbook` column. Skips (with a warning) any file that fails to load/extract rather than aborting the batch. |

## Porting conventions (read before adding/modifying a function)

1. **Go to the R source first.** Fetch the corresponding file from
   `github.com/DDSNA/twbparser` (or `PrigasG/twbparser`, same content) via
   the GitHub API/raw URLs — don't guess at Tableau XML schema from
   memory. Port the XPath expressions and fallback logic as literally as
   possible; deviations from the R behavior are bugs, not improvements.
2. **XPath parity**: `lxml`'s XPath 1.0 engine supports the same
   functions R's `xml2`/libxml2 use (`local-name()`, `contains()`,
   `count()`), so most R XPath strings can be copied verbatim into
   `.xpath(...)` calls.
3. **Empty-input contract**: every extractor returns an empty DataFrame
   with the *correct columns* (not just `pd.DataFrame()`) when there's no
   matching XML — callers (esp. `parser.py`) rely on this. Each module
   exposes its column list as a `_XXX_COLUMNS` constant (e.g.
   `joins._JOIN_COLUMNS`, `datasources._DATASOURCE_COLUMNS`) precisely so
   `parser.py`'s `_safe_call` fallbacks can reuse it instead of retyping
   the list a second time (which drifted out of sync once already).
4. **Cleaning helpers**: always route table/field name cleanup through
   `_clean.clean_table` / `_clean.clean_field` / `_clean.strip_brackets`
   rather than re-deriving regexes inline. Same for "is this value
   missing" checks — use `_clean.is_missing(x)`, not a hand-rolled
   `pd.isna()`/`isinstance(x, float)` check (its edge cases, like NaT or
   array-likes, are easy to get subtly wrong per call site).
5. **No R dependency, ever.** If a future port needs something R gets
   from `dplyr`/`igraph` for free (e.g. graph layout for
   `plot_dependency_graph`), find a pure-Python equivalent or scope it
   out — don't reach for `rpy2`/subprocess-to-R.
6. **XPath string literals**: never build one with
   `f"...='{value}'"` or a `.replace("'", "")` — user/workbook-controlled
   values (a dashboard name, say) can contain `'`, `"`, or both, and
   XPath 1.0 has no in-literal escape character. Use
   `dashboards._xpath_string_literal(value)` (or extend it if a new
   module needs the same thing), which picks a quoting style or falls
   back to `concat()` as needed — verified against real `lxml` evaluation
   for the tricky cases (leading/trailing/consecutive quotes, both quote
   types at once).

## Testing conventions

- Fixtures live in `tests/fixtures/` (`test_for_wenjie.twb`,
  `test_for_zip.twbx`) — pulled directly from the R package's
  `inst/extdata/`. Don't regenerate/hand-edit them; if a new fixture is
  needed, pull it from upstream the same way, or build a minimal
  synthetic XML snippet (see `tests/test_joins.py`,
  `tests/test_dashboards.py` for the pattern — many are lifted from the R
  functions' own `@examples` roxygen blocks).
- `tests/corpus/` is 200 real workbooks (permissive licences, pinned by blob sha in
  `manifest.csv`, licence texts in `licenses/`). The files are gitignored; fetch with
  `python scripts/fetch_corpus.py`. `tests/test_corpus.py` skips without them. Run it when you
  change anything that reads workbook XML: it found a Unicode matching bug the hand-made
  fixtures could not. Add to the corpus only from repositories whose licence permits
  redistribution, and record the licence text.
- `tests/conftest.py` provides `wenjie_xml`, `wenjie_path`,
  `zip_twbx_path` fixtures and an `xml_from_string()` helper. Tests import
  it with `from conftest import xml_from_string` (no `tests/__init__.py`,
  so it's a plain top-level import, not a relative one).
- **Anything that writes a workbook** (rename, template, whatever comes next) must pass the differential checks in `tests/test_schema.py`: no schema error and no `validate_workbook` finding that the input did not already have. `tests/schema_check.py` validates against Tableau's published XSD (`tests/schemas/`, Apache-2.0, 2026.2, with two small stubs for the namespaces it imports without a location); real workbooks mostly fail that schema already, so never assert "valid", only "nothing new". The corpus run in that file found three bugs the hand-made fixtures could not. `scripts/make_verification_pack.py` makes the files for the manual Tableau check.
- Every new extractor function needs: one test against a real fixture (if
  it exercises fixture data) and/or one synthetic-XML test for edge
  cases the fixtures don't cover (empty input, fallback paths).
- When in doubt about expected output, that's a signal to install R +
  the `twbparser` package and diff against the real function's output on
  the same fixture, rather than guessing.

### Testing the GUI

`tests/test_webgui.py` drives the HTTP endpoints directly — it never
executes the page's JavaScript. That blind spot shipped a real bug: a
`SyntaxError` in the inline `<script>` (a `\n` in a non-raw Python
string became a literal newline, splitting a JS string literal across
two lines) killed the entire script, so no handlers bound and the UI was
inert — with the whole suite green.

So: **any change to the page (`py_tbparse/webui/`) needs a browser test**, in
`tests/test_gui_browser.py`, which runs the page in real headless
Chromium via Playwright and fails on any uncaught JS error. The cheap
structural guards in `test_webgui.py` (unterminated string literals,
bracket balance) are a backstop, not a substitute.

The browser suite is split by concern, all sharing the fixtures in `tests/test_gui_browser.py`:
`test_gui_table.py` (windowing invariants, pipeline vs. a Python oracle, a seeded random walk;
`PYTBPARSE_WALK_SEEDS`/`PYTBPARSE_WALK_STEPS` widen it), `test_gui_a11y.py` (roles, keyboard, focus, rendered
contrast in both themes) and `test_gui_layout.py` (no sideways overflow from 320 px up, layout stability).
Design decisions the tests pin: only sorting uses a view transition (Chromium sends clicks to the page root while
one runs); column `MIN_WIDTH` is 80; per-table view settings are keyed by column name; disabled menu items use
`aria-disabled` so they stay focusable.

The page is real files, not a Python string: `py_tbparse/webui/index.html`, `tokens.css` (the design
tokens), `themes.css` (the colour themes), `app.css`, `table.js`, `graph.js`, `templates.js` (the Templates view: `window.TemplatesView = {init, show, hide, acceptDrop, dropHint, getState}`), `rename.js` (rename review in Field renames: `window.RenameReview = {init, load, check, body}`; the checkbox column itself is the `check` option of `VTable` in `table.js`) and `app.js`. They are served by `webgui.py` from a fixed whitelist under
`/static/` (`_ASSETS`), so a request can never reach any other file; add a new asset to
`_ASSETS` and to the `webui/*` package-data (pyproject and MANIFEST.in) or it will not ship.
`index.html` is the only thing that gets server values: `_render_index()` replaces
`<!--APP_CONFIG-->` (now in `<head>`, so the saved theme is on `<html>` before the first paint) with the single
inline `<script>`. Keep it that way (one inline script plus the five external ones, `table.js`, `graph.js`, `templates.js`, `rename.js`, then
`app.js`); a test counts them. `populateTables();` must appear exactly once
in `app.js`, and the structural tests (unterminated string literals, bracket balance) read both served scripts.
Keep apostrophes out of JS strings and comments (the test counts quotes per line).

The Templates view (`#templates`, the Templates button in the top bar) keeps all of its code in `templates.js`, inside one
function so its names cannot clash with `app.js`; `app.js` only has `setTemplatesMode()`, the drop routing (while the
view is open, `TemplatesView.acceptDrop(files, target)` gets the files and the overlay text comes from
`dropHint()`), the `#templates` hash and the `init` call with its helpers. The server keeps the choices
(`/template/state` restores them on a reload); the script only draws them, with `textContent` (never `innerHTML`) and
caps on every list (findings `SHOW_MAX`, columns `COLUMN_CAP`, mapping rows `ROW_PAGE`, dropdown options
`OPTION_CAP`, plan rows `GROUP_MAX`). Step 3 (`#tplBody3`: mapping table, parameters, tokens, plan panel, create) is built once per
chosen template and data (`S.gen`); an edit only changes `S.rv` (edits, params, tokens), asks `/template/plan` after
`PLAN_DELAY` ms with an `AbortController`, and updates rows in place so focus is kept. A mapping `<select>` holds only its
chosen option until it gets focus or pointer-down, and empties on blur. `/template/plan` takes `allow_missing`, so the page
can show what Create anyway would do; `plan()` returns `missing_required` and an `error` on each parameter and token row. Tests: `tests/test_webgui_templates_view.py` (no browser), `tests/test_gui_templates.py`
(Chromium). The "Make a template from your open workbook" section (`#tplMake`, 9e) is drawn by `renderMake()`;
`TemplatesView.refresh()` is how `app.js` tells it a workbook was opened while the view is showing.

`POST /upload` (drag and drop, Open file) takes raw bytes with `Content-Type: application/octet-stream` and the name
in `X-Filename`: neither is CORS-safelisted, so another site cannot send it without a preflight. It streams to a
`mkdtemp` directory, refuses over `MAX_UPLOAD_BYTES` (413) and content that does not match the extension, and keeps
only one upload at a time. An uploaded workbook cannot "create beside the original" (409), only download. `POST /template/upload-template` and
`/template/upload-data` use the same `_upload` with a slot: the template slot takes a `.twbx` only, the data slot
`.csv/.tsv/.txt/.xlsx/.xlsm/.twb/.twbx/.tds` (content checked per extension); tests are in
`tests/test_webgui_templates.py`.

Any server-side value spliced into the page (currently `TABLE_NAMES`, the preloaded workbook path
and the version, all in `_render_index()`'s config script) must go through `_json_for_script()`, not
bare `json.dumps()`. `json.dumps` doesn't escape `/`, so a value
containing the literal text `</script>` closes the script tag early in
the browser's HTML parser — this is real, not theoretical, since the
workbook path is user-controlled input; see
`test_preload_path_cannot_break_out_of_script_tag` for a reproduction.

`scripts/setup-browser-libs.sh` unpacks Chromium's system libraries into
a gitignored `.browser-libs/` instead of apt-installing them as root;
the test fixture picks that directory up automatically via
`LD_LIBRARY_PATH`. It verifies each download against the checksum
`apt-get --print-uris` reports for it (SHA256 if offered, MD5Sum as the
realistic fallback — this environment's apt only emits MD5Sum) before
extracting; don't remove that step to "simplify" the script. URIs that
aren't plain http(s) (e.g. `mirror+file:` apt sources, which `wget` can't
fetch) are downloaded with `apt-get download` instead, still followed by
the same checksum check. It also unpacks `xkb-data` and a font, and the
test fixture sets `XKB_CONFIG_ROOT`/`FONTCONFIG_FILE` from them: on a host
with neither, Chromium silently drops all keyboard input (so `fill()`
leaves inputs empty and tests time out) and may crash rendering. Don't add
`pytest-playwright` — it's a pytest plugin that imports playwright at
startup, which makes collection fail for anyone who doesn't have it
installed.

The table is windowed (`table.js`, class `VTable`): rows have a fixed height (`--row-h`) and only the rows
near the viewport exist in the page, so code and tests that read rows from the DOM see a window, not the table.
Use `aria-rowcount` for the size and the column menu's "Copy column values" to read a whole column (the tests do:
`_copy_column`). Never render every row; the old table needed over 4 s to sort 20,000 rows and could not draw
50,000. Data work (search index, typed sort) is in `app.js`; each render records the User Timing measure
`py-tbparse:table`, which the speed tests read. The budgets (first paint of 1,000 rows 150 ms, filtering 50,000 rows
100 ms) are enforced at twice the figure. Heavy tests skip below 1.5 GB of free memory (`_enough_memory`); this
sandbox has only 2 CPUs and 7.9 GB, and a 50,000-row DOM render has crashed it before.

The page's colours, spacing, type and motion are tokens in `webui/tokens.css`; use them rather than literals.
Colour themes are `webui/themes.css`: each theme is a complete colour set in light and dark, selected by
`<html data-theme data-mode>` (Auto is resolved to light/dark by the head script and kept in step by `app.js`;
dark colours live under `[data-mode="dark"]`, there is no `prefers-color-scheme` query). To add a theme, add its
two blocks there, its id to `webgui.THEMES` and its label to `THEME_LABELS` in `app.js`; the token test checks it.
`tests/test_webui_tokens.py` reads those files and fails if any text/background pair drops below WCAG AA
4.5:1, if the stylesheet uses an undefined variable, or if text is faded with `opacity` (use `--faint`).
Motion durations come from the `--dur-*` tokens, which `prefers-reduced-motion` sets to instant; keep new
animations on those tokens.

`scripts/readme_screenshots.py` retakes the README's four images from the made-up `docs/demo/coffee-shop.twb`
(built by `scripts/make_demo_workbook.py`, which is the one place that workbook is defined); run both after a
visible change.

`scripts/gui_screenshots.py WORKBOOK OUT_DIR [--compare BASELINE_DIR]` captures the GUI states (start,
overview and fields in light and dark, renames, graph, phone width, and the Templates view: empty, mapping, review, make) deterministically. Use it for GUI
refactors: a pure refactor must compare all-identical to the baseline taken before it; a redesign is expected to
differ, so review the new look and re-capture the baseline. The redesign plan and its decisions are in
`docs/ui-redesign-plan.md`.

## Commit / PR conventions

See repo commit history for message style. Two rules from the owner:

- **Author and committer are `DDSNA <79444147+DDSNA@users.noreply.github.com>`.** Commit with
  `git -c user.name=DDSNA -c user.email=79444147+DDSNA@users.noreply.github.com commit ...`, and check
  `git log --format='%an <%ae> | %cn <%ce>' origin/main..HEAD` before pushing.
- **Never name Claude or any AI tool as author or co-author**: no `Co-Authored-By` and no "Generated with" line in
  commit messages or PR descriptions, whatever default the tooling suggests.
