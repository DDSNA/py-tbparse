# Spec A7: partial results and refusals (`sheet copy`, `dashboard copy`, `library`, `style`, `template` writers, `apply-folder`)

Track: 0.6.0 exit codes and errors. Plan: [plan-0.6.0-exit-codes-and-errors.md](../plan-0.6.0-exit-codes-and-errors.md), WP7 and section 3. Common rules: [README.md](README.md#common-rules-for-every-spec) (follow the agent rules file).

- Branch: `feat/exit-codes-partial`
- PR title: `Exit codes 5 (refused) and 7 (partial) for the copy, library, style and template writers (WP7)`
- PR body starts with: `Refs #127`. Say "Breaking (0.6.0)".
- Depends on: A4 merged (A3 gives `SheetCopyRefused`, `LibraryClashError`, `StyleClashError`). Can run beside A5 and A6; rebase on whichever merges first.

## BLOCKED (owner): dry-run codes

Plan open question 5: should a dry run return the code its real run would? Today the dry runs disagree with each other (read on `1130fa9`):

| Command | Dry run today | `--write` today |
| --- | --- | --- |
| `sheet copy`, `dashboard copy` | 2 when some sheet/dashboard would be refused (the `return 2 if report["refused"] else 0` line runs for both) | 2 |
| `library import` | 0, even with entries that cannot be imported (prints "N entries cannot be imported") | 2 |
| `style import` | 1 when a palette name clashes under `--on-clash fail` | 1 (clash) |
| `slice` | 2 when the result would have new integrity problems (moved to 6 by A6, so it already matches `--write`) | 2 |

Plan default: `style import` dry-run clash -> 5 (as `--write`), `library import` dry run stays 0; the plan does not say what a `sheet copy`/`dashboard copy` dry run with a refusal returns (its table says "done, or a dry run: 0", which today's code does not do).

What to do: build everything in this spec **except** the dry-run return values. Put the dry-run changes in one separate, last commit that follows the plan default for `style import` (5) and `library import` (0), and for `sheet copy`/`dashboard copy` returns the same code as `--write` would (7), because that is what today's code already does (non-zero, same as write). Say in the PR body that this commit waits for the owner's answer and can be dropped or changed. Do not mark the PR ready to merge in your report until the caller confirms the answer.

## Changes (functions in `py_tbparse/cli.py`, `1130fa9`)

| Command | Case | Old | New | How |
| --- | --- | --- | --- | --- |
| `sheet copy` (`_run_sheet`) | unreadable file, no sheet found in the source | 1 | 4 | `except (SheetCopyError, FileExistsError, *_WORKBOOK_ERRORS)` returning 1 -> `except Exception as e: return _fail(e)`; an unknown sheet name must map to 4 (check its class: if it is `SheetCopyAbort`, which A3 left at 4, fine) |
| | clash under `--on-clash fail`, `--strict` refusal, nothing copyable (raised), output refused | 1 | 5 | `SheetCopyRefused`, `OutputRefusedError` through `_fail` |
| | "no sheet can be copied" (the CLI's own check after the report: `if not report["copied"] and not report["skipped"]`) | 1 | 5 | `return ExitCode.REFUSED` (message unchanged) |
| | some sheet refused, the others copied, `--write` | 2 | 7 | `return ExitCode.PARTIAL if report["refused"] else 0` (see BLOCKED for the dry run) |
| `dashboard copy` (`_run_dashboard`) | same four cases | 1 / 1 / 1 / 2 | 4 / 5 / 5 / 7 | same changes |
| `library export`, `show` (`_run_library`) | any error | 1 | 4 (output exists: 5) | the outer `except (...)` returning 1 -> `_fail(e)` |
| `library import` | `--on-clash fail` meets a clash | 1 | 5 | `LibraryClashError` |
| | other error | 1 | 4 (output exists: 5) | `_fail` |
| | `--write`: some entry failed or was skipped as a dependent | 2 | 7 | `return ExitCode.PARTIAL` |
| `style show`, `extract` | any error | 1 | 4 (output exists 5; wrong output suffix 2 via `StyleUsageError`) | `_run_style` outer `except` -> `_fail(e)` |
| `style export`, `import` | any error | 1 | 4 (output exists: 5) | same |
| | some palette was invalid; the others written | 2 | 7 | `return ExitCode.PARTIAL` |
| | `import` dry run with a clash under `--on-clash fail` | 1 | 5 | the inline `return 1` after "N palette name(s) clash" -> `ExitCode.REFUSED` (**BLOCKED commit**, see above) |
| `style apply` (only if PR #213, WP7-2b, is merged on your base; check `grep -n '"apply"' py_tbparse/cli.py` in `_run_style`) | `--on-clash fail` with kept formats (the inline `return 1`) | 1 | 5 | `ExitCode.REFUSED` |
| | unsupported or no-target after `--write` (the `return 2`) | 2 | 7 | `ExitCode.PARTIAL` |
| `template make`, `show`, `targets`, `target-make`, `update`, `apply` (`_run_template` outer `except`, around line 855) | `TemplateError` and other invalid input, missing file, bad zip or JSON | 1 | 4 | `_fail(e)` |
| | existing output, or output is an input (A2: `OutputRefusedError`, includes "--output is the template itself") | 1 | 5 | `_fail(e)` |
| | malformed `--param`/`--token`/`--column`, `--output` without `--markdown`, `--table` missing | 2 | 2 | unchanged (argparse `ap.error`) |
| `template apply-folder` (`_run_apply_folder`, around line 554) | some file skipped or failed | 1 | 7 | `return 0 if (table["status"] == "ok").all() else ExitCode.PARTIAL` |
| | nothing written at all | 1 | 7 | same line (plan: still 7; read as adopted with the scheme) |
| | error before the run (template unreadable / summary exists) | 1 | 4 / 5 | it raises out of `apply_template_folder`: make sure the call is inside `_run_template`'s handler (it is called from `_run_template`; check) so `_fail` gives 4, or 5 for the summary `OutputRefusedError` (A2 converted `template_batch.py:216`) |

`_run_template_update`'s `except TemplateError: ...; raise` re-raises into `_run_template`'s handler: after the change it gives 4. Keep the re-raise.

Messages stay the same.

## `docs/cli.md` rows to rewrite

`sheet copy SRC --to TARGET` and `dashboard copy SRC --to TARGET`: 0 done, or a dry run with nothing refused; 2 usage; 3; 4 unreadable file, sheet/dashboard not found; 5 clash under `--on-clash fail`, `--strict` refusal, nothing copyable, output refused (nothing written); 7 some sheet/dashboard refused, the others copied (dry run: see the answer to the BLOCKED question).
`library export`, `show`: 0; 2; 3; 4 any error; 5 output exists.
`library import`: 0 done or a dry run; 2; 3; 4 other error; 5 clash under `--on-clash fail`, output exists; 7 with `--write` some entry failed or was skipped as a dependent.
`style show`, `extract` (and `check` if A5 kept it in this row): 0; 2 usage, wrong output suffix; 3; 4 any error; 5 output exists.
`style export`, `import` (and `apply` if built): 0; 2; 3; 4; 5 output exists, clash under `--on-clash fail`; 7 some palette invalid (apply: some format unsupported or with no target), the rest written.
`template make` ... `apply`: 0; 2; 3; 4 invalid input, missing file, bad zip or JSON; 5 output exists or is an input.
`template apply-folder`: 0 every file written; 2; 3; 4 error before the run; 5 summary exists; 7 some file skipped or failed (also when none was written).

Column 1 becomes `not used` in all these rows.

## Tests (`tests/test_exit_codes.py` and module tests)

Update cases: `["sheet", "copy", WENJIE, "--sheets", "nope", "--to", WENJIE]` -> read what it is (unknown sheet: 4 if `SheetCopyAbort` maps to 4, or 5 if the CLI's "no sheet can be copied" path is what fires; assert the code that the classification gives and name the case in the test); `["dashboard", "copy", dsrc, "--dashboards", "Nope", ...]` likewise; the `Dash,Lone --write` case -> 7; `["library", "show", none.json]` -> 4; `["library", "import", target.twb, lib.json]` (clash under default `fail`) -> 5; the `--on-clash rename --write` partial case -> 7; `["style", "export", bad.tps, ...]` -> 7; `["style", "show", missing]` -> 4; `["template", "show", missing]` -> 4; `["template", "apply-folder", TEMPLATE, missing]` -> 4 (a missing folder: check whether it raises before the run or produces an empty table; assert what happens and make the docs say it); `test_sheet_copy_partial_refusal_is_2` -> `..._is_7`.

Add (plan WP7 acceptance):

- `test_partial_writes_the_rest`: sheet copy with one refused sheet and `--write -o out.twb` returns 7 and `out.twb` exists and holds the other sheet (`TwbParser(out).get_dashboards()`/worksheets list).
- `test_clash_under_fail_writes_nothing` (parametrised: `sheet copy`, `library import --write`, `style import --write`): returns 5 and the output path does not exist.
- `test_apply_folder_one_bad_file_is_partial`: a folder with one good CSV and one bad file returns 7 and `summary.csv` lists the bad one (reuse the fixtures of `tests/test_template_batch.py`).
- `test_dry_runs` (in the BLOCKED commit): one case per command in the BLOCKED table, asserting the default described there.

## Docs

- Per-command pages: `docs/sheet-copy.md`, `docs/dashboard-copy.md`, `docs/libraries.md`, `docs/styles.md` (export, import, apply), `docs/templates.md` (writers and `apply-folder`).
- CLI help strings stating codes: the `copy` subparser descriptions in `_run_sheet`/`_run_dashboard` ("Exit codes: 0 done, 1 error ..., 2 some sheet was refused"), `style apply`'s description (from #213), `library` and `template apply-folder` help (search "exit" in `build_library_arg_parser`, `build_template_arg_parser`, `build_style_arg_parser`).
- `AGENTS.md` rows: `sheetcopy.py` ("a refusal ... skips only that sheet (exit 2)"), `dashboardcopy.py`, `library.py`, `style.py` if they state codes.

## How to verify

```bash
PYTHONPATH=$PWD /home/claude-user/ai-sandbox/py-tbparse/.venv/bin/pytest -q tests/test_exit_codes.py tests/test_sheetcopy.py tests/test_dashboardcopy.py tests/test_library.py tests/test_style.py tests/test_template_batch.py tests/test_templates.py tests/test_cli.py
```

(and `tests/test_style_apply.py` if #213 is merged), then the whole non-browser suite. The GUI does not use exit codes; `tests/test_webgui_copy.py`, `test_webgui_libraries.py`, `test_webgui_styles.py` must pass unchanged.

## Not verifiable here

No Tableau involved; outputs do not change.

## Risks

- The dry-run question is the one place where the plan's own table and today's code disagree; the BLOCKED commit keeps it reviewable.
- `library import` in the CLI already defaults to `--on-clash fail`; A11 (the API default flip) does not change the CLI. If A11 merged first, its agreement test asserts the CLI code for a clash: update it from 1 to 5 here.

## Definition of done

Every non-dry-run row returns its new code, the dry-run commit is separate and labelled, docs and help texts updated, tests in, whole non-browser suite and CI green, no version bump; the report says the PR waits for the dry-run answer.
