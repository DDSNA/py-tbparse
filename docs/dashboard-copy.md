# Dashboard copy

Part of [py-tbparse](https://github.com/DDSNA/py-tbparse). `py-tbparse dashboard copy` copies dashboards, with every sheet on them, from one workbook into a copy of another. It is [sheet copy](sheet-copy.md) plus the dashboard itself. Nothing it writes was opened in Tableau Desktop; it is checked by re-reading, by Tableau's published XML schema and by the integrity checks of this project, not by Tableau. Open a copy first.

```bash
py-tbparse dashboard copy sales.twb --dashboards "Overview,KPIs" --to other.twb                 # the plan only
py-tbparse dashboard copy sales.twb --dashboards "Overview" --to other.twb --write -o merged.twb
py-tbparse dashboard copy sales.twb --dashboard "Overview" --to other.twb --on-clash rename --write -o merged.twb
```

`--dashboards` takes a comma-separated list; `--dashboard` is repeatable for a name that contains a comma. Without `--write` nothing is written. The output keeps the target's format (a `.twbx` keeps its members), defaults to `<TARGET>_dashcopy.<ext>`, and is never the source or the target (`--overwrite` replaces an existing output only). `--format json` prints the report as JSON.

## What is copied

For each dashboard:

1. Every sheet on it (including the sheets that only a filter, parameter or legend zone names), by the rules and refusals of sheet copy: one datasource per sheet, the same connection **and** the same internal name in the target, every physical field present, missing calculations and parameters added by the library planner. If one sheet is refused, skipped or clashes under `skip`, the **whole dashboard is refused** (listed with the reason), and sheets only that dashboard needed are not copied. A sheet shared by two dashboards stays as long as one of them can be copied.
2. The dashboard itself, with the sheet names in its zones (and so on) rewritten when a sheet was renamed, the calculation and parameter renames of the library planner followed, and every `simple-id` renewed.
3. Its own `<datasources>` and `<datasource-dependencies>` (the fields that filter, parameter and legend zones use). Each datasource must match the target as above, and every field those dependencies name must exist in the target (after renames). Otherwise the dashboard is refused and the reason names the field.
4. A new dashboard window: the source's window, renamed, with new uuids and renamed viewpoints (a plain one when the source has none). The window of each copied sheet is hidden when it was hidden in the source.
5. Actions that are internal to the copied set: the source (dashboard and sheet) and all `target` parameters are copied dashboards or sheets. Names are followed through renames, including the URL-encoded dashboard name of a link action. An action name the target already has gets a new name.

A dashboard that shows another dashboard in a zone is refused.

## Clashes: `--on-clash`

`fail` (the default), `rename` or `skip`, for calculations, parameters, sheet names and dashboard names. There is no overwrite policy.

| | dashboard name (a worksheet or dashboard of the target) |
| --- | --- |
| `fail` | the run stops before anything is written |
| `rename` | the copy is named `Name (2)`, the next free number; sheets are renamed the same way when needed |
| `skip` | the dashboard (and sheets only it needs) is not copied |

## What is dropped

Dropped and reported, never silently:

- Actions that touch the copied set but also something outside it (a target dashboard that is not copied, a source sheet of another dashboard). They are listed under `actions` with the reason.
- Action filters on the copied sheets (a filter on an `[Action (...)]` group), as in sheet copy: the filter state an action left on a sheet is not copied. The actions themselves are, when they are internal.
- Viz-in-tooltip references to sheets that are not copied.

`--strict` stops the run instead of dropping anything, so a dashboard with an action filter on any sheet fails under `--strict`.

Exit codes: 0 done, 1 an error or the run stopped (a clash under `fail`, `--strict`, nothing copyable), 2 some dashboard was refused (the others are written).

## Not covered

Thumbnails (the copy has none), stories, sets, groups and bins to add, blends, a datasource the target lacks, a different internal name for the same connection, field mapping inside sheets, and images or shapes of a `.twbx`. The result must pass `integrity_check` with nothing new, and is checked against the schema relative to both workbooks, and over the corpus (`tests/test_dashboardcopy_corpus.py`, skipped when the corpus is not fetched). None of that proves Tableau opens it. See [verify-in-tableau.md](verify-in-tableau.md).

Python: `plan_dashboard_copy(source, target, dashboards, on_clash="fail", strict=False)`, `build_dashboard_copy(...)` (bytes and report) and `copy_dashboards(..., output_path=None, overwrite=False)` in `py_tbparse.dashboardcopy`.
