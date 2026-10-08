# WP6 design: calculated-field and parameter libraries

Written 2026-10-05 for the agent that implements WP6 (roadmap: `docs/template-roadmap-plan.md`, section WP6). Every
number below comes from the 200-workbook corpus (`tests/corpus/files`, fetch with `python scripts/fetch_corpus.py`).
Nothing here has been checked in real Tableau; the items marked **UNVERIFIED** are guesses from the corpus.

## 1. Decision: the first slice

Build **calc + parameter** export, import and show. Defer sets, groups, bins, `overwrite`, folders on import and the GUI.

| Kind | In corpus | First slice? | Why |
|---|---|---|---|
| calc (`<column><calculation class='tableau'>`) | 378 in 122 workbooks | yes | Common and has a simple shape (section 2). |
| parameter (column in the `Parameters` datasource) | 55 in 34 workbooks | yes | 25 calcs use one, so a calc without its parameters is useless. |
| set (`<group>` with `user:ui-builder='filter-group'`) | about 13 in 200 | no: required by name | Rare. Nested `groupfilter` trees with `[none:X:nk]` instance refs and `count='[Parameters].[..]'`. |
| group: old `<group>` / new `categorical-bin` column | 66 hidden action groups (`user:auto-column='sheet_link'`, never export) / 10 in 9 workbooks | no: required by name | Rare. Holds data values (`<bin><value>"..."`), which mean nothing against other data. |
| bin (`<calculation class='bin'>`) | 26 in 18 workbooks; 8 use `size-parameter` | no: required by name | Easy to add later (section 9). No calc in the corpus refers to a bin. |

In the first slice, a calc that refers to a set, group or bin keeps the reference. The library lists that object as
*required*, and the target must already have it under the same name (2 calcs in the corpus do this).

## 2. Evidence: how Tableau writes these objects

**Calc** (378 calcs, all directly under `/workbook/datasources/datasource[@name!='Parameters']`). A `<column>` has
exactly one `<calculation class='tableau' formula='...'/>` child. The only other child seen is `<desc>` (once).
- Column attributes: `caption datatype name role type` in 282 calcs. The extras are `default-format` (22),
  `aggregation`, `semantic-role`, `visual-totals`, `default-role`/`default-type`. Some calcs have no `caption` (48),
  so their name is what people see.
- The calculation's attributes are `class formula`, plus `scope-isolation='false'` on 28 calcs.
- **Table calcs** (25) carry a child `<table-calc ordering-type='Rows'/>`. Sometimes it is
  `ordering-type='Field' ordering-field='[federated.051l...].[tdy:Datetime:qk]'`, which names the datasource and a
  field instance and so has to be rewritten on import.
- **LOD** calcs (10) are ordinary formulas, `{ FIXED [Sub-Category]:SUM([Sales])}`. The dimensions are plain `[refs]`.
- Formulas are multi-line in 84 calcs. The newlines are stored as `&#13;&#10;`, and lxml reads them as `\r\n`.
- Names: `[Calculation_<digits>]` (241), any other bracketed name (137, for example `[Calculation1]`, `[Calcul 1]`,
  `[Profit Ratio]`). Any bracketed name works, so a name we generate only has to be unique in its datasource.
- Calcs Tableau makes on its own (do not export them unless something refers to them): 40 with
  `user:auto-column='numrec'` (`[Number of Records]`, formula `1`), 22 split fields (`user:SplitFieldIndex/Origin`)
  and date bins (`user:ui-builder='date-bin-builder'`).
- Worksheets keep copies of the calcs they use in `<datasource-dependencies>` (469 such copies). A new calc that no
  sheet uses needs no copy. This is why `overwrite` is deferred: it would have to update these copies too.

**Parameter.** The parameters sit in `/workbook/datasources/datasource[@name='Parameters']`, which is the first child
of `<datasources>`. 27 of 34 workbooks write it as `<datasource hasconnection='false' inline='true' name='Parameters'
version='18.1'>`, with `<aliases enabled='yes'/>` first and then the columns. A parameter column has the attributes
`caption datatype name param-domain-type role type value`, sometimes with `alias`, `datatype-customized` or
`default-format`.
- Its children are a `<calculation class='tableau' formula='<current value>'/>` and one of `<range min max
  granularity/>` (32), `<members><member value alias?/>` (20) or nothing (`any`, 3). `<aliases><alias key value/>`
  is optional.
