# Spec A5: exit codes of the check commands (`validate`, `audit`, `template check`, `template drift`, `diff-xml`, `style check`)

Track: 0.6.0 exit codes and errors. Plan: [plan-0.6.0-exit-codes-and-errors.md](../plan-0.6.0-exit-codes-and-errors.md), WP5 and the rows of section 3. Common rules: [README.md](README.md#common-rules-for-every-spec) (follow the agent rules file).

- Branch: `feat/exit-codes-checks`
- PR title: `Exit codes of validate, audit, template check and drift, diff-xml and style check follow the 0.6.0 scheme (WP5)`
- PR body starts with: `Refs #127`. Say "Breaking (0.6.0)" and list the changed codes.
- Depends on: A4 merged. Can run beside A6 and A7.

## Owner decisions this builds on

The scheme of the plan, adopted 2026-10-16. Read here as including the plan's choice that `validate` with a broken relationship is **6** (integrity), not 1. If the owner says otherwise before you start, it is one constant (`ExitCode.INTEGRITY` -> `ExitCode.FINDING`) and the matching test rows.

## Changes (from plan section 3)

| Command | Case | Old | New | Where in `cli.py` (main at `1130fa9`) |
| --- | --- | --- | --- | --- |
| `WORKBOOK validate` | a relationship is broken, any `--format` | 2 | 6 | `_main` (was `main`): `return 0 if result["ok"] else 2` -> `ExitCode.INTEGRITY`. Also fix the comment above the CI-format branch ("the exit code stays the one of the plain formats: 0, or 2 ...") |
| `audit` | workbook cannot be read | 2 | 4 | `_run_audit`: `except _WORKBOOK_ERRORS as e: ... return 2` -> `return _fail(e)` |
| `audit` | bad `--only`/`--skip` | 2 | 2 | same handler: after A3 these raise `UsageError`, so `_fail` gives 2. Check that `_ids()` (around line 677) raises `UsageError` (A3 table: `cli.py:684`) |
| `audit` | rule crashed / finding / none | 3 / 1 / 0 | same | unchanged |
| `template check` | template unreadable (not a `.twbx` template, malformed manifest) | 2 | 4 | `_run_template_check` (around line 688): the `except (FileNotFoundError, ValueError, OSError, zipfile.BadZipFile, json.JSONDecodeError, etree.XMLSyntaxError)` returning 2 -> `except Exception as e: return _fail(e)` |
| `template check` | bad `--only`/`--skip` | 2 | 2 | through `_fail` (UsageError) |
| `template drift` | template, answers or data unreadable; no file matches | 2 | 4 | `_run_template_drift` (around line 705), same change. "No file matches": find where it is raised (`template_drift.py` or `multifile.py`); it must be an `InputError` (or a feature error that maps to 4). If it is a plain `ValueError` A3 missed, classify it. |
| `diff-xml` | a file cannot be read | 2 | 4 | `_run_diff_xml`: `except _WORKBOOK_ERRORS` -> `_fail(e)` |
| `diff-xml` | `-o` names one of the inputs | 2 | 5 | `_run_diff_xml`: the inline print + `return 2` -> `return _fail(OutputRefusedError("--output is one of the workbooks; refusing to overwrite it"))` (same text) |
| `style check` | a file that cannot be read | 1 | 4 | see below |
| `style check` | a problem found | 1 | 1 | unchanged |

`style check`: `_run_style`'s `check` branch calls `style.check_style_file(path)`, which returns a list of problem strings and never raises: a missing file gives `"file not found: ..."`, a `StyleError` from `load_style` or `_collect` is returned as text (`style.py`, `check_style_file`). To give 4 for "cannot be read" without changing the function's public contract:

- Add a keyword-only parameter `check_style_file(path, *, raise_unreadable: bool = False)`. With `True`, a missing file raises `InputError(f"file not found: {path}")`, a file that is not JSON/XML or not a style/`.tps` file raises the `StyleError` it caught (re-raise), and a wrong extension raises `StyleUsageError` from A3 (`expected a .tps or .style.json file, got ...`; it is knowable without opening the file, so 2). Problems **inside** a readable file stay list entries.
  **Check first:** read `load_style` and `_check_style`: a file that is valid JSON but breaks the style schema raises `StyleError` too. Decide per `raise` whether it is "unreadable" or "a problem found": JSON that does not parse = unreadable (4); a schema violation in a parsed file = a problem (1). If `load_style` cannot tell them apart, add the distinction there (catch `json.JSONDecodeError` separately) and say so in the PR.
- The CLI passes `raise_unreadable=True` and lets the exception reach `_fail` (catch it in the existing `except` and `return _fail(e)`).
- The GUI and other callers keep calling it without the flag (no change for them).

CI formats (`junit`, `sarif`, `github`) are not changed. Their tests assert the code with `--format`.

## `docs/cli.md` table rows to rewrite (eight code columns since A4)

`WORKBOOK validate`: 0 all resolve; 2 usage; 3 crash; 4 cannot be loaded; 6 a relationship refers to a table or field the workbook lacks; others `not used`.
`audit WORKBOOK`, `template check TEMPLATE`, `template drift TEMPLATE FILES`: 0, 1 finding at `--fail-on`, 2 bad `--only`/`--skip` or usage, 3 rule crashed or unexpected error, 4 cannot be read (drift: or no file matches).
`diff-xml A B`: 0 same, 1 differ, 2 usage, 3 crash, 4 cannot be read, 5 `-o` is an input.
`style show`, `extract`, `check` row: split it into two rows if that is clearer (`style check FILE` on its own; then add it to `tests/test_exit_codes.py`'s cases): `check` 0 no problem, 1 a problem found, 2 usage or wrong file type, 4 cannot be read.

## Tests (`tests/test_exit_codes.py` and neighbours)

- Update cases: `["audit", missing]` -> 4; `["template", "check", WENJIE]` -> 4; `["template", "drift", TEMPLATE, missing]` -> 4; `["diff-xml", WENJIE, missing]` -> 4; `test_validate_broken_relationship_is_2` becomes `..._is_6` (both plain and `--format junit`), reading the cell in column 6.
- Add: `["audit", WENJIE, "--only", "Z999"]` -> 2; `["audit", WENJIE, "--only", " "]` -> 2; `["diff-xml", WENJIE, WENJIE, "-o", WENJIE]` -> 5 (and the file is unchanged: compare bytes before and after); `["style", "check", str(tmp_path / "none.style.json")]` -> 4; `["style", "check", str(STYLE / "bad.tps")]` stays 1 (a problem in a readable file: check this fixture is readable XML; if `bad.tps` is unparsable, use `bad-format.style.json` for the 1 case and `bad.tps` for 4, and say which is which in the test name).
- `tests/test_ci_formats.py`: one test that a broken `validate` returns 6 for each of `junit`, `sarif`, `github` (monkeypatch `TwbParser.validate` as `test_exit_codes.py` does).
- `--fail-on never` still returns 0 for a finding and 3 for a crash (`crash_after` helper exists in `test_exit_codes.py`).
- `tests/test_style.py`: `check_style_file(missing)` without the flag still returns `["file not found: ..."]` (public contract unchanged); with the flag it raises `InputError`.

## Docs

- `docs/ci.md`: the exit-code lines for `validate`, `audit`, `template check` (search "exit"); the sentence "exit 3 if py-tbparse itself failed" stays true. Users copy from this page: update it in this package (plan risk).
- `docs/audit.md`, `docs/templates.md` (check and drift sections), `docs/diff-xml.md` (the "Exit code 0 ... 2" line), `docs/styles.md` (`check`): change the code lines for these commands.
- CLI help texts that state codes: `_run_audit`'s description ("2 when the workbook cannot be read or an option is wrong"), `_run_diff_xml`'s description ("2: a file cannot be read"), the `template check`/`drift` help (search `build_template_arg_parser` for "exit"), `template_check.py`/`template_drift.py` docstrings and `AGENTS.md` rows for `template_check.py`, `template_drift.py`, `ci_formats.py` (`validate` "exit codes (0, 1 unreadable, 2 broken) are unchanged"), `xmldiff.py` ("exit 0 same, 1 different, 2 unreadable").

## How to verify

```bash
PYTHONPATH=$PWD /home/claude-user/ai-sandbox/py-tbparse/.venv/bin/pytest -q tests/test_exit_codes.py tests/test_ci_formats.py tests/test_audit.py tests/test_template_check.py tests/test_template_drift.py tests/test_xmldiff.py tests/test_style.py tests/test_cli.py
grep -rn "exit code\|exit [0-9]\|exits [0-9]" docs/ci.md docs/audit.md docs/diff-xml.md docs/styles.md docs/templates.md
```

then the whole non-browser suite.

## Not verifiable here

No Tableau involved. How GitHub code scanning or a real CI product treats exit 6 for `validate` is not tested; the SARIF and JUnit content does not change.

## Risks

- `docs/ci.md` is what users copy; a stale line there is the worst miss.
- `style check` contract: keep the default behaviour of `check_style_file` exactly; only the CLI uses the flag.

## Definition of done

The rows above return the new codes, docs and help texts for these commands say the new codes, tests updated and added, whole non-browser suite and CI green, no version bump.
