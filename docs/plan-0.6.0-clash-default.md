# Plan: the library API default for `on_clash` becomes `fail` in 0.6.0

Issue #128. The owner confirmed on 2026-10-16 that the default of `on_clash` in `plan_import`, `build_imported_workbook` and `import_library` flips from `rename` to `fail` in 0.6.0. The `DeprecationWarning` that announces it shipped in 0.5.5. This page is the checklist for the flip PR. It changes no code. Every claim below was checked against the code on `main` at 1fa6acd (the repo is at 0.5.6), not taken from the issue.

## What is true today

| Entry point | Default today | Where |
| --- | --- | --- |
| Library API (`plan_import`, `build_imported_workbook`, `import_library`) | `rename`, plus a `DeprecationWarning` when `on_clash` is not passed | `py_tbparse/library.py`, `_resolve_on_clash` (the three signatures use the `_NOT_PASSED` sentinel) |
| `library import` (CLI) | `fail` | `cli.py`, `--on-clash`, `default="fail"` |
| Libraries view (GUI) | `fail` | `webgui.py` `_library_plan` and `_library_add` (`payload.get("on_clash", "fail")`); `webui/libraries.js` `policy = 'fail'` |
| `sheet copy`, `dashboard copy` (API, CLI, GUI) | `fail` | `sheetcopy.py`, `dashboardcopy.py`, `cli.py`, `webgui.py` `_cpy_policy`, `webui/copy.js` |
| `style` (API, CLI, GUI) | `fail` | `style.py` (`plan_palette_import`, `build_with_palettes`, `import_palettes`, `build_export`, `export_palettes`), `cli.py` (`clash` dict), `webgui.py` `_style_policy`, `webui/styles.js` |

So the library API is the only entry point that disagrees. `library.CLASH_POLICIES` is `("rename", "skip", "fail")`; `style.CLASH_POLICIES` is `("fail", "skip", "rename", "replace")`.

## The style `replace` question

The issue says "styles have a fourth policy, `replace`" and notes it as open. What the code shows: `replace` exists only in style, and it is never the default anywhere (API, CLI and GUI all default to `fail`; `tests/test_webgui_styles.py::test_the_default_policy_is_fail_and_every_clash_is_listed` pins the GUI). So there is no default to flip for style. The open question is only whether style should keep `fail` as its default or default to `replace`, because `replace` is the usual wish for "a new version of our palette" (`docs/styles.md` already says so).

Options:

1. Keep `fail` for style, `replace` stays opt-in. No code change on flip day. One sentence in `docs/styles.md` that style and library agree on the default and only style has `replace`.
2. Default style to `replace`. Matches the common case, but it overwrites a palette in the target without asking, and it would be the one entry point that defaults to a destructive policy. It also breaks the "same default everywhere" rule that #128 exists for.
3. Default to `replace` only when the incoming palette has the same name and a different colour list, and `fail` otherwise. That is `replace` with extra steps, and hard to explain.

Recommendation: option 1. Reasons: it needs no change, a silent overwrite of a colour palette is the harm to avoid, and `fail` already lists every clash and names `--on-clash replace` in its message (`style.py` around line 483), so the user is told what to type. Ask the owner to confirm before the flip PR merges, as this is a policy choice (via the interactive question tool, per the standing rule).

## Exact behaviour after the flip

Library API:

- `on_clash` not passed means `"fail"`. No `DeprecationWarning` any more (nothing is warned for a default that is now the safe one).
- The three signatures read `on_clash: str = "fail"`. `"rename"` and `"skip"` behave exactly as now.
- With a clash: `plan_import` raises `LibraryError("'<caption>' is already in the target datasource (on_clash='fail')")`; `build_imported_workbook` raises the same; `import_library` raises it before the output is created (no file is written). Unmapped or circular entries raise as now.
- A caller who wants a table of all clashes without raising uses `plan_import(..., on_clash="rename")`, which is what the GUI does internally to show a whole report. Say this in `docs/libraries.md`.
- A bad value still raises `LibraryError("on_clash must be one of ...")`.

CLI: no change. `library import` already defaults to `fail`; exit code 1 on a clash. Only the help text and docs that mention the API difference are edited.

