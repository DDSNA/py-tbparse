# Tableau Desktop check list (about 30 minutes)

Part of [py-tbparse](https://github.com/DDSNA/py-tbparse). Issue [#82](https://github.com/DDSNA/py-tbparse/issues/82).

**Status: not run.** Nothing py-tbparse writes has been checked in Tableau Desktop except one template path ([verify-in-tableau.md](verify-in-tableau.md)). This page is the short list for a person who has Tableau Desktop; the longer notes per feature are in that file. Fill the Result column (or `results.csv`, made with the pack) and report back on the issue.

## Make the files (1 minute)

```bash
python scripts/make_tableau_check_pack.py ~/tbparse-check      # a new folder; needs no corpus
```

It writes every file below from committed inputs (`docs/demo/coffee-shop.twb`, `tests/fixtures/public/filtering.twb` which Tableau wrote, `tests/fixtures/library/`, `tests/fixtures/style/palettes.twb`), plus `commands.txt` (the exact command behind each file), `results.csv` and `templates/report.txt` (schema and reference checks). Run it on the machine with Tableau: the CSV connections hold absolute paths. Two inputs are not the demo: the demo is hand-made and has **no connection, and its sheets name no datasource**, so templates, library, scaffold and the copy commands cannot use it.

**Pass** below means: opens with no error, "repair" or "unsupported feature" dialog, lists every sheet and dashboard the row names, shows no red `!` beside a field, and draws what the row says. **Fail** is any dialog (copy its text word for word), a missing sheet, a field with a red `!`, an "unknown field", or changed colours, fonts or layout compared with the baseline. A server or file prompt is expected only where the row says so; answer Cancel and go on. Stop reading a file at its first fail.

## Do these first (5 minutes): baselines

| File | Pass | Result |
|---|---|---|
| `00-filtering-original.twb` | Opens; asks for the SQL Server login (expected, the host is unreachable); lists `Sheet 1`, `Sheet 2` and dashboard `setTest`. If this fails, every file made from it says nothing. | |
| `00-demo-original.twb` | Opens with sheets `Sales by Region`, `Profit Trend`, `Top Products`, `Returns Detail` and dashboards `Weekly Overview`, `Product Review`. It is hand-made and has no data, so sheets are empty. **If it will not open, files 10 to 12 and 40 cannot be judged: note the message and skip them.** | |

## Highest value first (10 minutes)

| File and command | What to look for | Result |
|---|---|---|
| `40-palettes.twb`: `style import palettes.twb coffee-shop.twb --write` | Do this **before** 41, on a Tableau whose `Preferences.tps` lacks these palettes. Opens; on any colour legend, Edit Colors lists `Acme Brand` (4 colours, categorical), `Acme Ramp` (sequential) and `Acme Diverging`. Fail: not offered, wrong colours, a dialog. | |
| `41-Preferences_new.tps`: `style export palettes.twb -o ...tps` | Back up `My Tableau Repository/Preferences.tps`, copy this file over it, restart. Same three palettes in Edit Colors, in the same order and with the same names. Fail: Tableau ignores the file or reports it. Put your own back afterwards. | |
| `30-library.twb`: `library export source.twb`, then `library import target.twb ... --on-clash rename --write` | Opens (a "file not found" prompt for `C:/data/orders2024.csv` is expected). Data pane has 9 added calculations (`Profit Ratio (2)`, whose caption was taken, then `Sales by Category`, `Running Sales`, `Margin Gap`, ...) and the parameters `Top N`, `Metric`, `Free text`; none in red. Edit `Profit Ratio (2)`: the formula reads `SUM([Profit])/SUM([Revenue])` (the library's `Sales` was mapped to the target's `Revenue`) and is valid; `Margin Gap` refers to it. Fail: calculation missing, "invalid" or red, a parameter without its values. | |
| `42-fonts.twb`: `style apply format.style.json format-bare.twb --scope workbook --write` | Made from a copy of `filtering.twb` without any workbook style. Opens with no dialog. Format > Workbook, and the title and tooltip formats, show `Segoe UI` size 10 (title `Segoe UI Semibold` 14, colour `#1A3A5C`); sheet text follows where it has no font of its own. Fail: a dialog, nothing changes, or the font is gone after a save and reopen (Tableau dropped the new `<style>` block). A missing font may be replaced silently: note it. | |
| `44-fonts-keep.twb` and `44-fonts-force.twb`: the same style applied to `format-target.twb`, which already sets the title font to `Arial`, without and with `--force` | `44-fonts-keep`: the title font is still `Arial` (the explicit format is kept), the other fonts are the new ones. `44-fonts-force`: the title font is `Segoe UI Semibold`. Fail: any dialog, or the reverse. (File 43, dashboard defaults, comes with a later package.) | |
| `templates/2-template-on-csv.twbx`, `3-template-on-workbook.twbx` | Already opened once (see verify-in-tableau.md); re-check quickly: no server prompt, both sheets draw the sample values. | |
| `templates/4-template-on-excel.twbx` | No prompt, sheets draw, date fields show the calendar icon. Never opened. | |
| `templates/5-template-on-db.twbx` | Prompts for a login, then cannot connect to `db.example.invalid` (expected); the workbook still opens and lists sheets and fields. Fail: repair or "unsupported" message, a missing datasource. | |
| `templates/56-template-update.twbx`: `template update rev2.twbx 2-template-on-csv.twbx --old template.twbx --write` | Same as file 2. The revision changes nothing in the workbook, so any difference from file 2 is a fail. | |
| `templates/57-apply-folder/*.twbx`: `template apply-folder template.twbx data -o ...` | Three workbooks (CSV, Excel, PostgreSQL target) open like files 2, 4 and 5. | |

## The rest (10 minutes)

| File and command | What to look for | Result |
|---|---|---|
| `10-rename.twb`: `rename coffee-shop.twb --all --write-workbook` | Field captions are tidy (`Order ID`, `Sales Usd`, ...) and the sheet is now `Sales By Region`; dashboards keep their names; the data pane and sheets otherwise match the baseline. Fail: a field shows its internal name, a sheet loses a field. | |
| `11-prune.twb`: `prune coffee-shop.twb --sheets --write` | `Returns Detail` and the calculations `Loyalty Score` and `Old Discount` are gone; everything else as in the baseline. Fail: anything else missing, or a sheet now broken. | |
| `12-slice.twb`: `slice coffee-shop.twb -d "Weekly Overview" --write` | Only dashboard `Weekly Overview` with `Profit Trend` and `Sales by Region`; no `Product Review`, `Top Products`, `Returns Detail`; the `Target Margin` parameter is gone. | |
| `13-sanitize.twb`: `sanitize filtering.twb ... --placeholders` | Opens; Edit Data Source shows server `server.example.com`, database `database` and user `user` (placeholders; the login prompt is expected); no thumbnails. Watch for any repair dialog: the published schema flags the missing `<thumbnails>`, Tableau may not mind. | |
| `14-sanitize-fake-data.twbx`: `sanitize ... --fake-data` (`.twbx`) | Opens **without** a server prompt, reading the packaged `Data/synthetic/*.csv`; Edit Data Source shows that one text file; both sheets draw made-up values (a broken sheet here is plausible: it is experimental). | |
| `20-sheet-copy.twb`: `sheet copy filtering.twb --sheets "Sheet 1" --to filtering.twb --on-clash rename --write` | Tabs: `Sheet 1`, `Sheet 2`, `Sheet 1 (2)`; the copy draws the same chart as `Sheet 1`. | |
| `21-dashboard-copy.twb`: `dashboard copy ... --dashboards setTest --on-clash rename` | A second dashboard `setTest (2)` with both copied sheets in the same layout and filters that work. | |
| `22-scaffold.twb`: `scaffold make filtering.twb -o x.scaffold.json`, then `scaffold apply ... --name "Scaffold Check" --sheets "Sheet 2,Sheet 1" --write` | New dashboard `Scaffold Check`, two side-by-side zones with the sheets swapped (`Sheet 2` left); `setTest` untouched. Fail: empty zones, a layout that overlaps. | |

## After each file, and at the end

Save from Tableau, close, reopen; note any warning at save time. Record: `opens / opens with a message / does not open`, then what you saw (a screenshot of any dialog helps most). Put the result in the issue and add the Status lines to [verify-in-tableau.md](verify-in-tableau.md). Open one issue per fail, with the file name and the `commands.txt` line.

Not Tableau files, so not on this list: audit and dictionary reports, tables and graphs, `*.scaffold.json`, `*.library.json`, answers files, `summary.csv`. The GUI (`py-tbparse-gui`) runs the same writers and is not checked separately. Not covered because they need files not in the repository: the corpus examples in verify-in-tableau.md (a real multi-datasource slice, sheet copies between two different workbooks).
