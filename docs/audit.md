# Workbook audit and data dictionary

Part of [py-tbparse](https://github.com/DDSNA/py-tbparse).

Two read-only commands for a workbook: `audit` lists what its author probably did not mean, and `docs` writes a Markdown data dictionary. Neither writes to the workbook, and nothing here was opened in Tableau: the commands read the XML of the `.twb`/`.twbx` and say what they find there. This is the basic level; there is no `prune`, no health score and no JUnit or SARIF output yet.

## Audit

```bash
py-tbparse audit sales.twb                          # a table of findings; exit 1 if there is an error
py-tbparse audit sales.twb --fail-on warning        # exit 1 on a warning or worse (error, warning, info, never)
py-tbparse audit sales.twb --only A001,A005 --format csv -o findings.csv
py-tbparse audit sales.twb --skip A006,A009 --format json
```

Findings go to stdout (or `-o`), the count to stderr. Formats are `table`, `csv` and `json`. Exit codes are the ones of `template check`: 0, 1 (a finding at `--fail-on`), 2 (the workbook cannot be read or an option is wrong) and 3 (a rule crashed; it is reported as an error finding and its traceback goes to stderr).

From Python: `from py_tbparse import audit; audit("sales.twb", only=["A001"])` returns a pandas DataFrame with the columns `rule, severity, object, detail, fix`, sorted so the same workbook always gives the same frame.

### Rules

Rule ids are stable: put them in CI configs. An id is never renumbered or reused. Every rule is a heuristic, none says Tableau refuses the file.

| Id | Severity | What it finds |
| --- | --- | --- |
| A001 | info | A calculated field that no worksheet uses, not even through another calculation. Hidden calculations are left alone. |
| A002 | warning | Two calculations of one datasource with the same formula (comments, spacing and keyword case aside). Formulas with no field in them (`1`) are ignored. |
| A003 | error | A calculation refers to a field the workbook does not have (`usage.missing_references`). A field that only a blended datasource provides reads as missing. |
| A004 | error | Calculations that refer to each other in a circle, or to themselves. |
| A005 | info | A parameter that no worksheet, calculation, action or title uses. |
| A006 | info | A worksheet that is on no dashboard or story and not hidden. |
| A007 | info | Custom SQL is present: datasource, query name and the first 80 characters. A `password=` or `token=` value and `user:pass@` are replaced by `***`. |
| A008 | info | A datasource keeps an extract, or a file connection has an absolute local path (only the file name is printed, never the folder). |
| A009 | info | A calculation still has Tableau's default name (`Calculation1`, or no caption on `Calculation_123...`). |
| A010 | info | A calculation sits on a chain of more than 5 calculations. |
| A011 | info | A formula is longer than 1000 characters (the formula is never printed). |

The rules came from what the 200-workbook test corpus contains. A004, A010 and A011 have no hits there (Tableau refuses circular calculations, and the longest corpus formula has 746 characters, the deepest chain is 3); they are tested on small synthetic workbooks only, with the limits from the plan.

### What "used" means

A001 and A005 use `usage.field_usage`: a field is used when a worksheet shows or filters it, directly or through the calculations, groups, sets and bins that worksheet's fields depend on. A name that a dashboard, an action or a worksheet's text mentions as `[Name]` also counts as used. Not seen: another workbook or a published datasource that uses the field, a blend from another datasource, and a calculation that only a story caption mentions. "Unused" means "probably unused here", not "safe to delete".

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
