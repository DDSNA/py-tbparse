# AGENTS.md

## What this is

`twbparser_py` is a native Python port of the R package
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
helpers (calc complexity, field usage, replication brief), and the
Shiny-inspector equivalent.

Also added, with no R equivalent (Python-native extras -- see "Non-R
modules" below): Graphviz DOT export of the relationship graph
(replaces the R package's igraph/ggraph-based plotting with a
dependency-free alternative), workbook-to-workbook diff, folder/batch
analysis across many workbooks, and Jupyter rich display.

## Setup

No system-wide `pip`; use the project venv.

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[test]"
```

## Build / test / lint commands

```bash
.venv/bin/python -m pytest -q          # run the full test suite
.venv/bin/python -m pytest -q tests/test_joins.py   # single file
.venv/bin/python -m py_compile twbparser_py/*.py     # syntax check
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

## Release / packaging

```bash
.venv/bin/pip install -e ".[dev]"     # build + twine
rm -rf dist build twbparser_py.egg-info
.venv/bin/python -m build              # produces dist/*.whl and dist/*.tar.gz
.venv/bin/twine check dist/*           # validates metadata/README rendering
```

Version is single-sourced from `pyproject.toml`'s `[project].version`;
`twbparser_py.__version__` reads it back via `importlib.metadata` at
runtime (see `__init__.py`), so don't hardcode a second copy.

Before bumping the version for a release: bump `version` in
`pyproject.toml`, then rebuild and smoke-test the wheel in a
throwaway venv (`pip install dist/*.whl`, run `twbparser --help` and
`twbparser-gui --help`, run pytest against an extracted sdist) — this
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
`release` GitHub Environment created in repo settings.

## Architecture

Each `twbparser_py/*.py` module is a direct port of one R source file in
the upstream package, function-for-function:

| Python module | Ported from (R) | Notes |
|---|---|---|
| `_clean.py` | `R/utils.R` (`.twb_clean_table`, `.twb_clean_field`, `attr_safe_get`, `.strip_brackets`) | Regex-based name cleaners shared by everything else |
| `_xml.py` | `R/utils.R` (`twbx_list`, `extract_twb_from_twbx`, `twbx_extract_files`) | `.twbx` zip handling |
| `datasources.py` | `R/datasources.R` | `extract_named_connections`, `extract_datasource_details`, `extract_parameters` |
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
| `cli.py` | `twbparser` command-line entry point, plus the `diff`/`batch` subcommands (dispatched on `sys.argv[1]` before the normal single-workbook argparse parser runs) |
| `webgui.py` | `twbparser-gui`: stdlib-only (`http.server` + vanilla JS) local browser GUI, no GUI toolkit dependency. Loosely fills the role of the R package's `run_twbparser_app`/Shiny inspector. |
| `graph.py` | `to_dot()`: Graphviz DOT export of joins/relationships (+ optional inferred, as dashed edges). Replaces the R package's igraph/ggraph-based `plot_dependency_graph`/`plot_relationship_graph` with a dependency-free text format any Graphviz-compatible tool can render. |
| `diff.py` | `diff_tables()`/`diff_workbooks()`: row-level added/removed diff between two workbooks' same-named table, via `_tables.TABLE_SPECS`. No "changed" classification without a natural key — a changed row shows as one removed + one added row. |
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
- `tests/conftest.py` provides `wenjie_xml`, `wenjie_path`,
  `zip_twbx_path` fixtures and an `xml_from_string()` helper. Tests import
  it with `from conftest import xml_from_string` (no `tests/__init__.py`,
  so it's a plain top-level import, not a relative one).
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

So: **any change to `webgui.py`'s `_PAGE` needs a browser test**, in
`tests/test_gui_browser.py`, which runs the page in real headless
Chromium via Playwright and fails on any uncaught JS error. The cheap
structural guards in `test_webgui.py` (unterminated string literals,
bracket balance) are a backstop, not a substitute.

`_PAGE` is declared as `r"""..."""` (a **raw** string) specifically so
this can't recur: without `r`, any backslash escape meant for the
*browser* (`\n`, `\t`, a future `\'`) would need doubling in the Python
source, and forgetting to double it silently corrupts the embedded JS
instead of erroring. Keep it raw — write JS escapes the normal JS way
(`'\n'`, not `'\\n'`).

Any server-side value spliced into `_PAGE` (currently `TABLE_NAMES` and
the preloaded workbook path) must go through `_json_for_script()`, not
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
extracting; don't remove that step to "simplify" the script. Don't add
`pytest-playwright` — it's a pytest plugin that imports playwright at
startup, which makes collection fail for anyone who doesn't have it
installed.

## Commit / PR conventions

Nothing project-specific beyond the harness defaults — see repo commit
history for message style.
