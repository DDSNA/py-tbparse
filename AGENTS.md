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
.venv/bin/pip install -e ".[test]"
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
`release` GitHub Environment created in repo settings.

## Architecture

Each `py_tbparse/*.py` module is a direct port of one R source file in
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
| `cli.py` | `py-tbparse` command-line entry point, plus the `diff`/`batch`/`rename`/`template` subcommands (dispatched on `sys.argv[1]` before the normal single-workbook argparse parser runs) |
| `webgui.py` + `webui/` | `py-tbparse-gui`: stdlib-only (`http.server` + vanilla JS) local browser GUI, no GUI toolkit dependency. The server is `webgui.py`; the page is `webui/` (`index.html`, `tokens.css`, `themes.css`, `app.css`, `table.js`, `graph.js`, `app.js`). Loosely fills the role of the R package's `run_twbparser_app`/Shiny inspector. |
| `graph.py` | `to_dot()`: Graphviz DOT export of joins/relationships (+ optional inferred, as dashed edges); `graph_data()` is the same edges as plain data, which the GUI lays out and draws itself (`webui/graph.js`: layered layout, SVG, pan/zoom, keyboard). Replaces the R package's igraph/ggraph-based `plot_dependency_graph`/`plot_relationship_graph` with a dependency-free text format any Graphviz-compatible tool can render. |
| `diff.py` | `diff_tables()`/`diff_workbooks()`: row-level added/removed diff between two workbooks' same-named table, via `_tables.TABLE_SPECS`. No "changed" classification without a natural key — a changed row shows as one removed + one added row. |
| `rename.py` | `suggest_field_renames()` (clean-name suggestions, optionally matched against a "before" reference), `suggest_renames()` (the same for every kind of object: field, parameter, worksheet, dashboard, datasource, folder, hierarchy; adds a `kind` column), `load_rename_mapping()` (read an edited CSV back), `compare_field_schemas()` (fields with no counterpart across a datasource switch) and `apply_field_renames()`/`build_renamed_workbook()` (write a copy with captions set; never overwrites). Also the `field-renames` and `report-renames` tables in `_tables.py`. A worksheet/dashboard rename must rewrite every reference (`_SHEET_REFERENCES`); if you learn of another place Tableau writes a sheet name, add it there. |
| `report.py` | `workbook_report()`: the overview's report card (summary sentence, health checks, dashboards with their sheets) built from `validate_relationships`, `field_usage` and `usage.missing_references`. Every health item names the table and column filters that list exactly the rows it counted; a test keeps count and rows equal on all 200 corpus workbooks. |
| `usage.py` | `field_usage()`: for every field, the worksheets, dashboards and calculations that use it, followed through calculations, groups/sets and bins (the `field-usage` table). Python-native rather than a port of the R package's field-usage helper. |
| `templates.py` | Workbook templates. `make_template()` writes a `.twbx` with a `template.json` manifest (required fields from `usage.py`, parameters, connections; data, extracts and credentials stripped); `read_data()` describes new data (CSV, or a `.twb`/`.twbx`/`.tds`); `suggest_mapping()` pairs fields with columns (reuses `rename._match_key`, type checks against the field's *physical* type, `datatype-customized` fields keep their type); `apply_template()` replaces the datasource's connection, keeping every field's local name, sets parameters and stores `template-answers.json`. A CSV connection is written in the 2020.2+ object-model shape when the template uses it, in the template's own dialect (`_object_model()`: *prefixed* `_.fcp.ObjectModelEncapsulateLegacy.*` tags with both relations, or *plain* `<object-graph>`/`<column datatype='table'>`; both occur at version 18.1) -- object graph, table column and `object-id` per record, keeping the template's object id (worksheets name the table column by it) and placing the table column after `<aliases>`; keep those in step if you touch one. Opened in Tableau once for one workbook shape (see `verify.py`, `docs/verify-in-tableau.md`). Manifest version 2 adds a template `id`/`revision` and a `uid` per field (`field_uid()`: datasource, local name, role, type; a caption change keeps it); version 1 still loads (`_fill_version_1`). Answers version 2 (`load_answers`, `resolve_apply` -> `ApplyPlan`, which `apply_template` and the CLI both use) hold per-datasource entries, `profiles` and a schema fingerprint; precedence is explicit argument, then profile, then saved answers, and answers never hold credentials (`_reject_credentials`). `check_data()` (findings on the data, never blocking) and `explain()` (every consequence besides the connection; `broken_sheets()` is its short form) report before an apply. `DataSource.column()` maps a mapping's trimmed column name back to the data's real one. Zip members are written with a fixed timestamp so the same inputs give the same bytes (tests rely on it). |
| `verify.py` | `validate_workbook()`: dangling-reference checks on the XML (`sheet-field`, `calc-reference`, `dashboard-sheet`, `window-name`, `local-type`, and for text files `remote-name`/`remote-type`; one row per finding). Judge a written workbook by what it has that its input did not: real workbooks have findings of their own. Not a claim that Tableau opens the file. |
| `template_update.py` | `diff_template_revisions()`, `template_update_report()` (stage A: a newer template revision against the answers a workbook kept, impact per change) and `update_from_answers()` (stage B: re-apply with those answers, stop on `needs-mapping`). The "before" is `answers["template"]["manifest"]` (a snapshot `apply_template` writes, with `data.columns`), or `old=`. Three-way merge is not built; it needs a design note and the owner's go. |
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
The browser suite is split by concern, all sharing the fixtures in `tests/test_gui_browser.py`:
`test_gui_table.py` (windowing invariants, pipeline vs. a Python oracle, a seeded random walk;
`PYTBPARSE_WALK_SEEDS`/`PYTBPARSE_WALK_STEPS` widen it), `test_gui_a11y.py` (roles, keyboard, focus, rendered
contrast in both themes) and `test_gui_layout.py` (no sideways overflow from 320 px up, layout stability).
Design decisions the tests pin: only sorting uses a view transition (Chromium sends clicks to the page root while
one runs); column `MIN_WIDTH` is 80; per-table view settings are keyed by column name; disabled menu items use
`aria-disabled` so they stay focusable.

`tests/test_gui_browser.py`, which runs the page in real headless
Chromium via Playwright and fails on any uncaught JS error. The cheap
structural guards in `test_webgui.py` (unterminated string literals,
bracket balance) are a backstop, not a substitute.

The page is real files, not a Python string: `py_tbparse/webui/index.html`, `tokens.css` (the design
tokens), `app.css` and `app.js`. They are served by `webgui.py` from a fixed whitelist under
`/static/` (`_ASSETS`), so a request can never reach any other file; add a new asset to
`_ASSETS` and to the `webui/*` package-data (pyproject and MANIFEST.in) or it will not ship.
`index.html` is the only thing that gets server values: `_render_index()` replaces
`<!--APP_CONFIG-->` (now in `<head>`, so the saved theme is on `<html>` before the first paint) with the single
inline `<script>`. Keep it that way (one inline script plus the three external ones, `table.js`, `graph.js`, then
`app.js`); a test counts them. `populateTables();` must appear exactly once
in `app.js`, and the structural tests (unterminated string literals, bracket balance) read both served scripts.
Keep apostrophes out of JS strings and comments (the test counts quotes per line).

`POST /upload` (drag and drop, Open file) takes raw bytes with `Content-Type: application/octet-stream` and the name
in `X-Filename`: neither is CORS-safelisted, so another site cannot send it without a preflight. It streams to a
`mkdtemp` directory, refuses over `MAX_UPLOAD_BYTES` (413) and content that does not match the extension, and keeps
only one upload at a time. An uploaded workbook cannot "create beside the original" (409), only download.

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

`scripts/gui_screenshots.py WORKBOOK OUT_DIR [--compare BASELINE_DIR]` captures nine GUI states (start,
overview and fields in light and dark, renames, graph, phone width) deterministically. Use it for GUI
refactors: a pure refactor must compare all-identical to the baseline taken before it; a redesign is expected to
differ, so review the new look and re-capture the baseline. The redesign plan and its decisions are in
`docs/ui-redesign-plan.md`.

## Commit / PR conventions

Nothing project-specific beyond the harness defaults — see repo commit
history for message style.
