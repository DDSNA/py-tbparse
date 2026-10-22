# Spec A11: the library API default `on_clash` flips from `rename` to `fail`

Track: 0.6.0. Plan: [plan-0.6.0-clash-default.md](../plan-0.6.0-clash-default.md) (the flip-day checklist; read it whole, this spec adds the facts re-checked on `1130fa9` and the test details). Issue: #128. Common rules: [README.md](README.md#common-rules-for-every-spec) (follow the agent rules file).

- Branch: `feat/library-on-clash-fail`
- PR title: `Library API: on_clash defaults to fail, as the CLI and the GUI already do (#128)`
- PR body starts with: `Refs #128` (not "Closes": the plan says close #128 only after the owner approves; he has approved the style answer, so the owner closes it when 0.6.0 ships). Say "Breaking for Python callers (0.6.0)".
- Depends on: nothing. Any time before the 0.6.0 release (A10). Independent of A1 to A9.

## Owner decisions (do not reopen)

- The default of `on_clash` in `plan_import`, `build_imported_workbook` and `import_library` becomes `"fail"` in 0.6.0 (2026-10-16).
- Style keeps `fail` as its default and `replace` stays opt-in (plan option 1). No style code changes.

## Code (`py_tbparse/library.py` only; lines on `1130fa9`)

- Delete `class _NotPassed` (line ~636), `_NOT_PASSED` (~643) and `_resolve_on_clash` (~646, with its `TODO 0.6.0` comment).
- `plan_import` (~831), `build_imported_workbook` (~942), `import_library` (~971): signature `on_clash: str = "fail"`; delete the `on_clash = _resolve_on_clash(on_clash)` line in each (and in `import_library` the comment "here, so the warning points at the caller of import_library").
- Remove `import warnings` (line 23) if nothing else uses it: `grep -n 'warnings\.' py_tbparse/library.py` must be empty after the deletion.
- Remove `Union` / `_NotPassed` from the type hints; if `Union` is no longer used, drop it from the `typing` import.
- Docstrings: add "`on_clash` defaults to `\"fail\"`: the first clash raises `LibraryError` and nothing is written" to each of the three.
- Do **not** reorder `CLASH_POLICIES` (the plan calls it optional; it changes message texts that tests match). Leave it for a later PR if the owner wants it.

After A3, the clash raise is `LibraryClashError` (a `LibraryError`); if A3 is merged on your base, tests may match either; use `LibraryError` in assertions so the order of A3 and A11 does not matter.

## Tests

`tests/test_library.py`:

- Remove the file-level `pytestmark = pytest.mark.filterwarnings("ignore:on_clash was not passed:DeprecationWarning")` (line 29) and its comment.
- The 13 tests the plan lists fail under the new default because they call the API without `on_clash` on a target that clashes: `test_import_maps_fields`, `test_import_explicit_mapping`, `test_parameter_internal_clash`, `test_clash_rename`, `test_identical_under_other_name`, `test_parameter_roundtrip`, `test_table_calc_and_lod_preserved`, `test_ordering_field_follows_mapped_field`, `test_output_reparses`, `test_import_never_overwrites`, `test_twbx_members_copied`, `test_non_latin_names_and_caption_suffix`, `test_generated_calc_name_is_stable`. For each, read what it checks: if it is about renaming, pass `on_clash="rename"`; if it only needs a clean import, use a target without a clash (`target_noparams.twb` or a copy of the target with the clashing calculation removed) or pass `on_clash="rename"` with a comment saying why. The helper `built(parser, lib, **kw)` (line ~61) may take `on_clash="rename"` as its default keyword if most callers want it; say so in the PR. Run the file first with the flip in place to get the real failing list (the plan's list came from a simulation).
- Run it with `-W error::DeprecationWarning` once to prove no warning remains.

`tests/test_library_default_policy.py`: rewrite (its four warning tests fail by design). New content, fixtures `target.twb` and `source.twb` (they clash on "Profit Ratio"):

- `test_omitted_on_clash_fails` (parametrised over the three functions): `pytest.raises(LibraryError, match="on_clash='fail'")`; for `import_library` also assert the output path does not exist afterwards.
- `test_no_deprecation_warning_left`: under `warnings.simplefilter("error")`, an omitted call raises `LibraryError`, not a warning.
- `test_api_is_silent_when_on_clash_is_passed`: keep the existing parametrised test as it is (rename and skip work and are silent).
- `test_default_is_fail_in_every_entry_point`: the API default raises; `cli.main(["library", "import", target, lib])` returns non-zero and writes no file (assert `!= 0` and, if A7 is merged on your base, `== 5`, otherwise `== 1`; read `docs/cli.md` for the current code); `/library/plan` with no `on_clash` is blocked (reuse `tests/test_webgui_libraries.py::test_the_default_policy_is_fail_and_the_clash_report_is_whole` by calling its server fixture, or assert on the same endpoint in a few lines there).
- `test_signatures_default_to_fail`: `inspect.signature(f).parameters["on_clash"].default == "fail"` for the three, and `not hasattr(py_tbparse.library, "_resolve_on_clash")`.
- `test_style_defaults_stay_fail`: the same signature check for `style.plan_palette_import`, `style.build_with_palettes`, `style.import_palettes` (guards the owner's style decision).

Callers: `grep -rn "plan_import(\|build_imported_workbook(\|import_library(" py_tbparse scripts tests docs README.md`: every in-repo call that relies on the old default gets an explicit `on_clash`. Checked on `1130fa9`: every call passes it (`cli.py` lines ~954 and ~964, `webgui.py` ~1020, ~1025 and ~1054, `scripts/measure_writer_diffs.py` ~210 with `"rename"`); `sheetcopy.py` calls the private `_plan` with an explicit policy; `scripts/make_tableau_check_pack.py` goes through the CLI with `--on-clash rename`. Re-run the grep on your base for calls added since.

## Docs (plan checklist, re-checked)

- `docs/libraries.md` line 38: replace the sentences from "The Python functions (`plan_import`, ...) still default to `rename`" to the end of the bullet with: "The Python functions default to `fail` too (since 0.6.0; before, they renamed and warned). To list every clash without stopping, call `plan_import(..., on_clash=\"rename\")`, which is what the Libraries view does."
- `docs/cli.md` line 124: remove "The Python functions still default to `rename` and warn when `on_clash` is not passed; their default becomes `fail` in 0.6.0 ([libraries.md](libraries.md))."
- `docs/api.md`: in the library section, add "`on_clash` defaults to `\"fail\"`" to the `plan_import`, `build_imported_workbook` and `import_library` bullets.
- `docs/wp6-library-design.md` lines 116 to 119: `on_clash="fail"`, drop the "0.5.x ..." comment; line ~209 `[--on-clash rename|skip|fail]` -> `[--on-clash fail|skip|rename]`.
- `docs/styles.md` (around line 34): one sentence: "Style and library imports both default to `fail`; only style has `replace`."
- `AGENTS.md` `library.py` row: replace "Clash default: the public ... sentinel ... flips to `fail` in 0.6.0 (issue #128, owner 2026-10-08; ...)" with "`on_clash` defaults to `fail` in the API, the CLI and the GUI (#128, owner 2026-10-16)".
- `README.md`: nothing states the API default (plan checked it); leave it.
- `docs/template-roadmap-plan.md` line ~271: history, leave it.

## How to verify

```bash
PYTHONPATH=$PWD /home/claude-user/ai-sandbox/py-tbparse/.venv/bin/pytest -q -W error::DeprecationWarning tests/test_library.py tests/test_library_default_policy.py
PYTHONPATH=$PWD /home/claude-user/ai-sandbox/py-tbparse/.venv/bin/pytest -q tests/test_pathlike.py tests/test_webgui_libraries.py tests/test_webgui_styles.py tests/test_webgui_copy.py tests/test_sheetcopy.py tests/test_api_doc.py tests/test_tableau_check_pack.py
```

then the whole non-browser suite. `tests/test_corpus.py` passes `on_clash` explicitly (plan); run it only if the corpus is fetched, and say whether it ran. `tests/test_gui_libraries.py` (Chromium) is not needed: the GUI default does not change; say it was not run.

## Not verifiable here

Nothing to check in Tableau: no output changes for any caller that passes `on_clash`.

## Risks

- A test that passes `rename` blindly hides what it was meant to check: read each one.
- Third-party code calling the API without `on_clash` breaks at 0.6.0; the release note (A10) says how to fix it.

## Definition of done

Sentinel and warning gone, three signatures default to `"fail"`, tests rewritten and green with `-W error::DeprecationWarning`, docs and `AGENTS.md` updated, CI green, no version bump.