GUI: no change. The Libraries view already defaults to `Stop` (`fail`) and `/library/plan` and `/library/add` already default the payload to `fail`. The one place that still says `rename` there is the internal re-plan in `_library_plan` to list every clash; it passes `on_clash` explicitly, so it is correct and stays.

Style: no change (see above). Sheet copy and dashboard copy: no change.

## Flip-day checklist

Code (`py_tbparse/library.py` only):

- [ ] Delete `_NotPassed`, `_NOT_PASSED` and `_resolve_on_clash` (with the `TODO 0.6.0` comment).
- [ ] `plan_import`, `build_imported_workbook`, `import_library`: `on_clash: str = "fail"`; remove the three `on_clash = _resolve_on_clash(on_clash)` lines (and the "here, so the warning points at the caller" comment in `import_library`).
- [ ] Remove `import warnings` if nothing else in the file uses it (checked: only `_resolve_on_clash` does).
- [ ] Docstrings: `plan_import` already says it raises for `fail`; add the default to the first line of each of the three.
- [ ] Optional: reorder `CLASH_POLICIES` to `("fail", "skip", "rename")` so `--help` and error messages list the default first. Check `tests/test_cli.py` and `tests/test_library.py` for the message text first.

Tests:

- [ ] `tests/test_library.py`: remove the file-level `pytestmark = filterwarnings("ignore:on_clash was not passed...")` (line 29) and its comment. With the default simulated as `fail`, 13 tests in this file fail because they call the API without `on_clash` against a target that has a clash: `test_import_maps_fields`, `test_import_explicit_mapping`, `test_parameter_internal_clash`, `test_clash_rename`, `test_identical_under_other_name`, `test_parameter_roundtrip`, `test_table_calc_and_lod_preserved`, `test_ordering_field_follows_mapped_field`, `test_output_reparses`, `test_import_never_overwrites`, `test_twbx_members_copied`, `test_non_latin_names_and_caption_suffix`, `test_generated_calc_name_is_stable`. Each one that means "rename" gets `on_clash="rename"` (the helper `built(...)` at line 61 can take it as a default keyword); a test that only needs a clean import should use a target without a clash instead. Do not pass `rename` blindly: read what the test checks.
- [ ] `tests/test_library_default_policy.py`: rewrite (see "Acceptance tests"). The four tests that assert the warning and "omitted still means rename" fail after the flip by design.
- [ ] Already passing under a simulated `fail` default, no change needed: `tests/test_pathlike.py`, `tests/test_corpus.py` (both pass `on_clash` explicitly), `tests/test_webgui_libraries.py`.
- [ ] Any new in-repo caller found by `grep -rn "plan_import(\|build_imported_workbook(\|import_library(" py_tbparse scripts tests docs README.md` that does not pass `on_clash`. Today `cli.py` and `webgui.py` pass it; `sheetcopy.py` calls the private `_lib._plan` with an explicit policy.

Docs:

- [ ] `docs/libraries.md` (the `add-renamed` or `skip-clash` bullet, line 38): drop the "Python functions still default to `rename` ... DeprecationWarning" sentences; say all entry points default to `fail` and that the Python default changed in 0.6.0. Add the one-line tip about `plan_import(..., on_clash="rename")` for a full clash list. Examples at lines 53 and 55 already pass `on_clash`; keep them.
- [ ] `docs/cli.md` line 124: remove "The Python functions still default to `rename` and warn ...; their default becomes `fail` in 0.6.0".
- [ ] `docs/api.md` (library section, lines 136 to 138): add "`on_clash` defaults to `"fail"`" to `plan_import`, `build_imported_workbook`, `import_library`.
- [ ] `docs/wp6-library-design.md` lines 116 to 119: signatures show `on_clash="rename"` with a "0.5.x" note; change to `"fail"` and drop the note. Line 209 (`[--on-clash rename|skip|fail]`) lists the default first as `rename`; reorder.
- [ ] `docs/styles.md` line 34: add the sentence from option 1 (if the owner agrees).
- [ ] `AGENTS.md` module table, `library.py` row (line 286): replace "Clash default: ... sentinel ... DeprecationWarning ... flips to `fail` in 0.6.0 ..." with the new fact (`on_clash="fail"` everywhere). Note the row says "owner 2026-10-08" while the issue says 2026-10-16; keep the later date.
- [ ] `README.md`: nothing says the API default today (checked the Libraries and library bullets); add a "Changed" note only through the release notes below. If the README gains a Python library example, it must pass `on_clash`.
- [ ] `docs/template-roadmap-plan.md` line 271 is a planning-era signature (history); leave it.
- [ ] There is no CHANGELOG file in the repo. Release notes live in the GitHub release and follow the "Release notes" rule in `AGENTS.md` (Added / Changed / Fixed, short, for CLI and GUI users).

