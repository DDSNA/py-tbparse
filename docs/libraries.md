# Libraries of calculated fields and parameters

Part of [py-tbparse](https://github.com/DDSNA/py-tbparse).

A library is a small JSON file (`*.library.json`) that holds the calculated fields and parameters of one datasource. You can take them out of one workbook and add them to another, so a set of KPIs does not have to be typed in again.

**Read this first.** The workbook this writes follows what Tableau writes for these objects: the shapes were measured on the 200-workbook test corpus, and the output passes the schema and reference checks the rest of the tool uses. It has never been opened in Tableau. Add libraries to a copy (the tool never overwrites your file) and open the copy in Tableau before you rely on it. The six assumptions that nobody has checked are at the end of this page.

## What it covers

- Calculated fields (including level-of-detail and table calculations) and parameters (range, list and any-value).
- Not covered yet: sets, groups, bins, folders on import, replacing a field that already exists (`overwrite`). A calculation that uses a set, group or bin keeps the reference, and the target must already have that object under the same name. A calculation that refers to another datasource (`[other].[Field]`) is not exported; the export says which ones.

## In the GUI

The [Libraries view](gui.md#libraries) lists the workbook's calculations and parameters with a selection, exports the selection as a library file, and adds an uploaded library file to the open workbook. The clash policy is chosen on the page and defaults to `fail`, as in the command line; the plan and the clashes are shown before anything is made, and the result is a download. It never writes over the open workbook or any other file. It has no mapping file (fields are matched by name and close name only).

## Command line

```bash
py-tbparse library export sales.twb -o sales.library.json              # every calculation and parameter of the one datasource
py-tbparse library export sales.twb -o kpis.library.json --folder KPIs  # or one folder, or --field "Profit Ratio" (repeatable)
py-tbparse library show kpis.library.json                               # entries, what they need, formulas with captions (--markdown for a page)
py-tbparse library import other.twb kpis.library.json                   # print the plan, write nothing
py-tbparse library import other.twb kpis.library.json --write           # write other_library.twb beside it
```

Options: `export` takes `--datasource` (needed when several datasources have a connection), `--folder`, `--field`, `--no-dependencies`, `--no-parameters`, `--name`, `--description` and `--overwrite`. `import` takes `--datasource`, `--mapping`, `--on-clash`, `-o`, `--overwrite`, `--write` and `--format`. `import` exits 1 on an error and 2 when some entry could not be imported (the rest is still written).

## How an import works

1. **Fields the calculations need** (`Sales`, `Profit`, ...) are looked up in the target datasource: an explicit mapping first, then the same name, then the same matching that templates use (case and separators ignored, close names, types checked). The plan shows how each one matched. A mapping is a CSV with `field` and `mapped_to` (the target's column name), like the one `template apply --mapping-out` writes, or a Python dict.
2. **Entries go in dependency order**: parameters first, then a calculation after the ones it uses.
3. Each entry is, in this order:
   - `skip-identical`: the target already has it (same internal name with the same caption, type and formula, or the same caption with the same definition under another name). A workbook imported into itself is all `skip-identical`.
   - `fail-unmapped`: it needs a field the target has no match for. Whatever depends on it becomes `fail-dependency`. The others are still added.
   - `add`: the formula is rewritten to the target's field names and written after the target's last column. Parameters go into the `Parameters` datasource (created if the workbook has none).
   - `add-renamed` or `skip-clash`: the target already has a different field with that caption. `--on-clash rename` adds `(2)` to the caption, or the next free number; `skip` keeps the target's field and points the new calculations at it; `fail` (the default) stops before anything is written. Until this change the command line defaulted to `rename` while the Libraries view defaulted to `fail`; both are `fail` now. The Python functions (`plan_import`, `import_library`...) still default to `rename`.
4. An internal name that is taken (parameters are usually all `[Parameter 1]`) is replaced by a free one, and every formula that uses it follows. Nobody sees this in Tableau.

Text in quotes is never rewritten: `"[Sales] is "` stays as it is.

## From Python

```python
from py_tbparse import TwbParser, export_library, save_library, load_library, plan_import, import_library

lib = export_library(TwbParser("sales.twb"), select=["Profit Ratio"])   # a dict
save_library(lib, "kpis.library.json")

target = TwbParser("other.twb")
plan_import(target, load_library("kpis.library.json"))                  # a table; nothing is written
report = {}
import_library(target, "kpis.library.json", on_clash="skip", report=report)   # returns the new file's path
```

`report` gets a count and a `<name>_names` list for `added`, `skipped_identical`, `renamed`, `skipped`, `failed`, `skipped_dependents` and `renamed_internal`.

## What nobody has checked in Tableau

1. Tableau accepts a calculation or parameter column added after the existing columns with no copy in any worksheet, and shows it in the data pane.
2. The generated names, `[Calculation_<18 digits>]` and `[Parameter N]`, are fine. The corpus shows names are free text, not how Tableau makes them.
3. A clashing caption is named `X (2)` the way Tableau's paste does. That comes from research, not from a test.
4. A calculation Tableau made on its own (a split field, a date bin) works as an ordinary calculation once its `user:` attributes are dropped. They name the source datasource, so they are not exported.
5. A new `Parameters` datasource (version 18.1) also loads in older Tableau versions.
6. Comparing formulas as text (only line endings made the same) is close enough to "identical". Two formulas that differ only in spacing count as different, and the import then adds the copy with a new caption instead of skipping it.
