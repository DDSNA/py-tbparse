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
  relationships, inferred relationships, dashboards, dashboard-sheets, and
  relationship validation as `pandas` DataFrames.
- `twbparser` CLI: print any table as `table`/`csv`/`json`, write to a
  file, filter `dashboard-sheets` by dashboard, `validate` with exit code
  2 on failure.
- `twbparser-gui`: a local browser-based GUI (standard library only —
  `http.server` + vanilla JS), no GUI toolkit dependency.
- Test suite (69 tests) covering every extractor, both entry points, and
  the two real sample workbooks pulled from the upstream R package's
  `inst/extdata/`.

### Not yet ported (planned for a future release)
Formatting, tooltips, colors, axes, sorts, dashboard layout/actions,
custom SQL, published refs, analytics helpers (calc complexity, field
usage, replication brief), dependency-graph plotting, and the
Shiny-inspector equivalent.
