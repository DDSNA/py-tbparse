# Spec A2: every `raise FileExistsError` becomes `OutputRefusedError`

Track: 0.6.0 exit codes and errors. Plan: [plan-0.6.0-exit-codes-and-errors.md](../plan-0.6.0-exit-codes-and-errors.md), WP2 and the table in section 5. Common rules: [README.md](README.md#common-rules-for-every-spec) (follow the agent rules file).

- Branch: `feat/output-refused-error`
- PR title: `Raise OutputRefusedError where an output would overwrite a file (WP2 of the 0.6.0 plan)`
- PR body starts with: `Refs #186`
- Depends on: A1 merged (`py_tbparse/errors.py` exists). Next: A3.

## Goal

Every deliberate "refusing to overwrite" in the library raises `OutputRefusedError` (from `py_tbparse.errors`) instead of `FileExistsError`. Because `OutputRefusedError` is also a `FileExistsError`, a `ValueError` and an `OSError`, every existing `except` keeps working. Messages stay byte-identical. No exit code changes in this package (the CLI still chooses codes by its `except` clauses until A4).

## The sites (25 on `main` at `1130fa9`; the plan counted 24 at `1fa6acd`)

Found with `grep -n 'raise FileExistsError' py_tbparse/*.py`. Re-run it on your base: PR #213 (WP7-2b) adds `raise FileExistsError` in `style.apply_style`, and any WP7 package merged before you adds more. Convert every site you find, not only this list.

| File | Lines (approx.) | Message (keep exactly) |
| --- | --- | --- |
| `cli.py` | 585, 1064 | `refusing to overwrite {out} (pass --overwrite)`; `refusing to overwrite the input: {out}` |
| `dashboardcopy.py` | 425, 427 | `refusing to overwrite an input: {out}`; `refusing to overwrite existing file: {out}` |
| `library.py` | 991 | `refusing to overwrite existing file: {out}` |
| `prune.py` | 401, 403 | the input workbook; existing file `(use --overwrite)` |
| `rename.py` | 821 | existing file |
| `scaffold.py` | 164, 328 | existing file |
| `sheetcopy.py` | 356, 358 | an input; existing file |
| `slicer.py` | 217, 219 | the input workbook; existing file `(use --overwrite)` |
| `style.py` | 313, 315, 607, 653 | `refusing to write over {path}: write a new file and copy it into place yourself`; existing file; the input (twice) |
| `sanitize.py` | 498 | the input workbook |
| `template_batch.py` | 216 | `refusing to overwrite {summary} (pass overwrite)` |
| `template_drift.py` | 434 | `{out} exists; refusing to overwrite` |
| `template_update.py` | 436 | an input |
| `templates.py` | 309, 400, 1739 | existing file; the source workbook; an input |

Also in scope (plan section 5): the `cli.py` site that raises `ValueError(f"--output {args.output} is the template itself; it would be overwritten")` (around line 774, in `_run_template`) becomes `OutputRefusedError` with the same message.

Out of scope: places that refuse by printing and returning a code without raising (`_run_docs`, `_run_diff_xml` in `cli.py`); A5 and A6 handle them. `open(..., "x")` calls that let Python raise its own `FileExistsError` (search `"xb"` and `'x'`): leave them; A4 maps a plain `FileExistsError` to 4, and the explicit check before them (where there is one) raises the new class. List any such place you find in the PR body.

## How to change a site

```python
from .errors import OutputRefusedError
...
raise OutputRefusedError(f"refusing to overwrite existing file: {out}")
```

Import at module top. Do not change the message, the condition, or the order of checks.

## Tests to add (`tests/test_output_refused.py`)

- `test_no_bare_file_exists_error_left`: reads every `py_tbparse/*.py` except `errors.py` and asserts the text `raise FileExistsError` does not occur (a guard for new code).
- `test_refusals_raise_output_refused_with_the_old_message` (parametrised, one case per public entry point that is cheap to drive with existing fixtures): for each, call it so that the output already exists (or is the input) and assert `pytest.raises(OutputRefusedError, match=re.escape(<old message>))` and also that `except FileExistsError` catches it. Cover at least: `rename.apply_field_renames` (or `build`... whichever writes: read `rename.py` around line 821), `prune.prune`, `slicer.slice_workbook`, `sanitize.sanitize`, `library.import_library`, `style.import_palettes`, `style.export_palettes`, `scaffold.save_scaffold` (or the function around line 164), `sheetcopy.copy_sheets`, `dashboardcopy.copy_dashboards`, `templates.apply_template`, `template_update.update_from_answers`. Reuse the fixtures the existing test file of each module uses (`tests/test_<module>.py`); copy their setup, do not import test functions across files except helper builders that are already imported that way elsewhere (`tests/test_exit_codes.py` imports `test_dashboardcopy` helpers).
- `test_cli_overwrite_refusals_unchanged`: `cli.main(["sanitize", WENJIE, out])` run twice returns 2 the second time (as in `tests/test_exit_codes.py`), and `cli.main(["slice", WENJIE, "-d", <a dashboard of the fixture>, "--write", "-o", existing])` returns 2; both print a line starting `error: refusing to overwrite` on stderr (`capsys`). Does `tests/fixtures/test_for_wenjie.twb` have a dashboard? Check with `py-tbparse tests/fixtures/test_for_wenjie.twb dashboards`; if not, use `tests/fixtures/public/filtering.twb`.

Messages: the existing tests that match messages must pass untouched.

## Docs

- `AGENTS.md`: in the `errors.py` row add "every 'refusing to overwrite' raises `OutputRefusedError` (a `FileExistsError` too); a test forbids `raise FileExistsError` elsewhere".
- `docs/api.md`: no new names.

## How to verify

```bash
grep -n 'raise FileExistsError' py_tbparse/*.py        # only errors.py may match (it should not either)
PYTHONPATH=$PWD /home/claude-user/ai-sandbox/py-tbparse/.venv/bin/pytest -q tests/test_output_refused.py tests/test_exit_codes.py tests/test_cli.py
```

then the whole non-browser suite (README rule 8). The GUI routes catch `FileExistsError` and `ValueError`; `tests/test_webgui*.py` must pass unchanged.

## Not verifiable here

Nothing to check in Tableau; no output changes.

## Risks

- A site whose surrounding `except FileExistsError` re-raises a different type: read each caller (`grep -n 'except.*FileExistsError' py_tbparse`); behaviour must not change.
- A worker process (`template apply-folder --workers`) sends the exception back by pickling: A1 tested pickling; `tests/test_template_batch.py` must pass.

## Definition of done

No `raise FileExistsError` in `py_tbparse/` outside `errors.py`, guard test in, messages and exit codes unchanged, whole non-browser suite green, CI green, no version bump.
