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
