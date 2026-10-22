# Spec A6: exit codes of `sanitize`, `prune`, `slice`, `rename` and `scaffold`

Track: 0.6.0 exit codes and errors. Plan: [plan-0.6.0-exit-codes-and-errors.md](../plan-0.6.0-exit-codes-and-errors.md), WP6 and section 3. Common rules: [README.md](README.md#common-rules-for-every-spec) (follow the agent rules file).

- Branch: `feat/exit-codes-writers`
- PR title: `Exit codes of sanitize, prune, slice, rename and scaffold follow the 0.6.0 scheme (WP6)`
- PR body starts with: `Refs #127`. Say "Breaking (0.6.0)"; give the `slice` dry-run change (2 -> 6) its own line, since it is the case most likely to be in someone's CI script.
- Depends on: A4 merged (A3 gives the classes this relies on). Can run beside A5 and A7; rebase on whichever merges first (same table and test file).

(`docs`/`dictionary` were moved in A4.)

## Changes (plan section 3; functions in `py_tbparse/cli.py` on `1130fa9`)

| Command | Case | Old | New | How |
| --- | --- | --- | --- | --- |
| `sanitize IN OUT` (`_run_sanitize`, around line 1272) | input unreadable | 2 | 4 | the `except (SanitizeError, FileExistsError, *_WORKBOOK_ERRORS)` returning 2 -> `except Exception as e: return _fail(e)` |
| | `OUT` exists without `--overwrite`, or is `IN` | 2 | 5 | `OutputRefusedError` (A2) |
| | unknown `--keep`, bad output extension | 2 | 2 | `SanitizeUsageError` (A3) |
| `prune WORKBOOK` (`_run_prune`) | unreadable | 2 | 4 | same pattern |
| | output exists, is the input | 2 | 5 | `OutputRefusedError` |
| | bad extension | 2 | 2 | `PruneUsageError` |
| `slice WORKBOOK` (`_run_slice`) | unreadable workbook, unknown dashboard | 2 | 4 | same pattern (`SliceError` maps to 4) |
| | `--strict` would drop something; the selection shows no worksheet; output refused | 2 | 5 | `SliceStrictError`, `SliceRefused`, `OutputRefusedError` |
| | `--write` and new integrity problems (nothing written) | 2 | 6 | `SliceIntegrityError` |
| | dry run that predicts the same | 2 | 6 | the dry-run branch after the report (`if report["dry_run"] and report["integrity_new"]: ... return 2`) -> `return ExitCode.INTEGRITY` (stderr text unchanged) |
| `rename` (`_run_rename`, around line 272) | workbook, reference or mapping unreadable or invalid | 1 | 4 | each `except ... return 1` -> `return _fail(e)`; the reference handler prints `cannot read reference workbook: {e}`: keep that prefix: `print(f"error: cannot read reference workbook: {e}")` then `return exit_code_for(e)` |
| | output exists, or is an input | 1 | 5 | `OutputRefusedError` |
| | `--cutoff` outside 0..1 | 1 | 2 | `UsageError` (A3, `rename.py:236`) |
| `scaffold make`, `show`, `apply` (`_run_scaffold`, around line 1177) | any error | 1 | 4 (output exists: 5) | the broad `except` -> `_fail(e)` |

Keep every printed message as it is. Only the return value changes.

`_run_sanitize` and `_run_prune`: read them before changing; they may raise `FileExistsError`-like refusals from the CLI itself (A2 converted those). `_run_slice`'s argparse checks (`--write needs -o`) stay usage errors (2) through `ap.error`.

## `docs/cli.md` rows to rewrite

`sanitize IN OUT`: 0 written; 2 unknown `--keep`, bad extension, usage; 3 crash; 4 input unreadable; 5 `OUT` exists without `--overwrite` or is `IN`.
`prune WORKBOOK`: 0 done, dry run or written; 2 bad extension, usage; 3; 4 unreadable; 5 output refused.
`slice WORKBOOK`: 0 done; 2 usage; 3; 4 unreadable workbook, unknown dashboard; 5 `--strict` would drop something, no worksheet in the selection, output refused; 6 the result has new integrity problems (with `--write` nothing is written; a dry run predicts it).
`rename WORKBOOK`: 0 done; 2 usage, `--cutoff` outside 0..1; 3; 4 workbook, reference or mapping unreadable or invalid; 5 output refused. Column 1 becomes `not used`.
`scaffold make`, `show`, `apply`: 0; 2; 3; 4 any error; 5 output exists.

## Tests (`tests/test_exit_codes.py` and module tests)

Update existing cases: `["sanitize", WENJIE, existing]` -> 5; `["prune", missing]` -> 4; `["slice", WENJIE, "-d", "nope"]` -> 4; `["rename", missing]` -> 4; `["scaffold", "make", WENJIE, "-d", "nope", ...]` -> 4.

Add one case per new code (plan WP6 acceptance):

- `sanitize`: unreadable 4; existing output 5; output is the input 5; `--keep nope` 2; output `x.csv` 2.
- `prune`: unreadable 4; output exists 5 (with `--write -o`); wrong extension 2.
- `slice`: unknown dashboard 4; `--strict` on a case that drops an action 5 (find it in `tests/test_slice.py`, search `strict`); `--write` with new integrity problems 6 and no output file; the same as a dry run 6 with the same stderr line (`the result has new integrity problems; --write would refuse it`). Find the integrity case in `tests/test_slice.py` (search `integrity_new`) or `tests/test_exit_codes.py` history (#165 added the dry-run case).
- `rename`: `--cutoff 2` -> 2; `--write-workbook existing.twb` -> 5 (check the option exists and how it names the output).
- `scaffold`: `apply` with an existing output -> 5 (read `_run_scaffold` for the option names).

Search the rest of `tests/` for assertions on these commands' codes (`grep -rn '"sanitize"\|"prune"\|"slice"\|"rename"\|"scaffold"' tests/*.py | grep '== [0-9]'`) and update them.

## Docs

- Per-command pages: `docs/sanitize.md`, `docs/prune.md`, `docs/slice.md` (the #138 dry-run paragraph), `docs/renaming.md`, `docs/scaffolds.md`: their exit-code lines.
- CLI help/description strings that state codes in `_run_sanitize`, `_run_prune`, `_run_slice`, `build_rename_arg_parser`, `build_scaffold_arg_parser` (search "exit").
- `AGENTS.md` rows for `slicer.py` ("block a write"), `prune.py`, `sanitize.py` if they state codes (search "exit").

## How to verify

```bash
PYTHONPATH=$PWD /home/claude-user/ai-sandbox/py-tbparse/.venv/bin/pytest -q tests/test_exit_codes.py tests/test_sanitize.py tests/test_prune.py tests/test_slice.py tests/test_rename.py tests/test_scaffold.py tests/test_cli.py
grep -rn "exit" docs/sanitize.md docs/prune.md docs/slice.md docs/renaming.md docs/scaffolds.md
```

then the whole non-browser suite.

## Not verifiable here

No Tableau involved; outputs do not change.

## Risks

- The `slice` dry-run code moves for the second time in two minors (0.5.5 made it 2, 0.6.0 makes it 6). The release note says so.
- `_run_rename` has five separate handlers; miss one and a code stays 1. The test per case catches it.

## Definition of done

Every row above returns its new code, docs and help say so, tests updated and added, whole non-browser suite and CI green, no version bump.
