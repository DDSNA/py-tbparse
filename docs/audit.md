# Workbook audit and data dictionary

Part of [py-tbparse](https://github.com/DDSNA/py-tbparse).

Two read-only commands for a workbook: `audit` lists what its author probably did not mean, and `docs` writes a Markdown data dictionary. The GUI has an [Audit view](gui.md#audit) for the audit, with the data dictionary as a download. Neither writes to the workbook, and nothing here was opened in Tableau: the commands read the XML of the `.twb`/`.twbx` and say what they find there. This is the basic level; there is no health score. [`prune`](prune.md) removes what A001, A005 and A006 report, as a dry run unless told to write a new file. JUnit, SARIF and GitHub output are described in [ci.md](ci.md).

## Audit

```bash
py-tbparse audit sales.twb                          # a table of findings; exit 1 if there is an error
py-tbparse audit sales.twb --fail-on warning        # exit 1 on a warning or worse (error, warning, info, never)
py-tbparse audit sales.twb --only A001,A005 --format csv -o findings.csv
py-tbparse audit sales.twb --skip A006,A009 --format json
```

Findings go to stdout (or `-o`), the count to stderr. Formats are `table`, `csv`, `json` and the CI formats `junit`, `sarif` and `github` ([ci.md](ci.md)). Exit codes are the ones of `template check`: 0, 1 (a finding at `--fail-on`), 2 (the workbook cannot be read or an option is wrong) and 3 (a rule crashed; it is reported as an error finding and its traceback goes to stderr). The other commands use the codes differently: [cli.md](cli.md#exit-codes).

From Python: `from py_tbparse import audit; audit("sales.twb", only=["A001"])` returns a pandas DataFrame with the columns `rule, severity, object, detail, fix`, sorted so the same workbook always gives the same frame.

### Rules

Rule ids are stable: put them in CI configs. An id is never renumbered or reused. Every rule is a heuristic, none says Tableau refuses the file.

| Id | Severity | What it finds |
| --- | --- | --- |
| A001 | info | A calculated field that no worksheet uses, not even through another calculation. Hidden calculations, the `Number of Records` Tableau adds itself and workbooks with no worksheet are left alone. |
| A002 | warning | Two calculations of one datasource with the same formula (comments, spacing and keyword case aside). Formulas with no field in them (`1`) are ignored. |
| A003 | error | A calculation refers to a field the workbook does not have (`usage.missing_references`). Columns that an old workbook names only in the connection's column map, and a blended field the primary datasource declares, count as present. |
| A004 | error | Calculations that refer to each other in a circle, or to themselves. |
| A005 | info | A parameter that no worksheet, calculation, bin, set or group a worksheet uses, action, title or shown control uses. |
| A006 | info | A worksheet that is on no dashboard, story or tooltip and not hidden, in a workbook that has a dashboard or story. Zones that name a sheet through `type='sheet'`, `type-v2='worksheet'` or only a name count as placing it. |
| A007 | info | Custom SQL is present: datasource, query name and the first 80 characters. A `password=` or `token=` value and `user:pass@` are replaced by `***`. |
| A008 | info | A datasource points at a file on one machine: a file connection with an absolute local path, or an extract file at one (a temp or desktop copy). One finding per datasource; only the file name is printed, never the folder. An extract on its own, and a relative path, are not reported. |
| A009 | info | A calculation still has Tableau's default name (`Calculation1`, or no caption on `Calculation_123...`). |
| A010 | info | A calculation sits on a chain of more than 5 calculations. |
| A011 | info | A formula is longer than 1000 characters (the formula is never printed). |

### Tuning against the corpus

The first cut gave these counts over the 200-workbook corpus (`scripts/fetch_corpus.py`): A001 200, A002 8, A003 14, A005 18, A006 318, A007 2, A008 271, A009 8. Each rule's hits were read against the XML and the false positives fixed. No rule was removed, merged or renumbered; A008 changed meaning (below) and keeps its id. After tuning:

| Rule | Hits (workbooks) | What was wrong, what changed | Precision |
| --- | --- | --- | --- |
| A001 | 161 | 34 hits were Tableau's own `Number of Records`; 5 came from a workbook with no worksheet at all. Both are now skipped. | 161 of 161 hits have no `[Name]` or `:Name:` in any worksheet, dashboard, action or window (an automated check independent of `field_usage`); about 40 read by hand were real unused calculations. "True" means unused in this workbook; another workbook or a published datasource could still use one. |
| A002 | 8 (4 pairs) | Nothing wrong; kept as a warning. | 8 of 8: the formulas are identical (a `Duplicate` copy, two `SCRIPT_REAL` calls, two `DATENAME`). Whether the author meant two is not knowable. |
| A003 | 8 (5 workbooks) | 6 hits were false: fields that an old workbook (`csv.NNN` datasources, version 8.x) lists only in the connection's `<cols><map>`, and a blended field declared in the primary datasource's `datasource-dependencies`. Both now count as present. | All 8 read by hand: the field is nowhere in the workbook (`MISSING_METRIC` and `MissingField` are fixtures made to fail; `[F19]` and `[Purchase Date]` were removed from their data). |
| A005 | 16 | 2 hits were false: a parameter shown as a control (`<card param=...>`) and a parameter that a used set (top N) or bin (`size-parameter`) uses. | 16 of 16 are named in no worksheet, dashboard, action or window; 12 of them are the Superstore sample's two parameters whose only user is an unused set or bin (reported with that name). |
| A006 | 74 (30) | 216 of the 318 came from 92 workbooks that have no dashboard (nothing to be missing from); the other 28 were sheets that a zone places with `type='sheet'`, `type-v2='worksheet'` or a name only, and tooltip sheets. All now count as placed. | 74 of 74 sheets are named in no dashboard, story point or tooltip (a text check; one name only appeared inside a longer sheet name). |
| A007 | 2 | Unchanged. | 2 of 2 are custom SQL. |
| A008 | 208 (158) | Was "has an extract or an absolute path": an extract alone (68 hits, 56 workbooks) is what every extract workbook has, so it is no longer reported; an extract is reported only with an absolute path (a temp or desktop file). A datasource's findings are merged into one. | 208 of 208 are absolute local paths (a drive letter, a `/Users` or `/home` folder, or a temp folder). The rule still fires in 79% of the workbooks because these are public workbooks authored on desktops; it is about portability, not a defect. Use `--skip A008` for a workbook that only runs on your machine. |
| A009 | 8 | Unchanged. | 8 of 8 have a default name. |
| A004, A010, A011 | 0 | Tableau refuses circular calculations; the longest corpus formula has 746 characters and the deepest chain is 3. | Tested on small synthetic workbooks only. |

Precision here is a count of hits that are what the rule says, judged from the workbook's XML. The automated checks ran on every hit (A001 161 of 161, A005 16 of 16, A006 74 of 74, A008 208 of 208). What a person read: 40 of the first cut's A001 hits (every fifth), all 8 A002, all 14 A003 of the first cut, and about 10 A005 and A006 cases that the automated check flagged. A008 and most of A006 were not read one by one. Nothing was opened in Tableau. A "true" hit is not always worth acting on.

Two fixes live in shared code: `usage.missing_references` (the two A003 cases, which also adds those columns to `field_usage`) and `dashboards._SHEET_ZONE_TYPES` (`sheet` and `worksheet`, which also changes the dashboard summaries of such files).

### What "used" means

A001 and A005 use `usage.field_usage`: a field is used when a worksheet shows or filters it, directly or through the calculations, groups, sets and bins that worksheet's fields depend on. A name that a dashboard, an action or a worksheet's text mentions as `[Name]` also counts as used, and so does a parameter a worksheet window shows as a control. Not seen: another workbook or a published datasource that uses the field, a blend from another datasource, and a calculation that only a story caption mentions. "Unused" means "probably unused here", not "safe to delete".

`field_usage` itself does not yet follow a parameter through a calculation's formula (it reads the references from a set, so `[Parameters]` and the name after it lose their order; `docs/next-steps.md` lists it). A005 does not depend on that: it follows a parameter through formulas on its own. A parameter that only an unused calculation uses is still reported, and the finding names the calculation.

## Data dictionary

```bash
py-tbparse docs sales.twb                    # print the page
py-tbparse docs sales.twb -o sales.md        # write it (never over the workbook itself)
py-tbparse docs sales.twb -o sales.md --graph  # add the relationship graph as a DOT block
```

`py-tbparse dictionary` is the same command. From Python: `from py_tbparse import workbook_markdown; workbook_markdown(TwbParser("sales.twb"), graph=False)`.

The page has: an overview (file name, Tableau file version, counts); each datasource with its connections and tables; a table of its fields (name, caption, type, role, kind, formula, "used by": sheets, dashboards and calculations); the parameters (type, current value, allowed values, used by); the worksheets with the fields each uses directly, whether it is hidden and which dashboards show it (this is the "where used" index); and the dashboards with their worksheets.

- The order is fixed and there is no timestamp, so the page can live in git and a change shows as a diff.
- Pipes, newlines, `<`, `&`, backticks and brackets in names and formulas are escaped, so workbook text cannot break a table or open a heading, link or code fence. Non-Latin text is left as it is.
- A formula over 120 characters is cut in the table and given in full in a collapsible `<details>` block below the datasource's table.
- Connections go through the same allowlist as `template show --markdown` (`safe_connection`): class, server, database, schema, port, warehouse and authentication kind are shown, a file by its name only, and user names, passwords, tokens and folders never. The page and the template page build the connection text with the same function. Custom SQL text is not printed on the page (A007 lists its first 80 characters).
- Formulas, captions and parameter values are printed as the workbook has them. A password typed into a formula or a caption would be shown, and a local path inside a formula too; read the page before you share it.
- The page name is the file name, not its folder.

Not in the basic level: HTML output, a lineage view beyond the relationship graph, groups and sets as sections, and where-used for the fields of a sheet's filters and actions beyond what `field_usage` sees.
