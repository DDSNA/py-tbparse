# Spec A3: give every library `ValueError` a category; feature subclasses for refusal and integrity

Track: 0.6.0 exit codes and errors. Plan: [plan-0.6.0-exit-codes-and-errors.md](../plan-0.6.0-exit-codes-and-errors.md), WP3 and section 5 ("What the plain sites become"). Common rules: [README.md](README.md#common-rules-for-every-spec) (follow the agent rules file).

- Branch: `feat/classify-errors`
- PR title: `Give each library error a category the command line can turn into an exit code (WP3 of the 0.6.0 plan)`
- PR body starts with: `Refs #186`
- Depends on: A2 merged. Next: A4.

## Goal

1. The 38 `raise ValueError(...)` sites outside `webgui.py` raise a category class from `py_tbparse.errors` (`UsageError` or `InputError`) or a feature class, except three programmer-error sites that stay plain `ValueError`.
2. The feature-error sites that mean "refused on purpose" or "the result would have broken references" raise a small subclass with two parents (feature class + category), so `exit_code_for` gives 5 or 6 instead of 4.

No message changes, no exit-code changes yet (the CLI still picks codes by `except` position until A4), every `except ValueError` keeps working (every new class is a `ValueError`).

**First step, before code:** put the full site list with its category (the two tables below, re-checked on your base) in the PR description. The owner can veto a row there. This is what the plan asks; it is not an open question that blocks the work.

## The rule for a judgement call

`UsageError` if the problem can be known **without opening any file** (a bad option value, an unknown format, an unknown rule id). `InputError` if a file or a name inside a file cannot be used (missing columns in a mapping CSV, a `.twbx` without a `.twb`, an unknown sheet in a workbook). Feature classes stay where a module already raises one; only refusal and integrity sites get a two-parent subclass.

## Table 1: the 38 plain `ValueError` sites (`main` at `1130fa9`, `grep -n 'raise ValueError(' py_tbparse/*.py | grep -v webgui.py`)

| Site | Message starts | Becomes |
| --- | --- | --- |
| `_xml.py:152` | `No .twb file found inside .twbx` | `InputError` |
| `_xml.py:284`, `parser.py:77` | `Unsupported file type` | `InputError` |
| `parser.py:276` | `Validation failed. See parser.last_validation` | `IntegrityError` |
| `cli.py:684` | `{option}: no rule ids in ...` | `UsageError` |
| `cli.py:774` | `--output ... is the template itself` | already `OutputRefusedError` after A2 (check) |
| `findings.py:63` | `severity must be one of` | `UsageError` |
| `findings.py:77` | `rule ... is already registered` | stays `ValueError` (programmer error) |
| `findings.py:111` | `unknown rule` | `UsageError` |
| `findings.py:132` | `no rules for scope` | stays `ValueError` (programmer error: a scope name in code; the plan did not list it; say so in the PR) |
| `findings.py:135`, `:139` | `only: no rule ids given`, `only and skip leave no rule` | `UsageError` |
| `findings.py:222` | `unknown format` | `UsageError` |
| `ci_formats.py:187` | `unknown CI format` | `UsageError` |
| `batch.py:37`, `diff.py:82` | `unknown table` | `UsageError` |
| `precommit.py:32` | `unknown hook command` | `UsageError` |
| `template_check.py:67` | `... is reserved for ...` | `UsageError` |
| `rename.py:91` | `style must be one of` | `UsageError` |
| `rename.py:236`, `templates.py:787` | `fuzzy_cutoff must be between 0 and 1` | `UsageError` |
| `rename.py:394` | `unknown kind(s)` | `UsageError` |
| `rename.py:471`, `templates.py:873` | `mapping is missing column(s)` | `InputError` |
| `rename.py:479` | `unknown kind ... in mapping` | `InputError` |
| `rename.py:502` | two renames collide | `InputError` |
| `rename.py:581` | `exclude must be a list of rename ids` | `UsageError` (a type error of an argument; the GUI sends it) |
| `rename.py:589`, `:595`, `:609` | exclude list problems, "Every rename is left out" | `InputError` (they also reach the GUI) |
| `rename.py:819` | `output must end in ...` | `UsageError` |
| `templates.py:878` | `column ... is mapped to more than one field` | `InputError` |
| `template_batch.py:205`, `:207` | `on_error must be`, `min_mapped is a share` | `UsageError` |
| `template_gui.py:140`, `:145` | `the template has no field`, `the data has no column` | `InputError` |
| `docgen.py:75`, `:103` | heading level, row width | stay `ValueError` (programmer errors) |

That is 38 lines of grep output; `cli.py:774` is handled by A2. The allow-list of plain `ValueError` sites is therefore `findings.py` (registered twice, no rules for scope) and `docgen.py` (two). The plan said three; this spec finds four (`findings.py:132` added). Re-run the grep on your base and handle any new site with the same rule.

## Table 2: feature errors that need a refusal or integrity code

Add the subclasses next to their feature class (same module), each with a one-line docstring:

| New class | Where defined | Sites that raise it instead (message unchanged) | Code |
| --- | --- | --- | --- |
| `SliceStrictError(SliceError, RefusedError)` | `slicer.py` | `slicer.py:163` (`--strict: slicing would drop ...`) | 5 |
| `SliceIntegrityError(SliceError, IntegrityError)` | `slicer.py` | `slicer.py:225` (`the result has new integrity problems, nothing written`) | 6 |
| `SheetCopyRefused(SheetCopyAbort, RefusedError)` | `sheetcopy.py` (next to `SheetCopyAbort`; check where it is defined, it may be `sheetcopy.py` or `sheetcopy_core.py`) | clash under `fail`: `sheetcopy.py:164`, `:171`, `:186`, `dashboardcopy.py:262`; `--strict`: `sheetcopy.py:296`, `dashboardcopy.py:335`; nothing copyable: `sheetcopy.py:361`, `dashboardcopy.py:430` | 5 |
| `SheetCopyIntegrityError(SheetCopyAbort, IntegrityError)` | same module | `sheetcopy.py:304`, `dashboardcopy.py:384` (`integrity check failed on the result`) | 6 |
| `LibraryClashError(LibraryError, RefusedError)` | `library.py` | `library.py:792` (`... is already in the target datasource (on_clash='fail')`) | 5 |
| `StyleClashError(StyleError, RefusedError)` | `style.py` | `_clash_error` (around `style.py:508`) returns it; and, if PR #213 is merged, the `build_styled` raise for `fail` rows (`... format(s) already set in the target with another value`) | 5 |
| `SliceRefused(SliceError, RefusedError)` | `slicer.py` | `slicer.py:142` (`the selected dashboard(s) ... show no worksheet`): nothing to write, like "nothing copyable" | 5 |
| `SanitizeUsageError(SanitizeError, UsageError)` | `sanitize.py` | `sanitize.py:489` (unknown `--keep`), `:496` (output not `.twb`/`.twbx`), `:501` (output must be `.twbx`/`.twb`) | 2 |
| `PruneUsageError(PruneError, UsageError)` | `prune.py` | `prune.py:399` (`the output must end in ...`) | 2 |
| `SliceUsageError(SliceError, UsageError)` | `slicer.py` | `slicer.py:133` (no dashboard named), `:215` (`the output must end in ...`) | 2 |
| `StyleUsageError(StyleError, UsageError)` | `style.py` | `style.py:605` (`output must end in ...`), `:650` (`the output must end in .tps or .style.json`), and the `style extract` output check in `cli.py` `_run_style` (`the output must end in .style.json`) | 2 |

The usage rows exist because the plan's per-command table (section 3) gives "bad extension" and "unknown `--keep`" exit 2 for `sanitize`, `prune` and `slice`. Look for more "output must end in" / "the output is a ..." checks in other writers (`grep -n 'must end in\|the output is a' py_tbparse/*.py`) and treat them the same way; list them in the PR. `slicer.py:136` (unknown dashboard) stays a plain `SliceError` (4: the name is only known after opening the workbook, plan section 2).

Names are this spec's choice (the plan named only `SliceIntegrityError` and `SliceStrictError`); keep them unless a name already exists. They are **not** exported in `__all__` (feature-level detail; users catch the feature class or the category). If you export any, add `docs/api.md` bullets.

Not changed: `on_clash must be one of ...` sites (`sheetcopy.py:118`, `dashboardcopy.py:231`, `library.py:664`, `style.py:461`): the CLI never reaches them (argparse `choices`), so their code does not matter; they stay as they are. `SanitizeError` and `PruneError` have no refusal or integrity site today (read on `1130fa9`: `sanitize.py` raises it 3 times and `prune.py` once, all usage rows above); write that in the PR.

## Tests to add (`tests/test_error_categories.py`)

- `test_no_plain_value_error_outside_the_allow_list`: parse each `py_tbparse/*.py` except `webgui.py` and `errors.py` with `ast`, collect `raise ValueError(...)` calls with their file and line, and assert the set of files is exactly `{"findings.py": 2, "docgen.py": 2}` by count. (Use `ast`, not text search, so a comment does not count.)
- `test_usage_examples` (parametrised): `findings.run_rules` with an unknown id raises `UsageError`; `rename` style with a bad name; `fuzzy_cutoff=2`; `batch.scan_folder(..., table="nope")`; each is still caught by `except ValueError`.
- `test_input_examples`: a mapping CSV without the required columns for `rename.load_rename_mapping` (or whichever function reads it at `rename.py:471`) raises `InputError`; `TwbParser` on a `.txt` file raises `InputError`; a `.twbx` zip with no `.twb` raises `InputError`.
- `test_validate_error_true_raises_integrity`: `TwbParser(...).validate(error=True)` on a fixture with a broken relationship (monkeypatch as `tests/test_exit_codes.py::test_validate_broken_relationship_is_2` does) raises `IntegrityError`.
- `test_refusal_subclasses` (parametrised): `slice_workbook(..., strict=True)` on a case that drops an action raises `SliceStrictError` (find the case in `tests/test_slice.py`), which is a `SliceError` and a `RefusedError`; a sheet copy clash under `fail` raises `SheetCopyRefused`, still caught as `SheetCopyAbort`; `import_library(..., on_clash="fail")` on the clashing fixture raises `LibraryClashError`; `style.import_palettes(..., on_clash="fail")` on a clash raises `StyleClashError`.
- `test_integrity_subclasses`: the slice integrity case (find it in `tests/test_slice.py`, search `integrity_new`) raises `SliceIntegrityError` with `--write`.
- `test_usage_subclasses`: `sanitize(wb, out, keep=("nope",))` raises `SanitizeUsageError`; `sanitize` to a `.csv` output, `prune` and `slice_workbook` to a wrong extension raise the usage subclass; each is still caught by `except SanitizeError` / `PruneError` / `SliceError`.
- `test_exit_code_for_new_classes`: `exit_code_for` gives 5 for each `*Refused`/`*Strict`/`*Clash` class, 6 for each `*Integrity*` class and 2 for each `*UsageError` class.

Existing tests that match messages or catch the feature classes must pass untouched.

## Docs

- `AGENTS.md` `errors.py` row: add the rule for new code ("usage if knowable without opening a file, else input; refusal and integrity sites raise a two-parent subclass; plain `ValueError` only for programmer errors, and the allow-list test names them").
- `docs/development.md`: a short "Errors" paragraph with the same rule and the message rules of plan section 5 ("Message format rules"), for new messages only. (A8 also edits this page; keep yours short.)
- `docs/api.md`: nothing unless you export a name.

## How to verify

```bash
PYTHONPATH=$PWD /home/claude-user/ai-sandbox/py-tbparse/.venv/bin/pytest -q tests/test_error_categories.py tests/test_error_base.py tests/test_exit_codes.py tests/test_slice.py tests/test_sheetcopy.py tests/test_dashboardcopy.py tests/test_library.py tests/test_style.py tests/test_rename.py tests/test_findings.py
```

then the whole non-browser suite. Exit codes must be unchanged: `tests/test_exit_codes.py` passes as it is.

## Not verifiable here

Nothing to check in Tableau.

## Risks

- Largest review load of the track: 38 judgement calls. Split by module into two PRs only if the diff passes about 600 lines (the plan allows it); then the first PR is `rename.py`, `templates.py`, `template_*.py`, the second the rest.
- `SheetCopyAbort` is caught in `cli.py` (`_run_sheet`, `_run_dashboard`) and in `webgui.py` (rerun as `rename` to list every clash). The subclasses keep `SheetCopyAbort` as first parent, so those handlers still match. Read them before and after.
- Two-parent classes put the feature class first; an MRO error at import time means the order is wrong.

## Definition of done

Both tables done (or the PR says which row differs and why), allow-list test in, no message or exit code changed, whole non-browser suite and CI green, no version bump.
