# py-tbparse

Reads Tableau workbooks (`.twb` and `.twbx`) and gives you what's in them as pandas DataFrames: datasources, fields, calculated fields, joins, relationships, dashboards, custom SQL. It's plain Python. You don't need Tableau or R installed.

It began as a port of PrigasG's R package [twbparser](https://github.com/PrigasG/twbparser). The browser GUI, the command-line tool, workbook diffing and folder scanning are new here.

![py-tbparse GUI, the overview report card for a small demo workbook](https://raw.githubusercontent.com/DDSNA/py-tbparse/main/docs/gui-overview.png)

## Install

```bash
pip install py-tbparse
```

Or from a checkout:

```bash
git clone https://github.com/DDSNA/py-tbparse.git
cd py-tbparse
pip install -e .
```

One name throughout: `pip install py-tbparse`, `import py_tbparse`, run `py-tbparse` or `py-tbparse-gui`. (Releases up to 0.2.0 imported `twbparser_py` and ran `twbparser` / `twbparser-gui`; those names are gone.)

## Using it from Python

```python
from py_tbparse import TwbParser

p = TwbParser("workbook.twb")    # or a .twbx
p.get_overview()                 # counts of everything
p.get_calculated_fields()        # each calculation and its formula
p.get_relationships()            # how the tables connect
```

Every getter returns a DataFrame. The rest are `get_datasources`, `get_parameters`, `get_fields`, `get_raw_fields`, `get_joins`, `get_relations`, `get_inferred_relationships`, `get_dashboards`, `get_dashboard_sheets`, `get_custom_sql`, `get_initial_sql` and `get_published_refs`. `get_relationship_graph_dot()` returns the data model as Graphviz text, and `validate()` looks for problems in the relationships. In Jupyter, a bare `p` shows the overview.

Two helpers work across workbooks:

```python
from py_tbparse import diff_workbooks, scan_folder

diff_workbooks(TwbParser("v1.twb"), TwbParser("v2.twb"), table="datasources")
scan_folder("./workbooks", table="datasources")   # one table, every workbook in the folder
```

### Cleaning field names after a datasource switch

Pointing a workbook at a new datasource that only partly matches the old schema tends to leave ugly names: `ORDER_ID`, `orderId`, `Order ID (Orders1)`, `Order ID1`. `suggest_field_renames` proposes a clean name for each field. It only reports; it never edits the workbook.

```python
from py_tbparse import TwbParser, suggest_field_renames

new = TwbParser("after_switch.twb")
old = TwbParser("before_switch.twb")           # optional: the schema you want to match

suggest_field_renames(new, reference=old, only_changed=True)
#   name                      current                 suggested     reason             score
#   [ORDER_ID]                ORDER_ID                Order ID      matches reference  1.0
#   [Sales Amount (Orders1)]  Sales Amount (Orders1)  Sales Amount  matches reference  1.0
#   [orderDate]               orderDate               Order Date    normalized         NaN
```

With a `reference` (a workbook, a fields table or a plain list of names), fields that match by name ignoring case, separators and Tableau's duplicate suffixes take the reference's exact spelling, and near-misses above `fuzzy_cutoff` (default 0.85) are matched too. Everything else is tidied by `normalize_name(name, style)`, where `style` is `title` (default), `snake`, `lower` or `keep`. Names that are already clean (`YTD Sales`, `iPhone Units`, `Country/Region`) are left alone. `1` and `(Table1)` suffixes are only dropped when the plain name exists in the same datasource (`Address Line 2` and `Q1` are never treated as duplicates), fuzzy matches never cross a different number, and two fields never get the same suggestion (the loser stays as it is, with `reason` set to `conflict`).

`p.get_field_renames()` does the same from a parser.

**Rename everything in the report, not just fields.** Pass `kinds` (or `--all` / `--kinds` on the command line) and worksheets, dashboards, datasources, parameters, folders and hierarchies are covered too:

```python
from py_tbparse import TwbParser, suggest_renames, apply_field_renames

p = TwbParser("report.twb")
suggest_renames(p, only_changed=True)                    # kind, datasource, name, current, suggested, ...
suggest_renames(p, kinds=["worksheet", "dashboard"])     # just the sheets
apply_field_renames(p, kinds="all")                      # writes report_renamed.twb
```

```bash
py-tbparse rename report.twb --all --only-changed
py-tbparse rename report.twb --kinds worksheet,dashboard --write-workbook
```

Each kind is renamed the way Tableau does it: fields, parameters and datasources get a caption (their internal names stay, so formulas and sheets keep working); a worksheet or dashboard is renamed in every place its name is written (the sheet, its window and thumbnail, the zones of dashboards that show it, actions, story points); a folder or hierarchy gets its new name. Worksheets and dashboards share one namespace, as they do in Tableau, so two of them never end up with the same name. A `reference` workbook lends its spelling to objects of the same kind. Datasources that Tableau named itself (`federated.0grg...`) and nobody captioned are left out. The `kind` column also appears in the CSV, so **Edit the suggestions yourself** works for sheets too. The `report-renames` table lists all of it, and the GUI's Field renames view has an "Everything in the report" switch. As with fields, none of this has been opened in Tableau itself.

**Edit the suggestions yourself.** Export them, change the `suggested` column in a spreadsheet (blank means leave the field alone), then apply your version to a copy of the workbook:

```bash
py-tbparse rename new.twb -r old.twb -f csv -o mapping.csv
py-tbparse rename new.twb --apply mapping.csv      # writes new_renamed.twb; add --write-workbook PATH to choose the file
```

Your edits are applied as written, including rows the tool had marked `conflict`; two rows giving the same name in one datasource are rejected. From Python this is `apply_field_renames(p, renames=load_rename_mapping("mapping.csv"))`.

**What will stay broken.** `py-tbparse rename new.twb -r old.twb --missing` (or `compare_field_schemas(new, old)`) lists the fields with no counterpart after the switch: `old only` fields that nothing in the new source matches, and `new only` fields nothing in the old workbook matches, each with the closest name on the other side as a hint. Sheets using an `old only` field stay red after Replace Data Source until you map or recreate it.

To save the result, `p.write_renamed_workbook()` (or `apply_field_renames(p, ...)`) writes `<name>_renamed.twb` / `.twbx` next to the original. It sets each field's caption, which is how Tableau renames a field; the internal names that formulas and sheets use are not touched, and a `.twbx` keeps all its other contents. A field that only exists as a physical column (typical right after a datasource switch) gets a new minimal `<column>` element carrying the caption; that shape follows what Tableau writes but I have not opened such files in Tableau itself. It never modifies the original and refuses to overwrite an existing file unless you pass `overwrite=True`.

**When to run it.** Add the new datasource to a *copy* of the workbook first, then run this with the old workbook as `reference` and `datasource=` set to the new source, so only its fields are renamed. Open the fixed copy and use Replace Data Source; fields with matching names should re-link on their own. It also works after references have already broken, but it only fixes names: sheets that point at missing fields stay broken until you replace the source again. (Check this on a copy first; I have not tested the re-linking in Tableau itself.)

### Templates

Turn a finished workbook into a template, then make new workbooks from it with other data. Every sheet, dashboard, calculation and format comes along; only the data changes. The idea comes from Tableau's Accelerators and Power BI's `.pbit` files.

```bash
py-tbparse template make sales.twbx                         # writes sales.template.twbx
py-tbparse template show sales.template.twbx                # the fields it needs, and its parameters
py-tbparse template apply sales.template.twbx --data q3.csv # suggested mapping + what would break; writes nothing
py-tbparse template apply sales.template.twbx --data q3.csv --mapping-out map.csv   # save the mapping to edit
py-tbparse template apply sales.template.twbx --data q3.csv --mapping map.csv -p "Top N=10" --write
```

```python
from py_tbparse import make_template, load_template, read_data, suggest_mapping, apply_template

t = load_template(make_template("sales.twbx"))
data = read_data("q3.csv")                      # or a .twb / .twbx / .tds already connected to the new data
suggest_mapping(t, data)                        # field, required, used_by, mapped_to, status, ...
apply_template(t, data, params={"Top N": "10"}) # writes sales_q3.twbx
```

**What a template is.** An ordinary `.twbx` (Tableau still opens it) with a `template.json` manifest inside. The manifest lists the fields the workbook takes from its data, marking a field `required` when a sheet uses it, directly or through calculations, groups and sets. It also lists the parameters and where the data came from. Extracts, packaged data and cached query results are left out (`--keep-data` keeps them as sample data), and user names and passwords are blanked.

**Mapping.** Each required field is matched to a column of the new data by name, ignoring case and separators (`ORDER_DATE` → `Order Date`), with close spellings accepted above `--cutoff`. Types are checked like Tableau's Accelerator mapper: a text column is never offered for a number or a date, while integer vs decimal and date vs date-time map with a warning. A field whose type the author changed in Tableau keeps that type, and Tableau converts the column. Before anything is written you see which sheets would break for each field left without a column; writing then needs `--allow-missing`. Edit the mapping as a CSV, as with renames.

**What gets written.** The template's connection is replaced by one to the new data (a CSV file, or the connection of the workbook / `.tds` you pass). Every field keeps the local name its sheets and formulas use; only the physical column behind it changes. Parameter values are set with `-p NAME=VALUE`, checked against the parameter's type and its list of allowed values. The output (`<template>_<data>.twbx` beside the template, never overwritten) also stores `template-answers.json`: which template, data, mapping and parameters made it, so it can be re-made or checked later.

**Limits.** A CSV feeds one table. A template whose datasource joins several tables needs a workbook or `.tds` as its data, so the joins come along. Excel files are not read directly yet; save as CSV or pass a workbook connected to the sheet. As with renames, I have not opened the generated workbooks in Tableau itself, so check one before relying on it.

`p.get_field_usage()` (or `field_usage(p)`, the `field-usage` table) is the analysis behind `required`: for every field, the sheets, dashboards and calculations that use it.

### `.twbx` files

A `.twbx` is read directly from the zip and nothing gets written to disk. That means `p.twbx_dir` is `None`, and `p.path` is a made-up `<file>.twbx/<name>.twb` that you can't open. If you want the files out, extract them yourself:

```python
from py_tbparse import extract_twb_from_twbx, twbx_extract_files

extract_twb_from_twbx("workbook.twbx", extract_dir="out/")
twbx_extract_files("workbook.twbx", exdir="out/")    # everything in the package
```

## Command line

```bash
py-tbparse workbook.twb                        # overview
py-tbparse workbook.twb tables                 # list the tables
py-tbparse workbook.twb calculated-fields
py-tbparse workbook.twb fields --format csv -o fields.csv
py-tbparse workbook.twbx dashboard-sheets --dashboard "Sales Overview"
py-tbparse workbook.twb validate               # exit code 2 if it finds a problem
py-tbparse workbook.twb graph > model.dot      # --include-inferred adds the guessed links
py-tbparse diff old.twb new.twb datasources
py-tbparse batch ./workbooks datasources
py-tbparse rename new.twb --reference old.twb --only-changed   # suggested clean field names
py-tbparse rename new.twb -r old.twb --datasource federated.abc123 --write-workbook   # and save new_renamed.twb
py-tbparse rename report.twb --all --write-workbook       # sheets, dashboards, datasources, ... too
py-tbparse template make sales.twbx                        # see Templates above
py-tbparse template apply sales.template.twbx --data q3.csv --write
```

Tables: `overview`, `datasources`, `parameters`, `fields`, `raw-fields`, `calculated-fields`, `joins`, `relations`, `relationships`, `inferred-relationships`, `dashboards`, `dashboard-sheets`, `custom-sql`, `initial-sql`, `published-refs`, `field-usage`, `missing-references`, `field-renames`, `report-renames`.

`--format` takes `table` (default), `csv` or `json`. `graph` always prints Graphviz text. `rename` takes `--reference`, `--datasource`, `--write-workbook [PATH]`, `--style`, `--cutoff`, `--only-changed`, `--all`, `--kinds`, `--apply MAPPING.csv`, `--missing`, `--format` and `--output`. `diff` and `batch` accept the same table names except `graph`, `validate` and `tables`.

## GUI

```bash
py-tbparse-gui workbook.twb               # opens your browser with it loaded
py-tbparse-gui                            # starts empty: drop a file on the page, pick one, or paste a path
py-tbparse-gui --no-browser --port 8765   # server only, for a machine with no display
```

It uses only the standard library, so there's nothing more to install.

Open a workbook three ways: drop a `.twb`/`.twbx` anywhere on the page, press **Open file...**, or paste a path and Load. A dropped or picked file is copied to a private temporary folder (up to 200 MB, deleted when you open another or quit), so it has no folder to save beside: the Field renames view offers Download instead of Create. Opened paths are listed on the start screen. The **Theme** button switches between six colour themes (Shop, Matcha, Fjord, Pastel, Neon and a High contrast one) and Auto, Light or Dark; every theme passes the same contrast tests as the default.

The sidebar lists every table with its row count. Tables stay fast however big they are: only the rows you can see are drawn, so 50,000 rows filter in about 20 ms. Click a column header to sort, type in the filter box to narrow rows (`/` jumps to it), and click a row (or press Enter on it) to open a drawer with every column in full, the real datasource id, and a button that copies the row as JSON. Each column has an options menu (the `...` button, or Alt+Down on a header) to sort, filter just that column, pin it to the left, hide it, change its width or copy its values; the **Columns** button brings hidden ones back, and **Compact rows** fits more on screen. Datasources show their caption instead of Tableau's internal id (hover for the id). The overview opens with a sentence about the workbook, its tiles, a **Worth a look** list (relationships that point at nothing, calculations that name fields the workbook does not have, calculations and fields no worksheet uses; each has a Show button that opens that table already filtered to exactly those rows) and what is on each dashboard. The graph view draws joins and relationships as a picture: drag to pan, scroll or the + and - buttons to zoom, hover or Tab to a table to light up its connections (arrow keys move between tables, Enter tells about one, clicking a line shows its keys), **View as list** for a plain table of the same connections, and **Save as SVG**. A big workbook is drawn one connected group at a time. The DOT text is still there, collapsed under the picture, and **Export DOT** downloads it. The Field renames view has the buttons for the feature above: pick a style, datasource and optional reference workbook, then **Create fixed workbook** saves `<name>_renamed` beside the original (and says so if that file already exists) or **Download fixed workbook** sends it to your browser without saving anything. Everything else exports as CSV. It has a dark theme and works in a narrow window.

![py-tbparse GUI, Field renames view with suggested clean names](https://raw.githubusercontent.com/DDSNA/py-tbparse/main/docs/gui-field-renames.png)

![py-tbparse GUI, the relationship graph with one table and its connections highlighted](https://raw.githubusercontent.com/DDSNA/py-tbparse/main/docs/gui-graph.png)

![py-tbparse GUI, the Neon dark theme with the theme menu open](https://raw.githubusercontent.com/DDSNA/py-tbparse/main/docs/gui-themes.png)

The screenshots are of a made-up demo workbook (`docs/demo/coffee-shop.twb`, built by `scripts/make_demo_workbook.py`); `scripts/readme_screenshots.py` retakes them.

It's meant to run on your own machine for one person. It refuses requests that come from other websites, but there's no login, so don't put it on a shared network.

## Tests

```bash
pip install -e ".[test]"
pytest
```

The sample workbooks in `tests/fixtures/` come from the R package. `tests/fixtures/public/` holds real workbooks from Tableau's own [document-api-python](https://github.com/tableau/document-api-python) (MIT), used by the smoke tests.

`tests/corpus/` lists 200 more real workbooks from public repositories with MIT, Apache-2.0, ISC or CC0 licences, for integration tests and as examples (manifest, licence texts and where each file came from are in its README). The files themselves are not in git (about 26 MB): run `python scripts/fetch_corpus.py` to download them, checked against the manifest. `tests/test_corpus.py` then runs every feature over all of them; it skips when they are not fetched.

The GUI tests run the page in headless Chromium through Playwright and fail on any JavaScript error. They skip if the browser isn't installed. To run them:

```bash
pip install -e ".[test,browser]"
playwright install chromium         # add --with-deps if you have root
./scripts/setup-browser-libs.sh     # without root, this unpacks the system libraries locally
pytest tests/test_gui_browser.py
```

## Compared with the R package

The code follows the R original function by function, and the aim is the same output. Not everything is ported. Missing so far: formatting, tooltips, colors, axes and sorts, dashboard layout and actions, the analytics helpers (calculation complexity, field usage, replication brief) and the Shiny inspector. The GUI covers some of what the inspector did.

Where the R version has a bug, this one doesn't copy it. That currently covers joins and relationships on more than one key, nested joins, the include-parameters option, and calculations with brackets inside brackets.

## Why a Tableau parser

A `.twb` is XML and a `.twbx` is a zip containing one, so reading them from Python isn't hard. Power BI's `.pbix` is a binary format built on a proprietary storage engine, and getting into it from code took reverse-engineering projects like [PBIXRay](https://github.com/Hugoberry/pbixray) and [pbi-tools](https://github.com/pbi-tools/pbi-tools). On the server side it goes the other way: Tableau's own Python tooling ([tableauserverclient](https://pypi.org/project/tableauserverclient/) and `tabcmd`) is more mature and more open than what Microsoft has for the Power BI REST API.

## Credit

Based on [twbparser](https://github.com/PrigasG/twbparser) by George Arthur, MIT licensed.
