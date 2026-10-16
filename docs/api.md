# Python API

Everything below is importable from `py_tbparse` and is listed in `py_tbparse.__all__`
(`tests/test_api_doc.py` fails when this page and `__all__` disagree). It is grouped by what
you want to do. Each line is a short summary; the page linked at the top of each group has the
details, the options and the limits. Full signatures: `help(py_tbparse.name)`.

Conventions that hold across the package:

- A function that takes a workbook accepts a path (`.twb` or `.twbx`) or a `TwbParser`, unless the line says otherwise. Functions starting `extract_`, and `list_dashboards`, `dashboard_sheets`, `zone_kind` and `integrity_check`, take the parsed XML (`wb.doc`) instead.
- A function that writes a file returns the path as a `str` and never overwrites an existing file unless you pass `overwrite=True`. A dry run (no `output_path`) returns the report only.
- Tables are `pandas.DataFrame`s. Findings from `audit`, `check_template`, `validate_workbook` and similar share the columns in `FINDING_COLUMNS` of `py_tbparse.findings`.
- Nothing here has been opened in Tableau Desktop. Open every written workbook there before you use it ([verify-in-tableau.md](verify-in-tableau.md)).

## Read a workbook

The class and its tables. More: [cli.md](cli.md) (the same tables on the command line).

- `TwbParser`: parse a `.twb` or `.twbx`; `wb.get_datasources()`, `wb.get_fields()`, `wb.get_calculated_fields()`, `wb.get_parameters()`, `wb.get_dashboards()`, `wb.get_overview()` and the other `wb.get_*` methods return one table each.
- `extract_datasource_details`: the datasource details as a dict.
- `extract_named_connections`: the named connections.
- `extract_parameters`: the parameters.
- `extract_columns_with_table_source`: columns together with the table they come from.
- `extract_raw_fields`: the raw (physical) fields.
- `extract_calculated_fields`: the calculated fields, optionally with parameters.
- `extract_custom_sql`: custom SQL relations.
- `extract_initial_sql`: initial SQL.
- `extract_published_refs`: references to published datasources.
- `extract_relations`: the relations (tables, joins) of every datasource.
- `field_usage`: for every field, which worksheets, dashboards and calculations use it.
- `workbook_markdown`: the data dictionary of a workbook as a Markdown string ([audit.md](audit.md)).

## Joins, relationships and the graph

- `extract_joins`: the joins.
- `extract_relationships`: the relationships (Tableau 2020.2 and later).
- `infer_implicit_relationships`: guess relationships from matching field names.
- `validate_relationships`: check the relationships; returns a dict, `strict=True` raises.
- `to_dot`: the join and relationship graph as Graphviz DOT text.
- `graph_data`: the same graph as plain data for a drawing front end.

## Dashboards and scaffolds

A scaffold is the layout of one dashboard, kept as JSON so another workbook can get a new dashboard laid out the same way ([scaffolds.md](scaffolds.md)).

- `list_dashboards`: the dashboard names.
- `dashboard_sheets`: the worksheets on each dashboard (or on one).
- `zone_kind`: what a dashboard `<zone>` is (`sheet`, `filter`, `text`, ...).
- `integrity_check`: reference checks on dashboards; an empty list means nothing was found.
- `make_scaffold`: the scaffold of one dashboard, as a dict.
- `save_scaffold`: write a scaffold as JSON.
- `load_scaffold`: read a scaffold back.
- `apply_scaffold`: write a copy of a workbook with a new dashboard laid out like a scaffold.
- `ScaffoldError`: a dashboard cannot be a scaffold, or a scaffold cannot be applied.

## Check a workbook

Rules, findings and CI output. More: [audit.md](audit.md), [ci.md](ci.md).

- `audit`: run the workbook audit rules (A001 to A011); returns findings.
- `validate_workbook`: dangling references in a workbook; one row per finding.
- `run_rules`: run the rules of one scope on a subject; the engine behind `audit` and `check_template`.
- `format_findings`: render findings as `table`, `csv`, `json`, `junit`, `sarif` or `github`.

