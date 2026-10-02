# Renaming fields and other objects

Part of [py-tbparse](https://github.com/DDSNA/py-tbparse).

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
