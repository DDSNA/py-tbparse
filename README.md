# twbparser-py

A native Python port of the [`twbparser`](https://github.com/PrigasG/twbparser)
R package: parses Tableau `.twb`/`.twbx` workbook files into `pandas`
DataFrames. No R runtime required — pure `lxml` XML parsing.

This is a v1 subset port covering the parser's core: workbook loading,
datasources, parameters, fields, calculated fields, joins, relationships
(legacy and 2020.2+), inferred relationships, dashboards, relationship
validation, custom/initial SQL, and published-source detection.
Formatting/tooltips/colors/axes/sorts, dashboard layout/actions,
analytics helpers (calc complexity, field usage, replication brief),
and the Shiny-inspector equivalent are not yet ported.

Beyond the R original, this port adds a few Python-native extras: a
Graphviz DOT export of the relationship graph, a workbook-to-workbook
diff, folder/batch analysis across many workbooks, and Jupyter rich
display (`_repr_html_`).

### Why this was straightforward to build

`.twb` is plain XML, and `.twbx` is just a zip wrapper around one. That's
why parsing it natively in Python (no R, no reverse-engineering) was
tractable as a weekend-scale project. Power BI's equivalent file format,
`.pbix`, is a binary container built around the proprietary VertiPaq
columnar storage engine — reading it programmatically needed a dedicated
reverse-engineering effort ([PBIXRay](https://github.com/Hugoberry/pbixray),
[pbi-tools](https://github.com/pbi-tools/pbi-tools)) that a project like
this one never had to do. The two ecosystems aren't symmetric, though:
Tableau's own official Python tooling for *server* automation
([`tableauserverclient`](https://pypi.org/project/tableauserverclient/),
`tabcmd`) is more mature and more open than anything Microsoft ships
for Power BI's REST API.

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
p.get_custom_sql()
p.get_initial_sql()
p.get_published_refs()
p.get_relationship_graph_dot()   # Graphviz DOT string
p.validate()
p.get_overview()
p  # in Jupyter: renders get_overview() via _repr_html_

from twbparser_py import diff_workbooks, scan_folder

diff_workbooks(TwbParser("v1.twb"), TwbParser("v2.twb"), table="datasources")
scan_folder("./workbooks", table="datasources")  # one row per workbook x datasource
```

### CLI

```bash
twbparser workbook.twb                              # overview (default table)
twbparser workbook.twb tables                        # list available tables
twbparser workbook.twb calculated-fields             # print a table
twbparser workbook.twb fields --format csv -o fields.csv
twbparser workbook.twbx dashboard-sheets --dashboard "Sales Overview"
twbparser workbook.twb validate                       # exit code 2 if invalid
twbparser workbook.twb graph --include-inferred > relationships.dot
twbparser diff old.twb new.twb datasources             # row-level added/removed
twbparser batch ./workbooks datasources                # one table, every workbook in a folder
```

Tables: `overview`, `datasources`, `parameters`, `fields`, `raw-fields`,
`calculated-fields`, `joins`, `relations`, `relationships`,
`inferred-relationships`, `dashboards`, `dashboard-sheets`,
`custom-sql`, `initial-sql`, `published-refs`. `--format` is `table`
(default), `csv`, or `json` (`graph` always prints Graphviz DOT text
regardless of `--format`). `diff`/`batch` accept most of the same table
names, minus `graph`/`validate`/`tables`.

### GUI

A local, browser-based GUI — standard library only (`http.server` +
vanilla JS), no GUI toolkit or extra dependency required:

```bash
twbparser-gui workbook.twb   # opens your default browser
twbparser-gui                # opens with an empty path field; paste one and click Load
twbparser-gui --no-browser --port 8765   # just run the server, e.g. for a headless box
```

Pick a table from the dropdown, filter `dashboard-sheets` by dashboard,
toggle "include Parameters" for `calculated-fields`, pick `graph` to
preview/export a Graphviz DOT digraph of the relationships, and export
any tabular view as CSV. All state lives server-side in memory for the
life of the process — it's a single-user local tool, not something to
expose on a shared network.

## Testing

```bash
pip install -e ".[test]"
pytest
```

Fixtures in `tests/fixtures/` are the same tiny sample workbooks used by
the original R package's test suite (`inst/extdata/`).

The GUI additionally has end-to-end tests that drive the page in a real
headless Chromium (via Playwright) and fail on any uncaught JavaScript
error. They're opt-in — without the browser installed they skip and the
rest of the suite runs normally:

```bash
pip install -e ".[test,browser]"
playwright install chromium          # add --with-deps if you have root
./scripts/setup-browser-libs.sh      # no-root alternative to --with-deps
pytest tests/test_gui_browser.py
```

## Credit

Ported from the R implementation by George Arthur
([`PrigasG/twbparser`](https://github.com/PrigasG/twbparser)), MIT licensed.