- `value` equals `formula` in 53 of 55.
- **50 of 55 parameters are named `[Parameter N]`, and 30 of 34 workbooks have a `[Parameter 1]`**, so an internal
  name clash on import is the normal case, not the exception.

**References inside formulas.** There were 576 plain `[Field]` references, 66 `[Calculation_N]` references (calc to
calc; 37 calcs use another calc) and 29 `[Parameters].[Parameter N]` references.
- 3 calcs reach into another datasource with `[csv.41599.28...].[SalesAmountQuote]`. The first slice does not export
  them; they are reported as `unsupported`.
- 12 calcs refer to a name that their datasource does not have (formulas that were already broken).
- **5 calcs have `[...]` inside a string literal**, so references must be found with `usage._code_refs` (which skips
  strings) and not with the `_refs` regex.

**Clashes seen in the corpus.** 11 of 271 captions are defined in more than one way across workbooks (`Profit Ratio`
6 ways, `Calculation1` 7 ways, `Total Revenue` 3). In 10 workbooks the same calc caption appears in 2 or more
datasources. No datasource defines the same name twice. Folders are rare: `folder-item` appears in 5 workbooks.

## 3. Library JSON format v1 (`*.library.json`, UTF-8, `indent=2`, `ensure_ascii=False`, keys sorted)

```json
{"format": "py-tbparse-library", "version": 1, "name": "Sales KPIs", "description": "",
 "created": "<_now()>", "py_tbparse_version": "<_version()>",
 "source": {"workbook": "Superstore.twb", "datasource": "federated.0abc", "datasource_caption": "Orders"},
 "required": [
   {"name": "[Sales]", "caption": null, "remote": "Sales", "datatype": "real", "role": "measure",
    "kind": "field", "required": true, "used_by": ["<uid>", "..."]}],
 "entries": [
   {"uid": "<field_uid(src ds, name, role, datatype)>", "kind": "calc", "name": "[Calculation_1368249927221915648]",
    "caption": "Profit Ratio", "datatype": "real", "role": "measure", "type": "quantitative",
    "formula": "SUM([Profit])/SUM([Sales])", "formula_display": "SUM([Profit])/SUM([Sales])",
    "refs": ["[Profit]", "[Sales]"], "depends_on": [], "attrs": {"default-format": "p0.0%"},
    "calc_attrs": {}, "table_calc": null, "comment": null, "folder": null},
   {"uid": "...", "kind": "parameter", "name": "[Parameter 1]", "caption": "Top N", "datatype": "integer",
    "role": "measure", "type": "quantitative", "formula": "10", "value": "10", "domain": "range",
    "range": {"min": "5", "max": "20", "granularity": "5"}, "members": null, "aliases": null,
    "attrs": {}, "refs": [], "depends_on": [], "comment": null, "folder": null}]}
```

- The source of truth is `formula`, which uses internal names. `formula_display` swaps calc and parameter names for
  their captions; it is for people only, is never read on import, and `show` prints it.
- `refs` keeps the references in formula order: two-part refs stay whole (`[Parameters].[Parameter 1]`), and the
  table calc `ordering-field` is included. `depends_on` is the uids of the library entries they resolve to.
- `attrs` holds every other column attribute verbatim, except the `user:*` ones: those name the source datasource,
  and dropping them turns split and date-bin calcs into ordinary calcs (**UNVERIFIED** that Tableau is fine with
  this). `calc_attrs` holds the extra `<calculation>` attributes (for example `scope-isolation`). `table_calc` holds
  the `<table-calc>` attributes. `comment` is the `<desc>` element as a raw XML string.
- `required[].kind` is one of `field`, `calc`, `group`, `set`, `bin` or `unknown`. A `field` comes from the source's
  physical columns (`templates._physical_fields`), so `remote` is there for the matcher. The other kinds are objects
  the library leaves out (a calc that was not selected and `with_dependencies=False`, a set or group or bin, a
  dangling name), and they are matched **by exact name only**.
- `load_library` rejects any `format` other than `py-tbparse-library` and any `version` above 1, with `LibraryError`.

## 4. API (new module `py_tbparse/library.py`, exported from `__init__.py`)

