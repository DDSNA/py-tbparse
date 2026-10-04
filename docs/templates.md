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

**See the consequences first.** `--explain` lists what an apply changes besides the connection: fields that take a new type, fields with no column, and what each of those breaks, including the sets and groups built on a dropped field (`py_tbparse.explain`). Parameters are not listed: you pass their values, and no parameter in the 200 corpus workbooks depends on a field. `--check` looks at the new data itself (`py_tbparse.check_data`): a dimension the sheets use that the data lacks (its rows may be at another grain), a required column with no values, a column that looks like a key (`*_id`, `*_key`, `*_code`) and repeats a value. A CSV is judged on its first 2000 rows; `--deep` reads all of it. Both only report: neither stops an apply.

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

**Updating a workbook when the template changes.** Improve the template, save it as the next revision (`make_template(..., revision_of=OLD)` keeps the `id` and counts the `revision` up), then bring a workbook made from the old one along:

```bash
py-tbparse template update sales.v2.template.twbx sales_q3.twbx            # what changes for its saved answers; writes nothing
py-tbparse template update sales.v2.template.twbx sales_q3.twbx --write    # sales_q3_r2.twbx, same data, mapping and parameters
```

The report lists every change (fields added, removed, renamed, caption, required, type, role; parameters added, removed, default, allowed values; sheets and dashboards) with its effect on the saved answers: `auto-carry` (the saved choice still applies), `needs-mapping` (a required field has no column), `orphaned` (the saved choice names something the template no longer has), `type-conflict` (the saved column or value no longer fits), `optional` (a new field no sheet needs). Fields are matched by `uid`, then by name; a field that kept its source column or caption under a new name counts as renamed, and its saved column moves with it. `--write` stops on `needs-mapping` rows and on a saved column of the wrong type (supply an edited `--mapping`, or `--allow-missing`), drops a saved parameter value the template no longer accepts (the template's default applies, and the command says which), and reports which data columns appeared or vanished. The same template is a no-op. The "before" is the manifest the workbook's answers keep (workbooks made before 0.5 do not have it: pass `--old OLD_TEMPLATE`, or the report only checks the new template against the answers). It never merges edits made to the workbook itself in Tableau; it starts again from the new template. It updates one datasource at a time and refuses a workbook made from several.

**What gets written.** The template's connection is replaced by one to the new data (a CSV file, or the connection of the workbook / `.tds` you pass). Every field keeps the local name its sheets and formulas use; only the physical column behind it changes. Parameter values are set with `-p NAME=VALUE`, checked against the parameter's type and its list of allowed values. The output (`<template>_<data>.twbx` beside the template, never overwritten) also stores `template-answers.json`: which template, data, mapping and parameters made it, so it can be re-made or checked later.

**One template, many files.** For the same dashboard delivered to many customers, branches or months:

```bash
py-tbparse template apply-folder sales.template.twbx customers/ -o out/ --inputs customers.csv
```

Every `.csv`, `.tsv`, `.xlsx` and `.xlsm` in the folder gets its own workbook, `out/sales_<file>.twbx` (a stem used by two extensions gets `_2`), and `out/summary.csv` lists what happened to each file: `status` (`ok`, `skipped`, `error`), how many columns matched, how many required fields have no column, the sheets that would break, warnings and the error. The command exits with 1 if any file was not written, so a script or CI job can stop on it. Nothing is overwritten without `--overwrite`.

- **A file that does not fit is not written.** By default every required field must find a column, so a wrong file never becomes a half-broken workbook. `--min-mapped 0.9` writes a file when at least that share of the required fields match, and `broken_sheets` names what will not work. `--on-error stop` ends at the first file that fails.
- **Per-customer values.** `customers.csv` has a `file` column (the file's name, or its path under the folder), an optional `sheet` column for Excel files, and one column per parameter caption of the template, such as `file,Customer name,Top N`. An empty cell keeps the batch value (`-p NAME=VALUE`). Columns that are not parameters are an error, checked before anything is written. Files in the folder with no row are still made, without per-file values.
- **Mapping.** Each file is matched on its own; `--mapping map.csv` applies one edited mapping to all of them, and `--answers` (an earlier output or an answers file) uses its saved choices as the starting point and only suggests columns for what is left.
- `--workers N` uses several processes (at most the CPU count); the files are independent, so the output is the same.

**Excel.** `--data q3.xlsx` (or `.xlsm`) reads one worksheet, which needs the optional `openpyxl` (`pip install "py-tbparse[excel]"`). Pick the sheet with `--sheet NAME` or `--sheet 0` (an index from 0); with several visible sheets and none picked the command fails and lists them, and a hidden sheet is only read when it is named. The first non-empty row is the header, wherever it sits; a blank header becomes `F1`, `F2`... and a repeated one gets a number (`name`, `name1`) with a warning; the next 2000 rows decide each column's type (a column of whole numbers is an integer, dates and date-times are told apart by their time of day). The output connects to the file with Tableau's own `excel-direct` driver, written the way Tableau writes it (the shape and the remote types were measured over the 88 Excel workbooks of the test corpus), and the answers remember the sheet, so `--answers` repeats the run. The old `.xls` and `.xlsb` formats are refused: save as `.xlsx`. `--check` reads values only from a CSV.

**Tokens.** For one dashboard delivered to many customers, write `{{customer}}` as plain text where the customer's name should appear, and give each workbook its own value:

```bash
py-tbparse template make sales.twbx --token customer="Your company"      # a default; leave it out to make the value required
py-tbparse template apply sales.template.twbx --data acme.csv --token customer=ACME --write
py-tbparse template apply-folder sales.template.twbx customers/ --inputs customers.csv    # a `customer` column fills it per file
```

A token is `{{name}}`: a letter, then letters, digits, `_`, `-` or spaces (names are case-sensitive; the spaces around a name are ignored). A literal `{{` is written `{{{{` and a literal `}}` is `}}}}`. Tokens are found in these places, each with its own rule and never by a blind search over the XML: the **titles** of worksheets and dashboards, **text boxes** on dashboards, **field captions** and the **datasource caption** (with the copies a sheet keeps of them), and the **value, allowed values and aliases of a string parameter** (the value is stored as a Tableau string literal, so a customer called `O"Neil` is quoted correctly, and the saved parameter value is checked against the allowed values after the fill). Not places in this version: worksheet and dashboard *names* (renaming one means rewriting every reference to it), parameter captions (the caption is how a parameter is addressed), default filter values, tooltips and captions. A `{{token}}` inside a **formula** or SQL is left exactly as it is, never filled, and `template make` warns; so does a token that Tableau cut in two because part of it was formatted differently (a token must sit in one text run: format all of it the same way).

The manifest lists each token with where it occurs and its default (`template show` prints them; `template make` says how many it found), so `template update` can say what a new revision changed: a token added with no default and no saved value is `needs-value` and the update stops until you pass `--token`, a saved value for a token that is gone is dropped and reported, and a new revision keeps the default of every token it still has. Apply fills a token from, in order, the explicit value (`--token`, `tokens=`), the profile's `tokens`, the saved answers, then the default; a token with none stops the apply and lists every place it occurs. The values you gave are kept in the answers (`tokens`, not the defaults), so `--answers` repeats the run byte for byte. A value is plain text: it is written through the XML library (`<`, `&`, quotes and any alphabet are fine) and is not expanded again, so a value containing `{{x}}` stays as typed. A template whose workbook has no token syntax at all is not touched: no `tokens` key, no change to its text. In a folder run, a column of the `--inputs` file whose name is a token fills it for that file (a name that is both a parameter caption and a token is refused as ambiguous). Opening a filled workbook in Tableau has not been checked by hand; the text edits are the kind Tableau itself makes, and every filled output of the 200-workbook corpus adds no schema or reference errors.

**Limits.** A CSV or one Excel sheet feeds one table. A template whose datasource joins several tables needs a workbook or `.tds` as its data, so the joins come along. A CSV-backed and a workbook-backed output have been opened in Tableau and drew their sheets (one workbook, see [verify-in-tableau.md](verify-in-tableau.md)); other shapes, an Excel-backed output among them, have only been checked by the tests (schema, references, 200 workbooks), so open one before relying on it: the verification pack has an Excel file for it.

`p.get_field_usage()` (or `field_usage(p)`, the `field-usage` table) is the analysis behind `required`: for every field, the sheets, dashboards and calculations that use it.

**Checks.** Output is checked against Tableau's published schema and for dangling references (`py_tbparse.verify.validate_workbook`) on every workbook of the corpus; how to check it in Tableau yourself is in [verify-in-tableau.md](verify-in-tableau.md).
