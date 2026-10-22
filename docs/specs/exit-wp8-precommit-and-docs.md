# Spec A8: the pre-commit wrapper returns by precedence; one exit-code table; every doc page agrees

Track: 0.6.0 exit codes and errors. Plan: [plan-0.6.0-exit-codes-and-errors.md](../plan-0.6.0-exit-codes-and-errors.md), WP8, section 3 "The pre-commit wrapper" and section 4. Common rules: [README.md](README.md#common-rules-for-every-spec) (follow the agent rules file).

- Branch: `feat/exit-codes-precommit-docs`
- PR title: `Pre-commit wrapper returns the most important exit code; exit-code docs in one scheme (WP8)`
- PR body starts with: `Refs #127`. With this PR `main` has one scheme again; say so.
- Depends on: A5, A6, A7 merged. After it: A10 (release), and A9 if the owner wants it.

## Goal

1. `python -m py_tbparse.precommit` returns the code that comes first in the precedence list (3, 2, 4, 5, 6, 7, 1, 0) instead of `max`.
2. `docs/cli.md`'s table and prose describe one scheme; the rollout note goes; a test ties the table to `errors.ExitCode`.
3. Every page and help text that states an exit code agrees with the table; a grep test guards the old phrases.

## Owner decisions this builds on

Scheme adopted 2026-10-16, read as including the plan's precedence list for the wrapper (plan open question 4). If the owner says otherwise, `errors.PRECEDENCE` is the one place to change.

## Code (`py_tbparse/precommit.py`, 59 lines on `1130fa9`)

- Module docstring: "returns the worst exit code (0 to 3, ...)" -> "returns the most important exit code of the files, by the order 3, 2, 4, 5, 6, 7, 1, 0 (`errors.PRECEDENCE`); see docs/cli.md".
- `main()`: collect `rc` per file into a list and `return first_by_precedence(codes)` (from `py_tbparse.errors`, added in A1). Keep: no arguments -> 2 with the usage line; unknown hook command -> 2 (`build_argv` raises `UsageError` after A3; keep catching it as `except ValueError`, it is one); `SystemExit` from argparse -> `e.code if isinstance(e.code, int) else 2`; zero files -> 0; which arguments are files is unchanged.

`.pre-commit-hooks.yaml`: the comment "fails with the worst exit code (1 a finding at --fail-on, 2 unreadable file or bad option, 3 a rule crashed)" -> "fails when any file fails; the hook's exit code is the most important one (see docs/cli.md: 1 a finding at --fail-on, 2 a bad option, 3 a crash, 4 an unreadable file, 6 a broken relationship in validate)". This file is not `.md`, so the PR runs the full CI.

## Docs

`docs/cli.md`, section "Exit codes":

- Remove the rollout note added in A4. First paragraph: "Every command uses one scheme since 0.6.0:" followed by a small table `| Code | Name | Meaning |` with the eight rows of plan section 2 (names as in `ExitCode`: OK, FINDING, USAGE, CRASH, BAD_INPUT, REFUSED, INTEGRITY, PARTIAL). Then the per-command table (already in the new form after A5 to A7; re-read it whole and fix leftovers). Then "When several codes could apply, the first of 3, 2, 4, 5, 6, 7, 1, 0 wins." Then the `precommit` row: "the first code of that list over all files".
- Rewrite "What the codes mean, across the table" for the new scheme (short; the small table carries most of it).
- A short "Changed in 0.6.0" paragraph with the migration note of plan section 4 (the same text goes into the release notes in A10).

Other pages, checked against the table (plan WP8 list): `docs/ci.md`, `README.md` (search "exit"), `docs/api.md` (the `exit_code_for` bullet and any "until 0.6.0" sentence from A1), `docs/development.md` (rules for new errors and the message format rules of plan section 5, if A3 did not already add them; make it one section), `docs/prune.md`, `docs/slice.md`, `docs/sanitize.md`, `docs/sheet-copy.md`, `docs/dashboard-copy.md`, `docs/libraries.md`, `docs/styles.md`, `docs/diff-xml.md`, `docs/audit.md`, `docs/templates.md`, `docs/renaming.md`, `docs/scaffolds.md`. A5 to A7 changed most of them; this package reads all of them once more.

`AGENTS.md`: `precommit.py` row ("returns the worst exit code" -> "by precedence"), `errors.py` row (the scheme is complete), `ci_formats.py`, `template_check.py`, `template_drift.py`, `workbook_audit.py`, `xmldiff.py` rows if any still state old codes.

## Tests

`tests/test_precommit.py` (new; check first whether precommit tests exist elsewhere: `grep -rln precommit tests/`, `test_pre_push_hook.py` is about a git hook, not this):

- `test_precedence_over_files` (parametrised): monkeypatch `py_tbparse.precommit.cli_main` to return codes from a list per call; for files `a.twb b.twb` with code pairs `(0, 1) -> 1`, `(1, 7) -> 7`, `(4, 3) -> 3`, `(2, 4) -> 2`, `(6, 5) -> 5`, `(0, 0) -> 0`.
- `test_no_files_is_zero`, `test_no_arguments_is_two`, `test_unknown_hook_command_is_two`.
- `test_argparse_exit_counts_as_usage`: `cli_main` raising `SystemExit(2)` gives 2.

`tests/test_exit_codes.py`:

- `test_table_codes_match_the_enum`: the small code table in `docs/cli.md` has exactly the rows of `ExitCode` (number and name), and the per-command table header is `Command` plus `0` to `7`.
- `test_no_old_phrases_in_docs`: grep every `docs/*.md`, `README.md` and the CLI help (`cli.build_*_arg_parser().format_help()` for each builder, plus the descriptions inside `_run_audit`, `_run_slice`, `_run_diff_xml`, `_run_sheet`, `_run_dashboard`: run each command with `--help` through `cli.main` and capture stdout) for these phrases and fail on any: `exit code 2 if`, `or 2 for any error`, `2 when the workbook cannot be read`, `2: a file cannot be read`, `1 error or the run stopped`, `2 some sheet was refused`, `2 some dashboard was refused`, `not one scheme`, `returns the worst exit code`. Add any other old phrase you find while reading the pages.
- `test_every_row_has_a_case` stays and must still pass.

## How to verify

```bash
PYTHONPATH=$PWD /home/claude-user/ai-sandbox/py-tbparse/.venv/bin/pytest -q tests/test_precommit.py tests/test_exit_codes.py tests/test_api_doc.py tests/test_ci_formats.py
grep -rn "exit code\|exits [0-9]\|exit [0-9]" docs/*.md README.md | less      # read every hit once
```

then the whole non-browser suite. The hook file is YAML: `python -c "import yaml"` may not be installed; if not, check it by eye and say so (the repo never ran pre-commit itself: `docs/ci.md` says so).

## Not verifiable here

pre-commit itself is not run (the hook file was only ever parsed); real CI products reading the codes are not tested. Nothing involves Tableau.

## Risks

Missing a page: the grep test is the guard, and the reading pass in "Docs" is the second one.

## Definition of done

Wrapper by precedence with tests, `docs/cli.md` in one scheme with the enum test, every listed page checked, grep test in, whole non-browser suite and CI green, no version bump. After this merges, `main` is ready for A10.