```python
class LibraryError(ValueError): ...
CLASH_POLICIES = ("rename", "skip", "fail")
PLAN_COLUMNS = ["uid", "kind", "name", "caption", "action", "target_name", "target_caption", "reason"]

def export_library(parser: TwbParser, datasource: str | None = None, select: Iterable[str] | None = None,
                   folder: str | None = None, with_dependencies: bool = True, include_parameters: bool = True,
                   name: str | None = None, description: str | None = None, report: dict | None = None) -> dict
def save_library(library: dict, path: str | os.PathLike, overwrite: bool = False) -> str
def load_library(path: str | os.PathLike) -> dict
def library_table(library: dict) -> pd.DataFrame      # kind, name, caption, datatype, depends_on, required_by
def plan_import(parser: TwbParser, library: dict, datasource: str | None = None,
                mapping: dict | str | pd.DataFrame | None = None, on_clash: str = "rename") -> pd.DataFrame   # 0.5.x: omitted warns; default becomes "fail" in 0.6.0
def build_imported_workbook(parser, library, datasource=None, mapping=None, on_clash="rename",
                            report: dict | None = None) -> bytes
def import_library(parser, library: dict | str, datasource=None, mapping=None, on_clash="rename",
                   output_path: str | None = None, overwrite: bool = False, report: dict | None = None) -> str
```

- `datasource` takes the internal name or the caption, on both sides. If it is None, use the only non-Parameters
  datasource that has a connection. If there are several, raise `LibraryError` and list them.
- `select` matches an internal name or a caption. `folder` takes the `folder-item`s of that folder. If both are None,
  export every user calc in the datasource (not the auto-made ones listed in section 2) and, when
  `include_parameters` is on, every parameter.
- `report` gets counts (`exported`, `required`, `unsupported`) on export, and on import `added`, `skipped_identical`,
  `renamed`, `skipped`, `failed`, `skipped_dependents`, each a count with a list of names. The plan rows explain each
  entry.
