# Workbook templates

Part of [py-tbparse](https://github.com/DDSNA/py-tbparse).

Turn a finished workbook into a template, then make new workbooks from it with other data. Every sheet, dashboard, calculation and format comes along; only the data changes. The idea comes from Tableau's Accelerators and Power BI's `.pbit` files.

```bash
py-tbparse template make sales.twbx                         # writes sales.template.twbx
py-tbparse template show sales.template.twbx                # the fields it needs, and its parameters
py-tbparse template show sales.template.twbx --markdown -o SALES.md   # the same as a page to review in git
py-tbparse template check sales.template.twbx --fail-on warning       # lint it before sharing (CI-friendly)
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

The report lists every change (fields added, removed, renamed, caption, required, type, role; parameters added, removed, default, allowed values; sheets and dashboards) with its effect on the saved answers: `auto-carry` (the saved choice still applies), `needs-mapping` (a required field has no column), `orphaned` (the saved choice names something the template no longer has), `type-conflict` (the saved column or value no longer fits), `optional` (a new field no sheet needs). Fields are matched by `uid`, then by name; a field that kept its source column or caption under a new name counts as renamed, and its saved column moves with it. `--write` stops on `needs-mapping` rows and on a saved column of the wrong type (supply an edited `--mapping`, or `--allow-missing`), drops a saved parameter value the template no longer accepts (the template's default applies, and the command says which), and reports which data columns appeared or vanished. The same template is a no-op. The "before" is the manifest the workbook's answers keep (workbooks made before 0.4.6 do not have it: pass `--old OLD_TEMPLATE`, or the report only checks the new template against the answers). It never merges edits made to the workbook itself in Tableau; it starts again from the new template. It updates one datasource at a time and refuses a workbook made from several.

**What gets written.** The template's connection is replaced by one to the new data (a CSV file, or the connection of the workbook / `.tds` you pass). Every field keeps the local name its sheets and formulas use; only the physical column behind it changes. Parameter values are set with `-p NAME=VALUE`, checked against the parameter's type and its list of allowed values. The output (`<template>_<data>.twbx` beside the template, never overwritten) also stores `template-answers.json`: which template, data, mapping and parameters made it, so it can be re-made or checked later.

**One template, many files.** For the same dashboard delivered to many customers, branches or months:

```bash
py-tbparse template apply-folder sales.template.twbx customers/ -o out/ --inputs customers.csv
```

Every `.csv`, `.tsv`, `.xlsx` and `.xlsm` in the folder gets its own workbook, `out/sales_<file>.twbx` (a stem used by two extensions gets `_2`), and `out/summary.csv` lists what happened to each file: `status` (`ok`, `skipped`, `error`), how many columns matched, how many required fields have no column, the sheets that would break, warnings and the error. The command exits with 1 if any file was not written, so a script or CI job can stop on it. Nothing is overwritten without `--overwrite`.

- **A file that does not fit is not written.** By default every required field must find a column, so a wrong file never becomes a half-broken workbook. `--min-mapped 0.9` writes a file when at least that share of the required fields match, and `broken_sheets` names what will not work. `--on-error stop` ends at the first file that fails.
- **Per-customer values.** `customers.csv` has a `file` column (the file's name, or its path under the folder), an optional `sheet` column for Excel files, and one column per parameter caption of the template, such as `file,Customer name,Top N` (or per token, see Tokens below). An empty cell keeps the batch value (`-p NAME=VALUE`). Columns that are neither parameters nor tokens are an error, checked before anything is written. Files in the folder with no row are still made, without per-file values.
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

**Check a template before you share it.** `py-tbparse template check TEMPLATE` (or `py_tbparse.check_template(path)`) lints a template and prints one row per finding: `rule`, `severity` (`error`, `warning`, `info`), `object`, `detail` and `fix`. `--format table|csv|json`, `--only T001,T003` and `--skip T008` choose the output and the rules; `--fail-on error|warning|info|never` (default `error`) sets the severity that makes the exit code 1, so it can run in CI (exit 2 means the template could not be read or an option was wrong). Findings go to stdout, the count to stderr. The same template always gives the same rows in the same order. Rule ids are stable, so put them in CI configs without fear of renumbering:

| Rule | Severity | Looks for |
|---|---|---|
| T001 | warning | a connection that still names a server, database, file, directory, warehouse or service (an apply replaces it, so this matters only for a template shared as it is) |
| T002 | info | a version 1 manifest, or one with no `id`: `template update` cannot match it |
| T003 | error | a parameter with no value, or a value outside its allowed list |
| T004 | info | a datasource with several tables (a CSV or one Excel sheet feeds one table) |
| T005 | warning | data, a cached query or an extract still packaged in the `.twbx`, with its size |
| T006 | info | a required field nothing uses (only a hand-edited manifest does that), and per datasource the optional fields used by nothing (candidates to drop) |
| T007 | error / warning | dangling references: `validate_workbook`'s findings on the template's workbook, with their own severity |
| T008 | info | a calculation with a string that looks like a URL, UNC or drive path, e-mail address or a text over 50 characters; a **heuristic**, parameter defaults are not examined |
| T009 | | reserved for the token rule: tokens are merged (see Tokens above), the rule is planned next and not built yet (`--only T009` says it is reserved) |
| T010 | info | no description, or the name is the source file's name |

A template made from a real workbook nearly always has T001 (it still carries the connection it was made from) and T010 (the default name), so `--fail-on warning` is for a template you made on purpose with a name and a cleaned connection. T007 can also report what the original workbook already had; read it as "this template has a dangling reference", not as "py-tbparse broke it". These are lint rules about what an author probably did not mean; none says Tableau will refuse the file.

The engine is `py_tbparse/findings.py` (`rule`, `run_rules`, `format_findings`), shared with the workbook audit planned next (WP10): a rule is a function that yields `finding(object, detail)` rows, registered with an id and a scope. A rule that crashes shows up as one `error` finding instead of stopping the run. The template rules are in `py_tbparse/template_check.py`; the token rule (T009, planned next) will be one more function there.

**A page for a template.** `template show --markdown` (`py_tbparse.template_markdown(template)`) prints a Markdown page: name, description, id and revision, the required and optional fields with their types and the sheets that use them, the parameters with defaults and allowed values, tokens (once a template declares them), the connections it was made from (never a user name or password), the worksheets with the template fields each uses, and the dashboards with their worksheets. The order is fixed and there is no timestamp of its own, so the page can be committed and its changes reviewed. `-o FILE` writes it to a file. The renderer is `py_tbparse/docgen.py` (`md_table`, `heading`, `inline_code`, `code_block`; pipes, line breaks and `<` are escaped); the workbook data dictionary will use the same one.

**Limits.** A CSV or one Excel sheet feeds one table. A template whose datasource joins several tables needs a workbook or `.tds` as its data, so the joins come along. A CSV-backed and a workbook-backed output have been opened in Tableau and drew their sheets (one workbook, see [verify-in-tableau.md](verify-in-tableau.md)); other shapes, an Excel-backed output among them, have only been checked by the tests (schema, references, 200 workbooks), so open one before relying on it: the verification pack has an Excel file for it.

`p.get_field_usage()` (or `field_usage(p)`, the `field-usage` table) is the analysis behind `required`: for every field, the sheets, dashboards and calculations that use it.

**Checks.** Output is checked against Tableau's published schema and for dangling references (`py_tbparse.verify.validate_workbook`) on every workbook of the corpus; how to check it in Tableau yourself is in [verify-in-tableau.md](verify-in-tableau.md).
