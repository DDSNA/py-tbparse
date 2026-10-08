# Slice: keep selected dashboards, drop the rest

Part of [py-tbparse](https://github.com/DDSNA/py-tbparse). `slice` turns a workbook with many dashboards into one with only the dashboards you name. It is called `slice` and not `extract` because `extract` means a Tableau data extract (`.hyper`) everywhere else in this package. Nothing here was opened in Tableau Desktop: the command edits the XML of the `.twb`/`.twbx`, and the result is checked against the XML schema, by the dashboard reference checks and by re-reading it, not by Tableau.

```bash
py-tbparse slice sales.twb --dashboards "Overview,KPIs"                  # dry run: what stays, what goes
py-tbparse slice sales.twb --dashboards "Overview,KPIs" --write -o sales_overview.twb
py-tbparse slice sales.twb -d Overview -d KPIs --write -o out.twb        # --dashboards can be repeated
py-tbparse slice sales.twb -d Overview --strict                          # refuse instead of dropping actions
py-tbparse slice sales.twb -d Overview --no-prune --write -o out.twb     # skip the clean-up of unused fields and datasources
py-tbparse slice sales.twb -d Overview --format json                     # the report as JSON
```

The GUI has a **Slice and copy** view for this (tick, see the plan, download), see [gui.md](gui.md).

From Python: `from py_tbparse import slice_workbook, slice_doc`. `slice_workbook(path, ["Overview"], "out.twb")` writes; without the output path it is a dry run. `slice_doc(doc, names, strict=False, prune=True)` slices an lxml document in place, for use as a step of another edit (pass a deepcopy to keep the original).

## What stays and what goes

Kept: the named dashboards, every worksheet on them, and, until nothing new is added, every dashboard or worksheet that something kept names. That covers a story's captured sheets, a viz in a tooltip (`<Sheet name="...">`), a nested dashboard, and any other attribute or text that is exactly the name of a sheet. Doubt keeps a sheet.

Removed:

- the other dashboards and stories, and the other worksheets, hidden ones included (the audit's A006 spares hidden sheets, so `prune --sheets` would not do this);
- the windows and thumbnail records of everything removed, and a viewpoint of a removed sheet inside a window that stays;
- actions that depend on something removed (below);
- then `prune_doc` runs with sheets, calculations, parameters and datasources, so calculations, parameters and datasources that only the removed sheets used go too, and nothing is left naming something that is gone. `--no-prune` skips this step. Note that this prune also removes calculations that were already unused before the slice.

## Actions

An action is dropped when its source (`dashboard=` or `worksheet=`) or its target (`target`, or the `sheet` of a go-to-sheet action) is a dashboard or worksheet that did not stay. The filters in kept sheets that such an action drove (`user:ui-action-filter`) are dropped with it, otherwise they would name an action that no longer exists. A removed sheet named in an action's `exclude` list is taken out of the list and the action stays. All of it is listed in the report (`dropped_actions`, `trimmed_actions`, `dropped_filters`). With `--strict` nothing is changed and the command stops with exit code 2, naming what would have been dropped.

Not touched: hidden `[Action (...)]` groups in a datasource. If a kept filter still uses one, it stays; otherwise the datasource check of prune only removes a whole datasource, not a group inside one.

## Errors

- An unknown dashboard name fails and lists the valid names. Names are separated by commas; a name that contains a comma works when it is the only one.
- A selection that shows no worksheet (an empty story, say) is refused: a workbook needs at least one worksheet.
- The output must end in the input's extension, an existing output is refused without `--overwrite`, and the input is never written.
- Exit code 0, or 2 for an error. If the result has an integrity problem the input did not have (`dashboards.integrity_check`), nothing is written and the command exits 2. A dry run exits 2 too (it prints the `INTEGRITY` lines and says `--write` would refuse), so it predicts the write.

## What was checked, and what was not

Tested on a synthetic workbook (`tests/test_slice.py`: tooltip sheet, hidden sheet on a removed dashboard, actions dropped and trimmed, strict, prune of a datasource, calculation and parameter, story, `.twb` writing, CLI) and over the 200-workbook corpus (`tests/test_slice_corpus.py`, skipped when `tests/corpus/files` is missing, so a local check: fetch it with `python scripts/fetch_corpus.py`, run `pytest -m corpus`; the weekly and on-demand `Corpus` workflow does the same, see [development.md](development.md)): for the 19 workbooks with two or more dashboards, keep the first. The result re-parses, schema errors and A003 (missing reference) do not rise, `integrity_check` finds nothing new, and a second slice of the output is a no-op. A one-off run keeping each dashboard in turn (46 slices, two refused for showing no worksheet) found no new schema or integrity problem.

Not checked, and the weak spots:

- Nothing was opened in Tableau Desktop; see [verify-in-tableau.md](verify-in-tableau.md) for the files to try.
- The schema is Tableau's newest and most real workbooks already fail it, so the check only proves no new errors.
- The dropped-filter path (`dropped_filters`) is covered by a synthetic test only; no corpus workbook triggered it.
- A `.twbx` keeps all its members: thumbnails and extracts of removed sheets and datasources stay in the package.
- Story points that capture a removed dashboard cannot occur (a captured sheet is kept), but their saved filter state (`currentDeltas`) is not edited.
- "Used" is by name over the workbook, so a sheet is kept when something merely repeats its name.
