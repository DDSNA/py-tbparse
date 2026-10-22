# Spec A4: central exit handling in the CLI, crash = 3 everywhere

Track: 0.6.0 exit codes and errors. Plan: [plan-0.6.0-exit-codes-and-errors.md](../plan-0.6.0-exit-codes-and-errors.md), WP4, sections 2 and 3. Common rules: [README.md](README.md#common-rules-for-every-spec) (follow the agent rules file).

- Branch: `feat/exit-codes-central`
- PR title: `CLI: one place turns an error into its exit code; unexpected errors exit 3 (WP4 of the 0.6.0 plan)`
- PR body starts with: `Refs #127`. Say in the body: "Breaking (0.6.0): table commands, diff, batch and docs change exit codes; see docs/cli.md."
- Depends on: A3 merged. Next: A5, A6, A7 (any order; see README).

## Goal

1. `cli.main` never ends in an uncaught traceback with exit 1: an exception that escapes a command gives `exit_code_for(e)`; a real crash (code 3) prints `internal error: <message>` and the traceback on stderr.
2. The plain table commands (`WORKBOOK [TABLE]`, `tables`, `graph`, `validate`'s load step), `diff`, `batch` and `docs`/`dictionary` use the new codes.
3. `docs/cli.md`'s exit-code table gets eight code columns (0 to 7) and a note that the scheme is being rolled out until A8.

The other commands keep their codes in this package (A5 to A7 move them).

## Files and functions (read on `main` at `1130fa9`)

`py_tbparse/cli.py`:

- `main(argv)` (bottom of the file, around line 1568): today it dispatches subcommands, then parses, loads `TwbParser(args.workbook)` in `try/except (FileNotFoundError, ValueError)` returning 1, then prints. `validate` returns `0 if result["ok"] else 2`.
- `_run_diff` (around line 155): `except (FileNotFoundError, ValueError)` returns 1.
- `_run_batch` (around line 188): `not Path(args.directory).is_dir()` prints and returns 1.
- `_run_docs` (around line 1512): `except _WORKBOOK_ERRORS` returns 2; "--output is the workbook itself" returns 2.
- `_write(text, output)` (around line 95): writes `-o`; an unwritable path raises `OSError` uncaught today.

## Interfaces

```python
# cli.py
from .errors import ExitCode, OutputRefusedError, InputError, exit_code_for

def _fail(e: BaseException) -> int:
    """Print the error the way the CLI does and return its exit code (errors.exit_code_for)."""

def main(argv: list[str] | None = None) -> int:      # public entry point, same signature
    ...                                               # wraps _main(argv)

def _main(argv: list[str] | None) -> int:            # today's body of main, moved unchanged except as below
```

`_fail(e)`:

- code = `exit_code_for(e)`.
- code 3: print `internal error: {type(e).__name__}: {e}` and then `traceback.format_exception(e)` (use `traceback.format_exception(type(e), e, e.__traceback__)` for Python 3.9) to stderr, plus one line `this is a bug in py-tbparse; please report it with the command you ran`.
- otherwise: print `error: {e}` to stderr (the format every command uses today).
- return code.

`main(argv)`:

```python
def main(argv=None):
    try:
        return _main(argv)
    except Exception as e:          # never KeyboardInterrupt or SystemExit: argparse exits must pass through
        return _fail(e)
```

Keep `raise SystemExit(main())` at the bottom. Do not catch `BaseException`. `BrokenPipeError` (an `OSError`) would become 4 with an `error:` line; the current code does nothing special for it, so do nothing special now and note it in the PR.

Inside `_main`:

- Replace the `TwbParser` load handler with `except Exception as e: return _fail(e)` (so a malformed `.twb`, a missing file, a bad zip all give 4; a plain `ValueError` from the parser gives 3, which is the plan's rule "unclassified is a bug").
  **Check first:** run `py-tbparse tests/fixtures/test_for_wenjie.twb` against a truncated copy (`head -c 500`) and a `.txt` file; read what `TwbParser` raises. If it raises a plain `ValueError` for a user mistake that A3 did not classify, classify it here as `InputError` in the module that raises it, and list it in the PR.
- `validate`: only its load step changes here (unreadable 1 -> 4, through the line above). The broken-relationship code stays 2 until A5.
- `_write` failures (`-o` into a missing folder, no permission) are not caught locally: they escape to `main` and give 4 through `exit_code_for(OSError)`.

`_run_diff`: `except Exception as e: return _fail(e)` around both loads (missing file 1 -> 4).
`_run_batch`: not a directory -> `return _fail(InputError(f"not a directory: {args.directory}"))` (1 -> 4; same message).
`_run_docs`: load failure -> `_fail(e)` (2 -> 4); output is the workbook -> `_fail(OutputRefusedError("--output is the workbook itself; refusing to overwrite it"))` (2 -> 5; same message).

Leave every other `_run_*` alone in this package, except that an exception their own `except` does not catch now reaches `main` and gives its code instead of a traceback with 1. That is intended (plan: "any command: an exception that nobody expected, 1 -> 3").

## `docs/cli.md` "Exit codes"

- Table header becomes `| Command | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |` with the matching separator row. Every existing row gets four more cells. For commands not moved yet, cells 4 to 7 say `not used` and the old cells stay as they are, except the "3" cell, which becomes `an unexpected error (traceback on stderr; a bug)` for every row (that is true for all commands after this package).
- Rows moved in this package (from plan section 3): `WORKBOOK [TABLE]`: 1 `not used`, 4 `workbook not found or unreadable (malformed .twb/.twbx, not a zip), or -o cannot be written`; `WORKBOOK validate`: 1 `not used`, 4 `workbook cannot be loaded`, 2 stays "a relationship is broken" (until A5); `diff A B`: 1 `not used`, 4 `a workbook not found or unreadable`; `batch DIR`: 1 `not used`, 4 `DIR is not a directory`; `docs`/`dictionary`: 2 `usage error`, 4 `workbook cannot be read`, 5 `-o is the workbook itself`.
- Above the table, replace the "not one scheme" sentence with: "0.6.0 moves every command to one scheme (0 ok, 1 finding, 2 usage, 3 crash, 4 bad input, 5 refused, 6 integrity, 7 partial). The move is in progress on `main`: rows that still use the old meanings say so in their cells. Released versions up to 0.5.x use the old table." Keep the "What the codes mean" list but add the new codes at the end with one line each; A8 rewrites it.
- Remove the bullet "A Python exception that no command catches ends the process with the traceback and exit code 1": it is no longer true. Replace with "An error nobody expected exits 3 with `internal error:` and the traceback."

## `tests/test_exit_codes.py`

- `table_rows()`: expect 9 cells per row (`assert len(cells) == 9`); `test_table_cells_are_plain_text_of_five_columns` becomes `..._of_nine_columns` with `len(cells) == 8`.
- Update the cases of the moved rows: `[missing]` -> 4; `[missing, "validate"]` -> 4; `["diff", WENJIE, missing]` -> 4; `["batch", missing]` -> 4; `["docs", missing]` -> 4. Add `["docs", WENJIE, "-o", WENJIE]` -> 5 (check the `-o` flag name in `_run_docs`: it is `--output`/`-o`).
- New tests:
  - `test_malformed_workbook_is_bad_input`: write `tmp_path/"bad.twb"` with `"<workbook"` (truncated XML) and assert `cli.main([str(bad), "overview"]) == 4` and stderr starts with `error:` (no traceback).
  - `test_unwritable_output_is_bad_input`: `cli.main([WENJIE, "overview", "-o", str(tmp_path / "no" / "such" / "x.csv")]) == 4`.
  - `test_unexpected_exception_is_crash` (parametrised over three targets): monkeypatch `cli.TABLE_SPECS["overview"]` (use `monkeypatch.setitem`), `cli.diff_workbooks` and `cli.scan_folder` to raise `RuntimeError("boom")`; each command returns 3 and stderr contains `internal error: RuntimeError: boom` and `Traceback`.
  - `test_usage_and_help_unchanged`: an unknown option gives 2 (via `SystemExit`), `--help` gives 0.
  - `test_keyboard_interrupt_is_not_swallowed`: monkeypatch the overview getter to raise `KeyboardInterrupt`; `pytest.raises(KeyboardInterrupt)` around `cli.main(...)`.

Other test files that assert the old codes for these commands (search `tests/` for `cli.main(` with `== 1` near `diff`, `batch` or a missing workbook, and `test_cli.py`): update them to the new code and say so in the PR.

## Other docs

- The per-command pages that state codes for these commands: `docs/audit.md` (the `docs`/`dictionary` part), `docs/cli.md` prose above the table. Search `docs/` for "exit" near `diff`, `batch`, `docs`. A8 does the full sweep; fix only what this package makes false.
- `README.md`: search for "exit"; change only lines about these commands.
- `AGENTS.md` `cli.py` row: add "errors that reach `main` go through `_fail` (`errors.exit_code_for`); an unexpected exception exits 3 with `internal error:` and the traceback".

## How to verify

```bash
PYTHONPATH=$PWD /home/claude-user/ai-sandbox/py-tbparse/.venv/bin/pytest -q tests/test_exit_codes.py tests/test_cli.py tests/test_diff.py tests/test_batch.py tests/test_docgen.py tests/test_ci_formats.py
printf '<workbook' > /home/claude-user/.claude/jobs/b5d69d0e/tmp/bad.twb
PYTHONPATH=$PWD /home/claude-user/ai-sandbox/py-tbparse/.venv/bin/python -m py_tbparse.cli /home/claude-user/.claude/jobs/b5d69d0e/tmp/bad.twb overview; echo "exit $?"     # expect 4, no traceback
```

then the whole non-browser suite.

## Not verifiable here

Nothing to check in Tableau. How real CI scripts react to the changed codes cannot be tested; the release notes (A10) carry the migration text.

## Risks

- Catching too much: `except Exception` must not catch `SystemExit` (argparse and `--help`) or `KeyboardInterrupt`; the tests pin both.
- A plain `ValueError` that A3 missed now exits 3 instead of 1 or 2: that is the plan's intent, but check the CLI test suite for such cases and classify them in their module rather than special-casing the CLI.
- Between this package and A8 `main` has a mixed scheme. No release may be cut in between (the README of the specs and the roadmap say so).

## Definition of done

`main` wraps `_main`, `_fail` exists, the moved rows return the codes above, the table has eight code columns and the rollout note, the tests above pass, whole non-browser suite and CI green, no version bump.