## Compare workbooks

More: [diff-xml.md](diff-xml.md).

- `diff_tables`: row diff of two tables of the same shape.
- `diff_workbooks`: diff one named table between two parsed workbooks.
- `scan_folder`: run one table over every workbook in a folder.
- `normalised_diff`: unified diff of two workbooks' XML after canonicalisation; empty when nothing really differs.
- `twbx_list`: the members of a `.twbx` archive.
- `twbx_extract_files`: pull chosen files out of a `.twbx`.
- `extract_twb_from_twbx`: pull the `.twb` out of a `.twbx`.

## Rename fields

Suggest clean names, edit them, write a renamed copy. More: [renaming.md](renaming.md).

- `normalize_name`: tidy one name (`style="title"` and others).
- `suggest_field_renames`: a clean name for every field, optionally against a reference schema.
- `suggest_renames`: the same for sheets, dashboards and other objects too.
- `compare_field_schemas`: which fields have no counterpart across a datasource switch.
- `load_rename_mapping`: read an edited rename table (CSV path or frame) back in.
- `apply_field_renames`: write a new workbook with the renames applied.

## Templates and new data

Make a reusable `.twbx` template from a finished workbook and fill it with new data. More: [templates.md](templates.md).

- `Template`: a loaded template (`.manifest`, `.parser`, `.path`).
- `TemplateError`: the template cannot be made or applied as asked.
- `make_template`: save a template made from a workbook; returns its path (a `str`).
- `load_template`: open a template; returns a `Template`.
- `read_data`: describe new data (CSV, Excel sheet, database target file or another workbook).
- `read_many`: read a folder, glob or list of files as one source.
- `suggest_mapping`: pair the template's fields with the new data's columns.
- `load_mapping`: read an edited mapping back in.
- `load_answers`: answers for `apply_template` from a dict, an answers file or a workbook made from a template.
- `resolve_apply`: what `apply_template` would do, without writing.
- `broken_sheets`: required fields with no column, and the sheets that need them.
- `check_data`: what about the new data may mislead, without blocking anything.
- `explain`: what an apply changes besides the connection.
- `apply_template`: make the new workbook; returns its path.
- `apply_template_folder`: one workbook per data file in a folder; returns a summary table.
- `check_template`: lint a template; returns findings.
- `check_drift`: compare a set of data files (say, monthly ones) with a template or saved answers.
- `diff_template_revisions`: what changed between two revisions of a template.
- `template_update_report`: what a newer template revision would change for a workbook made from an older one.
- `update_from_answers`: apply the newer revision to such a workbook.
- `template_markdown`: a documentation page for a template, as Markdown.

## Clean up and share

More: [prune.md](prune.md), [slice.md](slice.md), [sanitize.md](sanitize.md). All three are dry runs unless you give an output path.

- `prune`: remove unused calculations, parameters (and optionally sheets and datasources).
- `prune_doc`: the same on an lxml document, in place.
- `PruneError`: pruning cannot be done as asked.
- `slice_workbook`: keep the named dashboards and what they need, remove the rest.
- `slice_doc`: the same on an lxml document, in place.
- `SliceError`: slicing cannot be done as asked.
- `sanitize`: write a share-safe copy (connection details, SQL, extracts, comments and more removed).
- `SanitizeError`: the workbook cannot be sanitized as asked.
- `PyTbparseError`: the common base of the library's own exception classes (`SliceError`, `ScaffoldError`, `SanitizeError`, `SheetCopyError`, `StyleError`, `TemplateError`, `LibraryError`, `PruneError`, `PackageTooLargeError`). It is a `ValueError`, so `except ValueError` keeps working. Plain `ValueError` and `FileExistsError` raised elsewhere (for example a bad `table` name or a refused overwrite) are not instances of it, so catch those separately. Messages are unchanged.

## Calculation libraries

