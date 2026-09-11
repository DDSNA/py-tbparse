# twbparser-py

A native Python port of the [`twbparser`](https://github.com/PrigasG/twbparser)
R package: parses Tableau `.twb`/`.twbx` workbook files into `pandas`
DataFrames. No R runtime required — pure `lxml` XML parsing.

This is a v1 subset port covering the parser's core: workbook loading,
datasources, parameters, fields, calculated fields, joins, relationships
(legacy and 2020.2+), inferred relationships, dashboards, and relationship
validation. Formatting/tooltips/colors/axes/sorts, dashboard
layout/actions, custom SQL, published refs, analytics helpers, graph
plotting, and the Shiny-inspector equivalent are not yet ported.

## Install

```bash
pip install -e .
```

## Usage

```python
from twbparser_py import TwbParser

p = TwbParser("workbook.twb")  # or .twbx
p.get_datasources()
p.get_fields()
p.get_calculated_fields()
p.get_joins()
p.get_relationships()
p.get_inferred_relationships()
p.get_dashboards()
p.get_dashboard_sheets()
p.validate()
p.get_overview()
```

### CLI

```bash
twbparser workbook.twb                              # overview (default table)
twbparser workbook.twb tables                        # list available tables
twbparser workbook.twb calculated-fields             # print a table
twbparser workbook.twb fields --format csv -o fields.csv
twbparser workbook.twbx dashboard-sheets --dashboard "Sales Overview"
twbparser workbook.twb validate                       # exit code 2 if invalid
```

Tables: `overview`, `datasources`, `parameters`, `fields`, `raw-fields`,
`calculated-fields`, `joins`, `relations`, `relationships`,
`inferred-relationships`, `dashboards`, `dashboard-sheets`. `--format`
is `table` (default), `csv`, or `json`.

### GUI

A local, browser-based GUI — standard library only (`http.server` +
vanilla JS), no GUI toolkit or extra dependency required:

```bash
twbparser-gui workbook.twb   # opens your default browser
twbparser-gui                # opens with an empty path field; paste one and click Load
twbparser-gui --no-browser --port 8765   # just run the server, e.g. for a headless box
```

Pick a table from the dropdown, filter `dashboard-sheets` by dashboard,
toggle "include Parameters" for `calculated-fields`, and export the
current view as CSV. All state lives server-side in memory for the life
of the process — it's a single-user local tool, not something to expose
on a shared network.

## Testing

```bash
pip install -e ".[test]"
pytest
```

Fixtures in `tests/fixtures/` are the same tiny sample workbooks used by
the original R package's test suite (`inst/extdata/`).

## Credit

Ported from the R implementation by George Arthur
([`PrigasG/twbparser`](https://github.com/PrigasG/twbparser)), MIT licensed.