- `mapping` can be a dict `{required name or caption: target local name or column name}`, or anything
  `templates.load_mapping` accepts (`field` to `mapped_to`, where `mapped_to` is a column name and is turned into a
  local name through the `DataSource` field's `local`).
- `import_library` writes to `<stem>_library<ext>` beside the source by default. The output must keep the source's
  extension, it never overwrites the input, and it opens with `"wb" if overwrite else "xb"`. A `.twbx` copies every
  other member across, exactly as `rename.build_renamed_workbook` does (reuse that code; do not copy it).

## 5. Import algorithm (in `plan_import`; `build_imported_workbook` carries out the plan)

1. **Resolve required items** against the target datasource `T`:
   1. Use the explicit `mapping` first.
   2. If not mapped, look for the exact local name among all of `T`'s fields (`usage._datasource_fields(T)`, any kind).
   3. For `kind == "field"` items still open, use the template matcher. Refactor the body of
      `templates.suggest_mapping` into `_match_fields(fields, data, ds_name, fuzzy_cutoff) -> DataFrame` and build
      `data` with a new `_tableau_datasource(ds_el, path, require_fields=False)`, split out of `read_data`.
      `suggest_mapping` then calls `_match_fields`, with no change in behaviour.
   4. Statuses `matched`, `close match` and `* differs` count as mapped, and the plan shows the status. Anything else
      is unmapped.
2. **Order** the entries topologically by `depends_on` (Kahn's algorithm, ties broken by `(kind, name)`; parameters
   come before calcs when both are ready). A cycle raises `LibraryError`.
3. **For each entry in that order**, take the first action that applies:
   1. `fail-dependency`: an entry it depends on failed, so it is not imported (reported in `skipped_dependents`).
   2. `skip-identical`: `T` (or `Parameters` for a parameter) already has a column with the same internal name and
      an identical definition. Identical means:
      - calc: the same caption (None = None), datatype and formula, after `\r\n` becomes `\n`;
      - parameter: the same caption, datatype, domain, value, members and range.

      This check runs **before** mapping, so a self-import is always all `skip-identical`, even for broken formulas.
   3. `fail-unmapped`: a required item the entry uses is unmapped.
   4. The formula is rewritten (section 6), and the check in 3.2 is repeated against *any* column of `T` with the same
      caption. If that column is identical, the action is `skip-identical`, and the entry's name now points to the
      existing column for later entries.
   5. **Caption clash** (another column or field of `T` has this caption, or this name with no caption, and a
      different definition):
      - `rename`: the caption becomes `"<caption> (2)"`, or the next free `(n)`, as Tableau's paste does
        (**UNVERIFIED** that Tableau uses exactly this suffix);
      - `skip`: keep the target's column and point to it, with a warning when the datatype differs;
      - `fail`: raise `LibraryError` before writing anything (the whole plan is built first).
   6. **Internal name taken** (with a different caption or definition) or free:
      - calc: keep the name if it is free, else use `[Calculation_<18 digits>]` from
        `sha1(target ds + caption + formula)`, bumping by 1 while the name is taken, so the output is the same on
        every run;
      - parameter: use the next free `[Parameter N]`.

      These renames are reported as `renamed_internal`; nobody sees them in Tableau.
   7. `add`.
4. **Write** to a deep copy of the target:
   - Calcs go after the last `<column>` of `T`. Split the anchor code out of `rename._new_column` into
     `_insert_column(ds_el, col)` and use it from both places.
   - Parameters go after the last `<column>` of the Parameters datasource. If the workbook has no Parameters
     datasource, create the 18.1 shape from section 2 as the first child of `<datasources>`.
   - Attributes are written in Tableau's order: `caption datatype name param-domain-type role type value`, then the
     keys of `attrs` sorted.
   - Folders are not created (`folder` is only reported).

Parameters have no `[Parameters]` copy anywhere else in the workbook (that is the only thing `rename._drop_parameters`
handles: it drops parameter rows from a rename table), so a parameter is written in this one place and nowhere else.

## 6. Formula rewriting

- Add `usage._code_ref_spans(formula) -> list[tuple[int, int, str]]` and make `_code_refs` a thin wrapper around it,
  with no change in behaviour (the existing tests guard this). Do not write a second parser.
- `library.rewrite_formula(formula, names: dict[str, str], params: dict[str, str]) -> str` replaces spans from right
  to left:
  - a `[Parameters]` span followed straight away by `.` and a span is a parameter ref, mapped through `params`;
  - any other `[A].[B]` pair where `A` is a datasource name is cross-datasource (the entry is `unsupported` at export);
  - a single span is mapped through `names` (required items plus renamed calcs).
  - A name with `]` inside is written with `]]`.
- `table_calc.ordering-field` (`[ds].[deriv:Field:suffix]`): change `ds` to `T`'s name and `Field` through `names`,
  keeping the derivation and the suffix (use `usage._INSTANCE`).
- At export, `formula_display` is made with the same function, using captions.

## 7. CLI (`py-tbparse library ...`: reserve it in `cli.main` like `template`, with `build_library_arg_parser`)

```
py-tbparse library export WB [--datasource DS] [--folder F] [--field NAME ...] [--no-dependencies]
                             [--no-parameters] [--name N] -o LIB.library.json [--overwrite]
py-tbparse library show LIB [--markdown]                    # entries, required fields, formula_display
py-tbparse library import WB LIB [--datasource DS] [--mapping CSV] [--on-clash rename|skip|fail]
                             [-o OUT] [--overwrite] [--write]
```

`import` without `--write` prints the plan table and writes nothing. With `--write` it writes the output and prints
`wrote <path>` and the report counts to stderr. It exits 1 on `LibraryError`, and 2 when any entry failed (stating
this in the message).

## 8. Tests (`tests/test_library.py` unless noted)

Fixtures: create `tests/fixtures/library/source.twb` and `target.twb` by hand from the corpus shapes in section 2. No
fixture in the repo has an LOD calc, a table calc or a parameter.
- `source.twb`: one datasource with the physical columns Sales, Profit, Category and Order Date. Calcs: Profit Ratio
  (with `default-format`), an LOD, a table calc with `<table-calc ordering-type='Rows'/>`, a nested calc (refers to
  another `[Calculation_N]`), a calc that uses a parameter, a calc that refers to a set, a multi-line formula, a
  string literal containing `[Sales]`, and a `numrec` auto column. Parameters: a range `[Parameter 1]` and a list
  `[Parameter 2]` with aliases. One `filter-group` set.
- `target.twb`: physical columns Revenue (for Sales), Profit, Category, the same set name, its own unrelated
  `[Parameter 1]`, a calc captioned "Profit Ratio" with a different formula, and no other overlap.
- A second target with no Parameters datasource.

The tests:
1. `test_export_shape`: format and version, the entry fields, `required` has Sales/Profit/Category (kind `field`) and
   the set (kind `set`), the numrec column and `user:*` attrs are left out, and `formula_display` uses captions.
2. `test_export_dependencies_closed`: selecting only the nested calc brings in its dependency and the parameter; with
   `with_dependencies=False` they become required (kind `calc`).
3. `test_export_by_folder`, and `test_export_unsupported_cross_datasource` (reported, not exported).
4. `test_save_load_roundtrip`: the same dict comes back, the save refuses to overwrite, and a bad format or a
   version above 1 raises.
5. `test_dependency_order`: the parameter comes before the calc that uses it, and the dependency before the nested
   calc. A hand-made cycle raises.
6. `test_self_import_all_identical`: importing into the source gives only `skip-identical` and changes nothing
   (`build_imported_workbook` gives an equal tree).
7. `test_import_maps_fields`: Sales is mapped to Revenue by the matcher. The formulas are rewritten and the string
   literal is untouched.
8. `test_parameter_internal_clash`: the imported `[Parameter 1]` becomes `[Parameter 2]` (or the next free number)
   and every `[Parameters].[..]` ref in the imported calcs follows it.
9. `test_clash_rename`, `test_clash_skip` and `test_clash_fail` (`fail` writes nothing).
10. `test_identical_under_other_name`: same caption and same definition with a different internal name gives
    `skip-identical`, and the dependents point to the existing name.
11. `test_unmapped_chain_skipped`: with Profit missing, every calc that depends on it is reported in
    `skipped_dependents`, and the others are still added.
12. `test_parameter_roundtrip`: range, list with aliases and `any`. Into the target with no Parameters datasource,
    one is created in the 18.1 shape.
13. `test_table_calc_and_lod_preserved`: `table-calc`, `scope-isolation` and `\r\n` come through byte-equal.
14. `test_output_reparses`: `TwbParser(out)` works, `field_usage` lists the imported calcs with their deps,
    `missing_references` adds nothing new, `validate_workbook` adds no errors, and
    `tests/schema_check.new_schema_errors(before, after) == []`.
15. `test_import_never_overwrites` (input, existing output, wrong extension) and `test_twbx_members_copied`.
16. `test_non_latin_names` (for example `[参数 1]`, which is in the corpus) and the dedup suffix `(2)` on a caption
    that already has `(2)`.
17. `test_match_fields_refactor`: `suggest_mapping` gives the same results as before; `test_matcher.py` and
    `test_templates.py` must pass unchanged.
18. `tests/test_cli.py`: export, show, import without `--write` (writes nothing) and with `--write`, and the exit codes.
19. `tests/test_corpus.py::test_library_self_import`: for every corpus workbook and every datasource with calcs,
    export with parameters, import into the same workbook, and expect every entry to be `skip-identical` and
    `failed == 0`. The cross-datasource calcs are a named known-issues list in the test, not a silent skip. Also check
    that export never raises on any workbook.

## 9. Files

- Create: `py_tbparse/library.py`, `tests/test_library.py`, `tests/fixtures/library/{source,target,target_noparams}.twb`.
- Change:
  - `py_tbparse/usage.py` (`_code_ref_spans`);
  - `py_tbparse/templates.py` (`_match_fields`, `_tableau_datasource`; no behaviour change);
  - `py_tbparse/rename.py` (`_insert_column`, plus a shared twbx-writing helper if one does not already exist);
  - `py_tbparse/cli.py`, `py_tbparse/__init__.py`, `tests/test_corpus.py`, `tests/test_cli.py`;
  - the README: a "Libraries" section, plus "What works" (say "follows what Tableau writes", never "opens in Tableau").
- Do not touch `pyproject.toml` or the version in this branch until a merge is planned.

**Deferred (the next slice, in this order):**
1. Bins: copy `class decimals formula peg size|size-parameter` and rewrite `formula` and `size-parameter`.
2. `overwrite`: update the worksheet copies in `datasource-dependencies` too.
3. Sets: rewrite the `groupfilter` `level/member/expression/count` refs through `usage._base_field`.
4. `categorical-bin` groups.
5. Folder placement on import.
6. Cross-datasource calcs.
7. GUI.

## 10. Unverified assumptions (none of this has been opened in Tableau)

1. Tableau accepts a calc or parameter column added at the end of the existing columns, with no worksheet copy, and
   shows it in the data pane.
2. Generated names `[Calculation_<18 digits>]` and `[Parameter N]` are fine. The corpus shows that names are free
   text, but not how Tableau makes them.
3. Tableau's paste names a clashing caption `"X (2)"`. This comes from the roadmap's research, not from a test.
4. Dropping `user:SplitField*` and `user:ui-builder` attributes leaves a working ordinary calc.
5. The newly created `Parameters` datasource (version 18.1) also loads in older Tableau versions.
6. Comparing formulas as text (with only line endings made the same) is close enough to "identical". Two formulas
   that differ only in spacing count as different, and the import then renames the copy rather than skipping it.
