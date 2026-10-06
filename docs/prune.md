# Prune: remove what the audit finds unused

Part of [py-tbparse](https://github.com/DDSNA/py-tbparse). `prune` removes from a workbook what the [audit](audit.md) reports as unused, and only when nothing that stays refers to it. Nothing here was opened in Tableau Desktop: the command edits the XML of the `.twb`/`.twbx` and the result is checked against the XML schema and by re-reading it, not by Tableau.

```bash
py-tbparse prune sales.twb                              # dry run: what would go, and why
py-tbparse prune sales.twb --write -o sales_pruned.twb  # write a NEW file
py-tbparse prune sales.twb --sheets --write -o out.twb  # also worksheets on no dashboard
py-tbparse prune sales.twb --no-parameters              # calculations only (--no-calculations likewise)
py-tbparse prune sales.twb --sheets --datasources --write -o out.twb   # also datasources nothing names
py-tbparse prune sales.twb --format json                # the report as JSON
```

From Python: `from py_tbparse import prune; report = prune("sales.twb")` (a dry run), `prune("sales.twb", "out.twb", sheets=True)` writes.

To prune a document you already hold in memory (for example as a step of another edit), use `prune_doc(doc, sheets=False, calculations=True, parameters=True, datasources=False)`. `doc` is an lxml tree or the `<workbook>` element, such as `TwbParser.xml_doc`; it is changed in place (pass `copy.deepcopy(parser.xml_doc)` to keep the original), and nothing is read from or written to disk. It returns the same report as `prune` without the file keys (`removed`, `kept`, `counts`, `traces`). `prune` is `prune_doc` on a copy plus the file handling, so the two give the same result.

## What it removes

| What | Found by | Default |
| --- | --- | --- |
| Calculated fields (bins included) nothing uses | A001 | on |
| Parameters nothing uses | A005 | on |
| Worksheets on no dashboard, story or tooltip | A006 | off, needs `--sheets` |
| Datasources nothing names | the check below (not an audit rule) | off, needs `--datasources` |

The candidates come from the audit's own code, so the two cannot disagree; the rules are in [audit.md](audit.md#what-used-means). Hidden calculations, Tableau's own `Number of Records` and a workbook with no worksheet are left alone, as in the audit. With `--sheets` the sheets go first, so a calculation that only a removed sheet used is removed too. The last worksheets of a workbook are never all removed.

## When something is kept

A finding is removed only if nothing that stays names it. After the candidates' own traces are set aside, every attribute value and text in the rest of the workbook is read for `[Name]` (also inside `[datasource].[Name]` and `[none:Name:nk]`). Whatever still names a candidate keeps it: another calculation, a set or group (including a top-N that uses a parameter), a bin, an action, a filter, a dashboard, a colour palette, a window entry such as a highlight or a quick filter, or an extract that stores the field. A kept candidate goes back into the pool and what it refers to is checked again, until nothing changes. So a chain of unused calculations goes together, and a chain that ends in a set stays.

The dry run prints every kept finding with what names it (`still named by <groupfilter> in group Set 1`). Over the 200-workbook corpus the usual reasons were colour palettes and highlights, a set's top-N parameter, and a calculation stored in an extract.

The check is by name over the whole workbook, not by datasource: a same-named field in another datasource also keeps a candidate. That errs toward keeping, never toward removing.

## Unused datasources (`--datasources`)

Off by default, so the behaviour of `prune` without the flag is unchanged. It runs last, after sheets, calculations and parameters, so a datasource that only a removed sheet used goes too. A datasource is removed when nothing outside it names its internal name: every attribute value and text of the rest of the workbook is read, so a worksheet's or dashboard's `<datasources>` list, a `<datasource-dependencies>` list, an action, a filter or another datasource that mentions it keeps it. The datasource's own element goes whole (its connection, columns, metadata and style). Rules:

- The `Parameters` datasource is removed only when it holds no column at all and nothing names it (`[Parameters]` in a formula, `datasource='Parameters'` in a sheet). One that still has a parameter stays, even an unused one, because the parameter was kept for a reason the report states. When unsure it stays.
- The last real datasource of a workbook is never removed; the report says it was kept.
- A datasource that something names is reported under `kept` with what names it, as for calculations.
- The check is by name over the whole workbook and may keep a datasource that is in fact unused, never the reverse. A `.twbx` keeps its extract and data files, so a removed datasource's extract stays in the package. Over the 200-workbook corpus with `sheets=True, datasources=True`, 15 datasources went, one of them an empty `Parameters`.

## What goes with a field

Its `<column>` (captions, aliases and the calculation are inside it), the `<column-instance>` of it, a `metadata-record` of it outside an extract, its entry in a folder, its field in a hierarchy, its colour or format entry in the datasource's `<style>`, and its entry in a `<datasource-dependencies>` list. A dependency list or style rule that is left empty goes too. A hierarchy that loses a field stays, even with one field; a folder that is left empty stays; the `Parameters` datasource stays even with no parameter left (unless you ask for `--datasources`, see below). For a sheet: the worksheet, its window and its thumbnail record. The report counts these per kind (`traces`).

## Safety

- Dry run unless `--write -o OUT`. The output is a new file in the input's format (`.twb` to `.twb`, `.twbx` to `.twbx`, whose other members are copied as they are); the input is never written and an existing `OUT` is refused unless `--overwrite`.
- A second prune of the output removes nothing.
- Exit code 0, or 2 for an unreadable workbook, a refused output or a wrong option.

## What was checked, and what was not

Tested over the 200-workbook corpus with every option on (`tests/test_prune_corpus.py`; the datasource option has its own run, `tests/test_prune_doc_corpus.py`, same checks plus no removed datasource name left in the output): no exception, the output re-parses, the XML-schema errors do not increase against the input, nothing removed is still an A001, A005 or A006 finding, no removed field name is left anywhere in the output, the A003 (missing reference) count does not rise, and a second prune is a no-op. Counts from that run: 146 calculations, 11 parameters and 69 sheets removed, 3 workbooks where the last worksheets were kept.

Not checked, and the weak spots:

- Nothing was opened in Tableau Desktop. The schema is Tableau's newest, most real workbooks already fail it, so the check only proves no new errors; passing it does not prove a workbook opens.
- "Unused" is "unused in this workbook". Another workbook, a published datasource or an external tool may use a calculation or parameter. A parameter a story caption uses is not seen either.
- Re-saving writes the XML through lxml, as `rename` does; the corpus run of `scripts/measure_roundtrip_diff.py` shows a no-edit save changes nothing in the normalised XML.
- A hierarchy left with one field and a folder left empty may be odd in Tableau; no test showed either to be refused.
- Packaged extracts, data and thumbnails of a `.twbx` are not touched, so a removed sheet's preview image stays in the package.
- No health score and no "hide instead of delete" mode (the roadmap suggested one; the owner asked for the basic level).
