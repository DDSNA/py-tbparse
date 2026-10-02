# py-tbparse

[![PyPI](https://img.shields.io/pypi/v/py-tbparse)](https://pypi.org/project/py-tbparse/)
[![Python](https://img.shields.io/pypi/pyversions/py-tbparse)](https://pypi.org/project/py-tbparse/)
[![CI](https://github.com/DDSNA/py-tbparse/actions/workflows/ci.yml/badge.svg)](https://github.com/DDSNA/py-tbparse/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/DDSNA/py-tbparse/blob/main/LICENSE)

Read Tableau workbooks (`.twb` and `.twbx`) from Python. You get datasources, fields, calculated fields, joins, relationships and dashboards as pandas DataFrames. It is plain Python on top of `lxml` and `pandas`, so Tableau and R are not needed.

It began as a port of PrigasG's R package [twbparser](https://github.com/PrigasG/twbparser). The command-line tool, the browser GUI, renaming, templates, workbook diffing and folder scanning are new here.

![The overview report card for a small demo workbook](https://raw.githubusercontent.com/DDSNA/py-tbparse/main/docs/gui-overview.png)

## What it does

- Lists what is in a workbook: datasources, parameters, fields, calculations, joins, relationships, dashboards, custom SQL, published sources.
- Checks relationships and finds calculations that refer to fields the workbook does not have.
- Shows which worksheets, dashboards and calculations use each field.
- Suggests clean names for fields, sheets, dashboards and other objects, and writes a renamed copy.
- Turns a finished workbook into a template you can fill with other data.
- Compares two workbooks, scans a folder of them, and draws the data model as a graph.
- Works from Python, from the command line, or in a local browser page.

## Install

```bash
pip install py-tbparse
```

Python 3.9 or newer. The package, the import and both commands all use the same name: `pip install py-tbparse`, `import py_tbparse`, `py-tbparse`, `py-tbparse-gui`. Releases up to 0.2.0 used `twbparser_py` and `twbparser`; those names are gone.

## Quick start

From Python:

```python
from py_tbparse import TwbParser

p = TwbParser("workbook.twb")    # or a .twbx
p.get_overview()                 # counts of everything
p.get_calculated_fields()        # each calculation and its formula
p.get_relationships()            # how the tables connect
```

Every getter returns a DataFrame. The others are `get_datasources`, `get_parameters`, `get_fields`, `get_raw_fields`, `get_joins`, `get_relations`, `get_inferred_relationships`, `get_dashboards`, `get_dashboard_sheets`, `get_custom_sql`, `get_initial_sql`, `get_published_refs` and `get_field_usage`. `get_relationship_graph_dot()` returns the data model as Graphviz text and `validate()` looks for problems in the relationships. In Jupyter, a bare `p` shows the overview.

From the command line:

```bash
py-tbparse workbook.twb                    # overview
py-tbparse workbook.twb calculated-fields
py-tbparse workbook.twb fields --format csv -o fields.csv
py-tbparse workbook.twb validate           # exit code 2 if it finds a problem
```

In the browser:

```bash
py-tbparse-gui workbook.twb
```

Across workbooks:

```python
from py_tbparse import TwbParser, diff_workbooks, scan_folder

diff_workbooks(TwbParser("v1.twb"), TwbParser("v2.twb"), table="datasources")
scan_folder("./workbooks", table="datasources")   # one table, every workbook in the folder
```

## Guides

- [Command line](https://github.com/DDSNA/py-tbparse/blob/main/docs/cli.md): every table, the `diff`, `batch`, `rename` and `template` commands, and their options.
- [Browser GUI](https://github.com/DDSNA/py-tbparse/blob/main/docs/gui.md): opening files, the table, the overview, the graph, themes.
- [Running as a server](https://github.com/DDSNA/py-tbparse/blob/main/docs/deployment.md): the Docker image, a reverse proxy that ends TLS, sessions, limits.
- [Renaming](https://github.com/DDSNA/py-tbparse/blob/main/docs/renaming.md): clean names after a datasource switch, editing the suggestions, what will stay broken.
- [Templates](https://github.com/DDSNA/py-tbparse/blob/main/docs/templates.md): make a template from a workbook and apply it to new data.
- [`.twbx` files](https://github.com/DDSNA/py-tbparse/blob/main/docs/twbx.md): they are read straight from the zip; how to extract the contents.
- [Development](https://github.com/DDSNA/py-tbparse/blob/main/docs/development.md): running the tests, the workbook corpus, the browser tests.

## Limits

- **Nothing the tool writes has been opened in Tableau yet.** That covers renamed workbooks and workbooks made from templates. The XML follows what Tableau writes, but open one on a copy and check it before relying on it. The original file is never modified or overwritten.
- **Only part of the R package is ported.** Missing: formatting, tooltips, colors, axes and sorts, dashboard layout and actions, calculation complexity, the replication brief and the Shiny inspector. The GUI covers some of what the inspector did.
- Where the R version has a bug, this one does not copy it: joins and relationships on more than one key, nested joins, the include-parameters option, and calculations with brackets inside brackets.
- The GUI is meant to run on your own machine for one person. It refuses requests that come from other websites, but there is no login, so do not put it on a shared network. To share it, use the [Docker image](https://github.com/DDSNA/py-tbparse/blob/main/docs/deployment.md) behind a proxy that adds TLS and a login.

## Why a Tableau parser

A `.twb` is XML and a `.twbx` is a zip containing one, so reading them from Python is not hard. Power BI's `.pbix` is a binary format built on a proprietary storage engine, and getting into it from code took reverse-engineering projects like [PBIXRay](https://github.com/Hugoberry/pbixray) and [pbi-tools](https://github.com/pbi-tools/pbi-tools). On the server side it goes the other way: Tableau's own Python tooling ([tableauserverclient](https://pypi.org/project/tableauserverclient/) and `tabcmd`) is more mature and more open than what Microsoft has for the Power BI REST API.

## Contributing

Issues and pull requests are welcome at [github.com/DDSNA/py-tbparse](https://github.com/DDSNA/py-tbparse). The test setup is in the [development guide](https://github.com/DDSNA/py-tbparse/blob/main/docs/development.md). `AGENTS.md` describes the code layout and the rules for porting a function from the R package.

## Credit

Based on [twbparser](https://github.com/PrigasG/twbparser) by George Arthur, MIT licensed.

## License

MIT, see [LICENSE](https://github.com/DDSNA/py-tbparse/blob/main/LICENSE).
