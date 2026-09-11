# Changelog

All notable changes to this project are documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [0.1.0] - Unreleased

Initial release. Native Python (lxml + pandas, no R dependency) port of
the v1 core subset of the [`twbparser`](https://github.com/PrigasG/twbparser)
R package.

### Added
- `TwbParser` class: loads `.twb`/`.twbx` workbooks and exposes datasources,
  parameters, raw/calculated fields, legacy joins, modern (2020.2+)
  relationships, inferred relationships, dashboards, dashboard-sheets,
  custom/initial SQL, published-source detection, and relationship
  validation as `pandas` DataFrames. `_repr_html_` for Jupyter rich
  display.
- `twbparser` CLI: print any table as `table`/`csv`/`json`, write to a
  file, filter `dashboard-sheets` by dashboard, `validate` with exit code
  2 on failure, `graph` for a Graphviz DOT export of the relationship
  graph, and `diff`/`batch` subcommands for comparing two workbooks or
  scanning a folder of them.
- `twbparser-gui`: a local browser-based GUI (standard library only —
  `http.server` + vanilla JS), no GUI toolkit dependency, including a
  `graph` view with DOT preview/download.
- `to_dot()`, `diff_tables()`/`diff_workbooks()`, `scan_folder()`: usable
  directly as a library, not just via the CLI.
- Test suite (101 tests) covering every extractor, both entry points, and
  the two real sample workbooks pulled from the upstream R package's
  `inst/extdata/`.

### Fixed
A code review caught several R-vs-Python behavior divergences before
release (see commit history): `get_calculated_fields(include_parameters=True)`
was a no-op (a bug present in the upstream R package too); fractional
dashboard-zone coordinates raised instead of truncating; an
empty-but-present XML attribute was sometimes treated as absent where R
distinguishes the two; the Athena-region regex fallback dropped data R
would keep; and `validate_relationships`' token-cleaning ran in a
different order than R's, changing results for whitespace-padded values.

### Not yet ported (planned for a future release)
Formatting, tooltips, colors, axes, sorts, dashboard layout/actions,
analytics helpers (calc complexity, field usage, replication brief), and
the Shiny-inspector equivalent.
