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
- Turns a finished workbook into a template you can fill with other data: a CSV, an Excel sheet (`.xlsx`, `.xlsm`), another workbook, or a database table described in a target file. The database is never contacted. Supported: MySQL, PostgreSQL, SQL Server and Snowflake.
- Fills `{{token}}` placeholders in titles, text and captions, so one template gives each customer its own dashboard.
- Makes one workbook per file in a folder (`template apply-folder`), brings a workbook up to a newer template revision (`template update`) and lints a template (`template check`).
- Audits a workbook (`audit`: unused or duplicate calculations, missing references, custom SQL, absolute-path leftovers) and writes a Markdown data dictionary of it (`docs`). Read-only; never opened in Tableau.
- Writes a share-safe copy of a workbook (`sanitize IN OUT --report`): user names, servers, databases, paths, custom SQL, extracts, comments and thumbnails out, a report of what was removed and what it could not judge, optional placeholders and synthetic data. A clean-up, not a guarantee.
- Writes the findings of `validate`, `audit` and `template check` as JUnit, SARIF or GitHub annotations for CI (`--format junit|sarif|github`), with a pre-commit hook and a sample workflow.
- Takes calculated fields and parameters out of one workbook into a library file and adds them to another (`library export`, `library import`). The output follows what Tableau writes but has not been opened in Tableau.
- Takes named colour palettes out of workbooks and `Preferences.tps` files and writes them into a new `Preferences.tps`, a JSON file or a copy of a workbook (`style show`, `export`, `import`, `check`). Palettes only: it adds them to the colour picker and recolours nothing, and it has not been opened in Tableau.
- Runs as a Docker image behind a TLS proxy. From the next release, the image is also published to the GitHub Container Registry (`ghcr.io/ddsna/py-tbparse`).
- Compares two workbooks, scans a folder of them, and draws the data model as a graph.
- Works from Python, from the command line, or in a local browser page.

## Install

```bash
pip install py-tbparse
```

For Excel input to templates, add the optional extra: `pip install "py-tbparse[excel]"` (it installs `openpyxl`).

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

- [Command line](https://github.com/DDSNA/py-tbparse/blob/main/docs/cli.md): every table, the `diff`, `batch`, `rename`, `template`, `library` and `style` commands, and their options.
- [Browser GUI](https://github.com/DDSNA/py-tbparse/blob/main/docs/gui.md): opening files, the table, the overview, the graph, themes, filling a template with new data, and making a template from the open workbook (Templates).
- [Running as a server](https://github.com/DDSNA/py-tbparse/blob/main/docs/deployment.md): the Docker image, a reverse proxy that ends TLS, sessions, limits.
- [Renaming](https://github.com/DDSNA/py-tbparse/blob/main/docs/renaming.md): clean names after a datasource switch, editing the suggestions, what will stay broken.
- [Templates](https://github.com/DDSNA/py-tbparse/blob/main/docs/templates.md): make a template from a workbook and apply it to new data.
- [Sanitize](https://github.com/DDSNA/py-tbparse/blob/main/docs/sanitize.md): the share-safe copy, its categories, the report and the optional synthetic data.
- [CI output and pre-commit](https://github.com/DDSNA/py-tbparse/blob/main/docs/ci.md): `--format junit|sarif|github`, exit codes, rule ids, sample workflow.
- [Audit and data dictionary](https://github.com/DDSNA/py-tbparse/blob/main/docs/audit.md): the audit rules A001 to A011, what "used" means, the Markdown data dictionary.
- [Libraries](https://github.com/DDSNA/py-tbparse/blob/main/docs/libraries.md): export calculated fields and parameters, add them to another workbook, what is not covered.
- [Colour palettes](https://github.com/DDSNA/py-tbparse/blob/main/docs/styles.md): list, export and import named palettes, the clash policy, why nothing is recoloured and what was not checked in Tableau.
- [Normalised XML diff](https://github.com/DDSNA/py-tbparse/blob/main/docs/diff-xml.md): `py-tbparse diff-xml A B` and `normalised_diff()`, a line diff of two workbooks' XML that ignores attribute order, quotes and indentation.
- [`.twbx` files](https://github.com/DDSNA/py-tbparse/blob/main/docs/twbx.md): they are read straight from the zip; how to extract the contents.
- [Development](https://github.com/DDSNA/py-tbparse/blob/main/docs/development.md): running the tests, the workbook corpus, the browser tests.

## Limits

- **Little of what the tool writes has been opened in Tableau.** Everything it writes is checked against Tableau's published schema and for dangling references, on 200 real workbooks. A template applied to a CSV and to a workbook has been opened in Tableau once, for one workbook, and drew its sheets (see [verify-in-tableau.md](https://github.com/DDSNA/py-tbparse/blob/main/docs/verify-in-tableau.md)); renamed workbooks, workbooks with a library added, palettes imported and other shapes have not. Open one on a copy and check it before relying on it. The original file is never modified or overwritten.
- **Only part of the R package is ported.** Missing: formatting, tooltips, colors, axes and sorts, dashboard layout and actions, calculation complexity, the replication brief and the Shiny inspector. The GUI covers some of what the inspector did.
- Where the R version has a bug, this one does not copy it: joins and relationships on more than one key, nested joins, the include-parameters option, and calculations with brackets inside brackets.
- **No login.** The GUI is meant to run on your own machine for one person. It refuses requests that come from other websites, but there is no login, so do not put it on a shared network. To share it, use the [Docker image](https://github.com/DDSNA/py-tbparse/blob/main/docs/deployment.md) behind a proxy that adds TLS and a login.

## Why a Tableau parser

A `.twb` is XML and a `.twbx` is a zip containing one, so reading them from Python is not hard. Power BI's `.pbix` is a binary format built on a proprietary storage engine, and getting into it from code took reverse-engineering projects like [PBIXRay](https://github.com/Hugoberry/pbixray) and [pbi-tools](https://github.com/pbi-tools/pbi-tools). On the server side it goes the other way: Tableau's own Python tooling ([tableauserverclient](https://pypi.org/project/tableauserverclient/) and `tabcmd`) is more mature and more open than what Microsoft has for the Power BI REST API.

## Contributing

Issues and pull requests are welcome at [github.com/DDSNA/py-tbparse](https://github.com/DDSNA/py-tbparse). The test setup is in the [development guide](https://github.com/DDSNA/py-tbparse/blob/main/docs/development.md). `AGENTS.md` describes the code layout and the rules for porting a function from the R package.

## Credit

Based on [twbparser](https://github.com/PrigasG/twbparser) by George Arthur, MIT licensed.

## License

MIT, see [LICENSE](https://github.com/DDSNA/py-tbparse/blob/main/LICENSE).
