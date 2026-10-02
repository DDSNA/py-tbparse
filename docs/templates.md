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

**Mapping.** Each required field is matched to a column of the new data by name, ignoring case and separators (`ORDER_DATE` → `Order Date`), with close spellings accepted above `--cutoff`. Types are checked like Tableau's Accelerator mapper: a text column is never offered for a number or a date, while integer vs decimal and date vs date-time map with a warning. A field whose type the author changed in Tableau keeps that type, and Tableau converts the column. Before anything is written you see which sheets would break for each field left without a column; writing then needs `--allow-missing`. Edit the mapping as a CSV, as with renames.

**What gets written.** The template's connection is replaced by one to the new data (a CSV file, or the connection of the workbook / `.tds` you pass). Every field keeps the local name its sheets and formulas use; only the physical column behind it changes. Parameter values are set with `-p NAME=VALUE`, checked against the parameter's type and its list of allowed values. The output (`<template>_<data>.twbx` beside the template, never overwritten) also stores `template-answers.json`: which template, data, mapping and parameters made it, so it can be re-made or checked later.

**Limits.** A CSV feeds one table. A template whose datasource joins several tables needs a workbook or `.tds` as its data, so the joins come along. Excel files are not read directly yet; save as CSV or pass a workbook connected to the sheet. As with renames, I have not opened the generated workbooks in Tableau itself, so check one before relying on it.

`p.get_field_usage()` (or `field_usage(p)`, the `field-usage` table) is the analysis behind `required`: for every field, the sheets, dashboards and calculations that use it.
