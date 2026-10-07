# Sheet copy: the shared core (WP14b)

Part of [py-tbparse](https://github.com/DDSNA/py-tbparse). `py_tbparse/sheetcopy_core.py` holds the pieces that `sheet copy` ([sheet-copy.md](sheet-copy.md)) is built from. Nothing in it writes a file. Nothing here was opened in Tableau Desktop. It is checked on small synthetic workbooks and on the 200-workbook corpus by re-reading and by invariants, not by Tableau.

```python
from py_tbparse import TwbParser
from py_tbparse.sheetcopy_core import (dependency_closure, match_datasource, compare_to_target,
                                       copy_sheet_element, copy_window, new_uuid)

src, dst = TwbParser("a.twb").xml_doc, TwbParser("b.twb").xml_doc
closure = dependency_closure(src, "Sales by region")
target = match_datasource(src, closure.datasource, dst)       # same connection AND same internal name
plan = compare_to_target(src, closure, dst, target)           # present / identical / add / clash / missing / blocked
```

## What is in it

| Function | What it does |
| --- | --- |
| `sheet_datasources(doc, sheet)` | The non-Parameters datasources of a worksheet (more than one is a blend). |
| `dependency_closure(doc, sheet)` | Every field, calculation, parameter, group or set, and bin the sheet needs, **taken from the source datasource**. The sheet's cached `datasource-dependencies` is only where the search starts: it is not a closure (in the corpus a cached calculation names a field the list lacks 62 times). Calculations come back with their dependencies first. Hidden `[Action (...)]` groups, Tableau's own names (`[:Measure Names]`, `[Multiple Values]`, `(generated)` fields) and names the datasource does not define are listed apart (`action_groups`, `builtin`, `unresolved`), and a formula that points at another datasource goes to `cross_datasource`. |
| `compare_to_target(src, closure, dst, target)` | How the closure meets a target datasource, by internal name. A calculation with the same formula is `identical`, a missing one is `add`, the same name with another formula is `clash`, a physical field, group or bin the target lacks is `missing`, and a calculation that depends on something missing, clashing or blocked is `blocked`, even when the target has it (it would show other values). Formulas are compared as text. A group or set is `identical` when its `groupfilter` tree is the same (attributes sorted, the operands of a union or intersection in any order), otherwise a `clash`. |
| `connection_signature(ds)`, `match_datasource(...)` | Finds the target datasource with the same connection: class, server, database, schema, port, file base name (not its folder) and table names; credentials are not part of it. **First slice: the match must have the same internal name.** A different name raises `SheetCopyError` that says which name the target uses; `allow_rename=True` returns it for later work. No match, several matches and a datasource with no connection are errors, never a guess. |
| `rewrite_references(el, ds_map, names, params, captions)` | Rewrites a copied element in place: `[old].[x]` pairs anywhere (formulas, `rows`, `cols`, filters, encodings, title tokens, the quoted `[ds].[avg:Sales:qk]` members of a Measure Names filter), `datasource` attributes, the datasource entry's `name` and caption, and the cached dependency copies (`name`, `column`, `formula`, `ordering-field`). `names` maps `[Old]` to `[New]` and also works inside instance names (`[sum:Old:qk]`, `[Calc_1:qk]`); `params` does the same for `[Parameters].[X]`. Quoted text in a formula is left alone, a pair that names another datasource is left alone. An empty map changes nothing. |
| `new_uuid`, `renew_uuids`, `copy_sheet_element`, `copy_window`, `add_window`, `windows_element` | uuid and window helpers. `new_uuid` and `add_window` were lifted from `scaffold.py`, which uses them now with the same result. A copied sheet and its window get new `simple-id` uuids; a copied window is not hidden unless asked. |

## Not in it

No CLI, no writing of a workbook, no thumbnail, no dropping of action filters, no sheet-name clash handling, no calculation or parameter import (the library planner, WP14e), no sets, groups or bins to add, no blends, no copying a datasource that the target lacks. Field mapping inside sheets works in the rewriter but nothing offers it yet; the first slice only needs the datasource prefix.

## Checks

`tests/test_sheetcopy_core.py` (synthetic workbooks) and `tests/test_sheetcopy_core_corpus.py` (skipped when `tests/corpus/files` is missing; the corpus is not committed). Over the corpus: the closure of every single-datasource sheet is computed, a sheet compared with its own workbook needs nothing, moving the datasource name away and back restores the sheet XML exactly, and a copy gets all-new uuids.