Release:

- [ ] Version bump to 0.6.0 is the release PR's job, not the flip PR's (no bump in the branch unless the owner says).
- [ ] Release notes (below). Mention under what is not verified that nothing here was opened in Tableau Desktop.
- [ ] Close #128 from the flip PR with "Closes #128" only after the owner approves the style answer.

## Keeping the DeprecationWarning path testable until the flip

Nothing changes now; the path is already covered by `tests/test_library_default_policy.py` (a warning per function, once, pointing at the caller's file; silent when `on_clash` is passed; omitted still equals `rename`; CLI and GUI paths silent). Rules until 0.6.0:

- Keep `_NOT_PASSED` and `_resolve_on_clash` untouched. Any new public library function that takes `on_clash` must use the same sentinel and the same helper, with a test in that file.
- New tests that call the three functions should pass `on_clash` explicitly. Only `tests/test_library.py` keeps its file-level ignore, and that file should not get new omitted-`on_clash` calls.
- Suggested tripwire (a separate small PR, not this one): a test that reads the version from `pyproject.toml` and, once it is 0.6.0 or higher, fails if `_resolve_on_clash` still exists. It stops the flip from being forgotten at release time.
- A cheap way to rehearse the flip before it happens, used for this plan: run the library tests with a plugin that makes the omitted default return `"fail"`, from outside the repo, and compare the failures with the list above. The count was 17 failures (13 in `tests/test_library.py`, 4 in `tests/test_library_default_policy.py`).

## Release-note wording (draft)

Changed (breaking for Python callers):

> **Library API: `on_clash` now defaults to `fail`.** `plan_import`, `build_imported_workbook` and `import_library` used to rename a clashing calculation or parameter when you did not pass `on_clash` (and warned since 0.5.5). They now stop with a `LibraryError` on the first name clash and write nothing, as `library import`, the Libraries view, sheet copy, dashboard copy and style import already did. If your code relied on the old behaviour, pass `on_clash="rename"` (or `"skip"`). The command line and the GUI are unchanged. Issue #128.

## Acceptance tests

Rewrite `tests/test_library_default_policy.py` to say:

1. For each of `plan_import`, `build_imported_workbook`, `import_library` against the `target.twb` / `source.twb` fixtures (which clash on "Profit Ratio"): omitted `on_clash` raises `LibraryError` matching `on_clash='fail'`, and `import_library` leaves no output file.
2. Under `warnings.simplefilter("error")`, the omitted call raises `LibraryError`, not a warning (no `DeprecationWarning` remains).
3. `on_clash="rename"` and `"skip"` still work and are silent (keep the existing parametrised test).
4. Agreement test, as the issue asks: for the same fixtures, the API default, `cli.main(["library", "import", ...])` (exit 1, no file) and the GUI `/library/plan` with no `on_clash` (blocked) all fail on the same clash. The CLI and GUI halves can reuse `tests/test_webgui_libraries.py::test_the_default_policy_is_fail_and_the_clash_report_is_whole`.
5. `inspect.signature` of the three functions has `on_clash` default `"fail"`, and `py_tbparse.library` has no `_resolve_on_clash` (guards against a half-done flip).
6. Style stays on `fail`: `inspect.signature` of `plan_palette_import`, `build_with_palettes`, `import_palettes` has default `"fail"` (guards the recommendation; change this test if the owner picks option 2 or 3).
7. Existing tests still pass: `tests/test_library.py` (after the edits above, with the ignore removed and run with `-W error::DeprecationWarning`), `tests/test_pathlike.py`, `tests/test_corpus.py`, `tests/test_webgui_libraries.py`, `tests/test_webgui_styles.py`, `tests/test_webgui_copy.py`. Run them the CI way: `scripts/ci-like-tests.sh`.

Not covered here: the GUI browser tests (`tests/test_gui_libraries.py`) need Chromium; the GUI default does not change, so they should be unaffected, but they were not run for this plan.
