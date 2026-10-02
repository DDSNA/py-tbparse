# Workbook templates

Part of [py-tbparse](https://github.com/DDSNA/py-tbparse).

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

**Mapping.** Each required field is matched to a column of the new data by name, ignoring case and separators (`ORDER_DATE` → `Order Date`, `customer-id` → `customer_id`). The field's caption, name, original column name and alias are all tried, and close spellings are accepted above `--cutoff`; between equally close columns the one that comes first wins, so the same data always gives the same mapping. Types are checked like Tableau's Accelerator mapper: a text column is never offered for a number or a date, while integer vs decimal and date vs date-time map with a warning, and so does a column Tableau says is a dimension where the template has a measure (`role differs`; only a workbook or `.tds` states a role, a CSV does not). A field whose type the author changed in Tableau keeps that type, and Tableau converts the column. Before anything is written you see what each field left without a column would break: its worksheets, the dashboards that show them, the calculations, sets and groups built on it, and the worksheets that filter on it. Writing then needs `--allow-missing`. Edit the mapping as a CSV, as with renames.

**See the consequences first.** `--explain` lists everything an apply changes besides the connection: fields that take a new type, fields with no column, and what each of those breaks (`py_tbparse.explain`). `--check` looks at the new data itself (`py_tbparse.check_data`): a dimension the sheets use that the data lacks (its rows may be at another grain), a required column with no values, a column that looks like a key (`*_id`, `*_key`, `*_code`) and repeats a value. A CSV is judged on its first 2000 rows; `--deep` reads all of it. Both only report: neither stops an apply.

**Answers and profiles.** Every workbook an apply writes keeps `template-answers.json`: the template (its `id` and `revision`), the data and a fingerprint of its columns, the mapping and the parameters. Pass it back to repeat the run without asking, from the workbook itself or from a copy saved as `*.answers.json`:

```bash
py-tbparse template apply sales.template.twbx --answers sales_q3.twbx --data q4.csv --write   # same mapping and parameters, new data
py-tbparse template apply sales.template.twbx --answers sales.answers.json --profile prod --write
```

Saved choices are put over the suggestion, so a column that was renamed is reported (`stale`) and re-suggested instead of failing, and a change in the data's columns is noted. A `profiles` section names sets of values to switch between, each with its own `parameters` and optionally the `data` file (relative to the answers file):

```json
{ "profiles": { "prod": { "parameters": { "Region": "EMEA" }, "data": "prod/q4.csv" },
                "test": { "parameters": { "Region": "Test" } } } }
```

An explicit argument beats the profile, which beats the saved answers; an unknown parameter or profile name fails and lists the valid ones. Answers refuse to hold credentials (a `password`, `username`, `token` or `secret` key is an error): enter them in Tableau when you open the workbook, as with a Power BI template. A template made by an older version (manifest version 1) loads and applies as before; version 2 adds a stable `uid` per field, the template `id` and a `revision`.

**What gets written.** The template's connection is replaced by one to the new data (a CSV file, or the connection of the workbook / `.tds` you pass). Every field keeps the local name its sheets and formulas use; only the physical column behind it changes. Parameter values are set with `-p NAME=VALUE`, checked against the parameter's type and its list of allowed values. The output (`<template>_<data>.twbx` beside the template, never overwritten) also stores `template-answers.json`: which template, data, mapping and parameters made it, so it can be re-made or checked later.

**Limits.** A CSV feeds one table. A template whose datasource joins several tables needs a workbook or `.tds` as its data, so the joins come along. Excel files are not read directly yet; save as CSV or pass a workbook connected to the sheet. A CSV-backed and a workbook-backed output have been opened in Tableau and drew their sheets (one workbook, see [verify-in-tableau.md](verify-in-tableau.md)); other shapes have only been checked by the tests, so open one before relying on it.

`p.get_field_usage()` (or `field_usage(p)`, the `field-usage` table) is the analysis behind `required`: for every field, the sheets, dashboards and calculations that use it.

**Checks.** Output is checked against Tableau's published schema and for dangling references (`py_tbparse.verify.validate_workbook`) on every workbook of the corpus; how to check it in Tableau yourself is in [verify-in-tableau.md](verify-in-tableau.md).