Move calculated fields and parameters between workbooks. More: [libraries.md](libraries.md).

- `export_library`: collect the calculations and parameters of one datasource into a library dict.
- `save_library`: write a library as `*.library.json`.
- `load_library`: read a library back.
- `library_table`: one row per entry and per item it needs.
- `plan_import`: what `import_library` would do, one row per item.
- `build_imported_workbook`: the bytes of a workbook copy with the library added.
- `import_library`: write a copy of the workbook with the library added; returns the path.
- `LibraryError`: the library cannot be made, read or applied as asked.

## Colour palettes

Read, check and copy custom colour palettes (`Preferences.tps`, workbooks, style files). More: [styles.md](styles.md).

- `read_palettes`: the usable palettes of a workbook, `.tps` or style file.
- `palettes_table`: one row per palette found.
- `palette_records`: every palette, valid or not, with a status.
- `palette_problems`: the check lines for palette records.
- `palettes_from_bytes`: palette records from uploaded file bytes.
- `make_style`: a style dict holding palettes.
- `save_style`: write a style dict as JSON.
- `load_style`: read and check a style file.
- `check_style_file`: problems in a `.tps` or style file; empty means none found.
- `tps_bytes`: a fresh `Preferences.tps` as bytes.
- `plan_palette_import`: what importing palettes into a target would do.
- `build_with_palettes`: the bytes of a copy of the target with the palettes added.
- `import_palettes`: write that copy; returns the path.
- `export_palettes`: merge the palettes of several sources into one file.
- `build_export`: the same, as bytes.
- `StyleError`: a palette, style file or import cannot be read or done as asked.

## Examples

Each block runs from the repository root against `docs/demo/coffee-shop.twb` (a made-up workbook) or a file in `tests/fixtures/`. `tests/test_api_doc.py` runs them.

Read the tables and check the workbook:

```python
from py_tbparse import TwbParser, audit, field_usage, validate_workbook

wb = TwbParser("docs/demo/coffee-shop.twb")
print(wb.get_datasources())
print(wb.get_calculated_fields()[["name", "formula"]])
print(wb.get_dashboards())
print(field_usage(wb).head())
print(audit(wb)[["rule", "severity"]])        # findings: rule id, severity, ...
print(validate_workbook(wb))                  # dangling references
```

Make a template and lint it (`make_template` returns the output path as a string, not a `Template`):

```python
import os, tempfile
from py_tbparse import make_template, load_template, check_template

out = tempfile.mkdtemp()
path = make_template("docs/demo/coffee-shop.twb", os.path.join(out, "coffee.template.twbx"))
template = load_template(path)
print(template.manifest["name"], check_template(template)["rule"].tolist())
```

Fill a template with a CSV (the coffee template needs no input columns, so the mapping is empty here; `docs/templates.md` has a case with real fields):

```python
import os, tempfile
from py_tbparse import apply_template, load_template, make_template, read_data, suggest_mapping

out = tempfile.mkdtemp()
template = load_template(make_template("docs/demo/coffee-shop.twb", os.path.join(out, "t.twbx")))
csv = os.path.join(out, "orders.csv")
with open(csv, "w") as fh:
    fh.write("order_id,sales_usd\n1,12.5\n")
data = read_data(csv)
mapping = suggest_mapping(template, data)
print(apply_template(template, data, mapping, output_path=os.path.join(out, "new.twbx")))
```

Dry-run a prune, write a share-safe copy and round-trip a library:

```python
import os, tempfile
from py_tbparse import TwbParser, export_library, library_table, load_library, prune, sanitize, save_library

out = tempfile.mkdtemp()
print(prune("docs/demo/coffee-shop.twb")["counts"])          # nothing is written
print(sanitize("docs/demo/coffee-shop.twb", os.path.join(out, "safe.twb")))

lib = export_library(TwbParser("tests/fixtures/test_for_wenjie.twb"))
path = save_library(lib, os.path.join(out, "wenjie.library.json"))
print(library_table(load_library(path)))
```
