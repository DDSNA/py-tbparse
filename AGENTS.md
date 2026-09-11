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
dashboards/dashboard-sheets, and `validate_relationships`. **Not yet
ported** (v2): formatting, tooltips, colors, axes, sorts, dashboard
layout/actions, custom SQL, published refs, analytics helpers (calc
complexity, field usage, replication brief), dependency-graph plotting,
and the Shiny-inspector equivalent.

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

Before bumping the version for a release: update `CHANGELOG.md`, bump
`version` in `pyproject.toml`, then rebuild and smoke-test the wheel in a
throwaway venv (`pip install dist/*.whl`, run `twbparser --help` and
`twbparser-gui --help`, run pytest against an extracted sdist) — this
catches packaging bugs (missing files, wrong entry points) that an
editable install won't.

CI (`.github/workflows/ci.yml`) runs pytest across Python 3.9–3.13 and
builds+checks the distribution on every push/PR. Release
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
| `parser.py` | `R/twb_parser.R` (`TwbParser` R6 class) | The `TwbParser` façade tying every module together |
| `_tables.py` | — (Python-only) | Name → `TwbParser` accessor registry shared by `cli.py` and `webgui.py`, not ported from R |
| `cli.py` | — (Python-only) | `twbparser` command-line entry point |
| `webgui.py` | — (Python-only, loosely mirrors `run_twbparser_app`/Shiny) | `twbparser-gui`: stdlib-only (`http.server` + vanilla JS) local browser GUI, no GUI toolkit dependency |

`parser.py`'s `TwbParser.__init__` mirrors the R6 constructor: it eagerly
computes every cached DataFrame, guarding each with `_safe_call` (the port
of R's `safe_call`/`tryCatch`) so a malformed workbook degrades to empty,
correctly-columned DataFrames instead of raising.

`_tables.py`, `cli.py`, and `webgui.py` have no R source to track — they're
the Python-native user-facing layer on top of `TwbParser`. Adding a new
extractor to `TwbParser`? Add it to `_tables.TABLE_SPECS` too so it's
automatically available from both the CLI and the GUI.

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
   matching XML — callers (esp. `parser.py`) rely on this.
4. **Cleaning helpers**: always route table/field name cleanup through
   `_clean.clean_table` / `_clean.clean_field` / `_clean.strip_brackets`
   rather than re-deriving regexes inline.
5. **No R dependency, ever.** If a future port needs something R gets
   from `dplyr`/`igraph` for free (e.g. graph layout for
   `plot_dependency_graph`), find a pure-Python equivalent or scope it
   out — don't reach for `rpy2`/subprocess-to-R.

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

## Commit / PR conventions

Nothing project-specific beyond the harness defaults — see repo commit
history for message style.
