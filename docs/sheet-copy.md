# Sheet copy

Part of [py-tbparse](https://github.com/DDSNA/py-tbparse). `py-tbparse sheet copy` copies worksheets from one workbook into a copy of another. This is the first slice: the sheets must use a datasource the target already has, under the same internal name. Nothing it writes was opened in Tableau Desktop; it is checked by re-reading, by Tableau's published XML schema and by the integrity checks of this project, not by Tableau. Open a copy first.

```bash
py-tbparse sheet copy sales.twb --sheets "Sales by region,Profit map" --to other.twb                 # the plan only
py-tbparse sheet copy sales.twb --sheets "Sales by region" --to other.twb --write -o merged.twb
py-tbparse sheet copy sales.twb --sheet "Sheet 1" --to other.twb --on-clash rename --write -o merged.twb
```

`--sheets` takes a comma-separated list; `--sheet` is repeatable for a name that contains a comma. Without `--write` nothing is written. The output keeps the target's format (a `.twbx` keeps its members), defaults to `<TARGET>_sheetcopy.<ext>`, and is never the source or the target (`--overwrite` replaces an existing output only). `--format json` prints the report as JSON.

The GUI has a **Slice and copy** view for this (tick, see the plan, download), see [gui.md](gui.md).

## What a sheet needs

For each sheet:

1. It must use exactly one datasource besides Parameters (a blend is refused).
2. The target needs a datasource with the same connection (class, server, database, file name, tables...) **and** the same internal name. A different name is refused with a message that names the target's datasource.
3. Every physical field, group and bin the sheet needs must exist in the target. The needs are followed from the source datasource, not taken from the sheet's cached list, so the calculations a calculation uses are found too.
4. Missing calculations and parameters are added to the target by the same planner as `library import` ([libraries.md](libraries.md)). An identical one in the target is reused.

A refused sheet is listed with the reason and the others are copied (exit code 2). If no sheet can be copied nothing is written (exit 1).

## Clashes: `--on-clash`

`fail` (the default), `rename` or `skip`, for calculations, parameters and sheet names alike.

| | calculation or parameter | sheet name (worksheet or dashboard of the target) |
| --- | --- | --- |
| `fail` | the run stops before anything is written | the run stops before anything is written |
| `rename` | the new one gets a free caption (`X (2)`) and, if its internal name is taken, a new internal name; the copied sheet is pointed at it | the copy is named `Name (2)`, the next free number |
| `skip` | the target's field is kept and the sheets use it (as in `library import`) | the sheet is not copied |

A bin, group or set of the same name with another definition is a refusal of that sheet under `rename` and `skip` (a group or set cannot be renamed or replaced here); under `fail` the run stops for a group or set. Groups and sets are compared by their `groupfilter` tree: the members and levels, with the operands of a union or intersection in any order.

A calculation that uses a clashing one counts as clashing too, even when its own formula text matches the target's, because it would show other values there. `rename` renames it and points the sheet at it; `skip` refuses the sheet and names the calculations (keeping the target's version would change the numbers).

## What is dropped

Dropped and reported, never silently:

- Action filters (a filter on an `[Action (...)]` group). They belong to a dashboard action, which is not copied, so they would filter on nothing.
- Viz-in-tooltip references to sheets that are not copied (a sheet that is copied under a new name is followed).
- The report also counts dashboard actions that name the sheet; actions are not copied.

`--strict` stops the run instead of dropping anything.

## Not covered

Dashboards (see [dashboard-copy.md](dashboard-copy.md)), actions, thumbnails (the copy has none), sets, groups and bins to add, blends, a datasource the target lacks, a different internal name for the same connection, field mapping inside sheets, and images or shapes of a `.twbx`. The result is checked against the schema and the dashboard integrity check relative to both workbooks, and over the corpus (`tests/test_sheetcopy_corpus.py`, skipped when the corpus is not fetched, so a local check: `python scripts/fetch_corpus.py`, then `pytest -m corpus`; the weekly and on-demand `Corpus` workflow does the same, see [development.md](development.md)); none of that proves Tableau opens it. See [verify-in-tableau.md](verify-in-tableau.md).

Python: `plan_sheet_copy(source, target, sheets, on_clash="fail", strict=False)`, `build_sheet_copy(...)` (bytes and report) and `copy_sheets(..., output_path=None, overwrite=False)` in `py_tbparse.sheetcopy`.
