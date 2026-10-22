# Spec A9 (optional): the `webgui.py` `ValueError` sites get a category

Track: 0.6.0 exit codes and errors. Plan: [plan-0.6.0-exit-codes-and-errors.md](../plan-0.6.0-exit-codes-and-errors.md), WP9 and section 5 ("Sites in `webgui.py`"). Common rules: [README.md](README.md#common-rules-for-every-spec) (follow the agent rules file).

- Branch: `refactor/webgui-error-categories`
- PR title: `GUI server: request errors raise UsageError or InputError instead of a plain ValueError (WP9)`
- PR body starts with: `Refs #186`
- Depends on: A3 merged (the allow-list test exists). Independent of A4 to A8.

## BLOCKED (owner)

Plan open question 10: do this in 0.6.0, or leave the 40 `ValueError`s in `webgui.py` alone (the plan says it "can be dropped")? **Do not start until the owner answers yes.** No exit code depends on it; it is consistency only.

## Goal

The 40 `raise ValueError(...)` in `py_tbparse/webgui.py` (count on `1130fa9`; the plan counted 39) become `UsageError` (a malformed request: wrong type, missing key, out-of-range number, unknown option) or `InputError` (a file the user added is unusable: a library or palette upload that does not parse). The HTTP answers stay the same: status 400 and `{"error": str(e)}` with the same text.

## How

- List them: `grep -n 'raise ValueError(' py_tbparse/webgui.py`. Examples read on `1130fa9`: `_sty_page` "offset and limit must be whole numbers" (usage), `_style_export` "Tick at least one palette to export." (usage), "format: use style or tps" (usage), `_style_loaded` "Add a palette file first." (usage: a missing step, no file is unreadable), `_style_policy` "on_clash: use ..." (usage).
- Rule: `InputError` only when the message is about the content of an uploaded file; everything else is `UsageError`.
- The handlers catch `(ValueError, FileNotFoundError)` and answer 400 (for example `_style_post`); both new classes are `ValueError`, so no handler changes. Do not touch the handlers.
- Extend the A3 allow-list test (`tests/test_error_categories.py`): drop the `webgui.py` exclusion so that no `raise ValueError(` remains anywhere in `py_tbparse/` except the programmer-error allow-list.

## Tests

- The allow-list test above.
- `test_gui_errors_unchanged` (in `tests/test_webgui.py` or a new `tests/test_webgui_errors.py`): three routes that answer 400 today (for example `POST /style/export` with `select: []`, `GET /style/palettes?offset=x`, `POST /library/plan` without an upload; read `tests/test_webgui_styles.py` and `tests/test_webgui_libraries.py` for how they call the server) still answer 400 with the same message text.
- All `tests/test_webgui*.py` and `tests/test_server_mode.py` pass unchanged.

## Docs

`AGENTS.md` `errors.py` row: "no plain `ValueError` in the package except the allow-list".

## How to verify

```bash
grep -n 'raise ValueError(' py_tbparse/webgui.py      # none left
PYTHONPATH=$PWD /home/claude-user/ai-sandbox/py-tbparse/.venv/bin/pytest -q tests/test_error_categories.py tests/test_webgui*.py tests/test_server_mode.py
```

Browser tests are not needed (no page change); say they were not run.

## Not verifiable here

Nothing to check in Tableau.

## Risks

Low. A message changed by accident would show in the GUI; the route tests compare text.

## Definition of done

Only when the owner said yes: no plain `ValueError` in `webgui.py`, HTTP answers unchanged, tests green, CI green, no version bump.
