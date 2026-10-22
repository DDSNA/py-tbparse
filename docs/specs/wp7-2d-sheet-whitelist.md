# Spec B4: WP7-2d, the sheet whitelist (`sheet_defaults`, `--scope sheets`)

Track: WP7 slice 2. Plan: [wp7-style-plan-slice2.md](../wp7-style-plan-slice2.md) (sections 2 "Sheet level", 3 `sheet_defaults`, 4, 8 "WP7-2d", 11 Q3 and Q4). Common rules: [README.md](README.md#common-rules-for-every-spec) (follow the agent rules file).

- Branch: `feat/wp7-slice2-2d`
- PR title: `Style extract and apply: name-free sheet formats, only with --scope sheets (WP7-2d)`
- PR body starts with: `Refs roadmap card: Templates style templates slice 2 (WP7-2d)`
- Depends on: PR #213 (2b) merged. Doing B3 (2c) first is recommended, because both edit `_plan_formats` and `build_styled`; if 2c is not merged yet, rebase on it when it is. Written against #213's head `0ffa408` and `main` `1130fa9`: re-read `extract_style`, `_plan_formats`, `_unbuilt_wants`, `_NOT_BUILT` on your base before starting.

## Owner decisions

- 2026-10-16: build all of slice 2, so 2d ships (plan Q3 answered "yes"). The plan's other half of Q3, "`--scope sheets` is opt-in", is already how 2a and 2b work (the default scopes are `("workbook", "dashboards")`); keep it.

## BLOCKED (owner): title runs (plan Q4)

Sheet and dashboard title runs (`layout-options/title/formatted-text/run` with `fontname`, `fontsize`, `fontcolor`) hold most real fonts but sit beside text that may name fields. Plan default: **not** read or written in this slice. Build to the default (do not touch runs) and include `test_sheet_title_runs_untouched`, which pins it. If the owner says "copy run formatting", that is a later package. This question does not block the rest of the PR.

## Goal

1. `extract_style(..., scopes=(..., "sheets"))` reads name-free formats from every worksheet's `table/style/style-rule` into `sheet_defaults` (today it raises `StyleError("the sheets scope (sheet_defaults) is not available yet: it is work package WP7-2d")`).
2. `plan_style`/`build_styled`/`apply_style` with `"sheets"` in `scopes` write `sheet_defaults` into `table/style` of the selected worksheets (all, or `sheets=`/`--sheet NAME`, exact names of the target), under the same explicit/skip/force rules as 2b and 2c.

## The whitelist (already in `style.py`, from 2a)

`SHEET_ELEMENTS = ("header", "label", "title", "worksheet", "cell")`, `SHEET_ATTRS = FONT_ATTRS + ("background-color", "border-color", "border-style", "border-width", "text-align")`, `FORMAT_SCOPE_ATTRS = ("rows", "cols")`. `_check_formats` already validates `sheet_defaults` in a style file (check: `grep -n sheet_defaults py_tbparse/style.py`). Use these; do not add elements or attributes (the plan's whitelist test, `test_whitelist_matches_xsd`, checks them against the XSD).

## Extract

In `extract_style`, remove the `if "sheets" in scopes: raise ...` and add, for `"sheets"`:

- For each worksheet (`/workbook/worksheets/worksheet`), `_style_rules(ws.find("table/style"), SHEET_ELEMENTS, SHEET_ATTRS, f"sheet {name}", rep, store)`: it already skips `field=` formats (into `rep["field_skipped"]`), `_.fcp.*` and `encoding` children, and keys by `(element, attr, scope)`, so `rows` and `cols` are separate keys.
- Then `sheet_defaults = _rules_from(store, rep, "sheet ")` (modal value over all sheets; `mixed` lists keys with more than one value).
- Never read `table/panes/pane/style` (pane rules are out, plan section 2) or title runs.
- A `dashboard=` argument does not narrow sheets (it is a dashboard filter); say so in the docstring.
- Add `"sheet_defaults": <count of formats>` to `report["counts"]`.
- `make_style(..., sheet_defaults=...)`: check whether `make_style` already accepts it (2a reserved the section); if not, add the keyword.

## Plan and apply

Unit of change: `(sheet, element, attr, scope)` in the sheet's `table/style`.

- In `_plan_formats`, replace the `_unbuilt_wants` loop for `sheets` by real rows (after this package `_unbuilt_wants` and `_NOT_BUILT` can go entirely; remove them if nothing uses them).
- Rows: `scope` `sheets`, `target` the sheet name, `where` `_where(element, scope)`, `attr`, `current`, `new`; actions as in 2b (`add`, `same`, `skip`, `force`, `fail`). Look for existing formats with `ws.xpath("table/style/style-rule[@element=$e]/format[@attr=$a]")` filtered to no `field` and the same `scope` attribute (`""` when absent), like `_find_formats`.
- A format in the target with a `field=` for the same element and attr is **not** the same key (it is a different, field-bound format; plan rule 1): the new name-free format is `add`ed beside it. Pin it in a test.
- Writing: the sheet's `table/style` (the XSD `Workbook-VisualSpecification-G` puts `<style>` right after `<view>` and before `<panes>`, and requires it, so it normally exists; if it is missing, create it in that position). New `style-rule` after the last real `style-rule`; formats appended with `_add_child`; `force` sets `value` in place.
- `--sheet NAME` (repeatable) narrows the sheets; unknown names raise `StyleError` through `_check_names` (exists).
- Never touch: `field=` formats, `encoding`, `_.fcp.*`, `pane/style`, title runs, `datasource` styles.

## CLI

- `style extract --scope workbook,dashboards,sheets` now works (no new option).
- `style show --what formats --scope ...sheets`: `format_table` rows for `sheet_defaults` (check `_format_rows`; add the section if it does not list it).
- `style apply --scope sheets` and `--sheet NAME`: already parsed by #213; update the description ("sheet formats are written only with --scope sheets").
- Exit codes: as in 2b/2c, or the 0.6.0 scheme if A4 to A7 are merged on your base.

## Tests (plan WP7-2d list, in `tests/test_style_formats.py` for extract and `tests/test_style_apply.py` for apply)

Fixtures: `format-source.twb` has, on `Sheet 1`, a `header` rule (`font-weight bold`), a `label` rule with a `field=` format (`font-size 12`) and a `scope="cols"` format (`line-visibility off`, an attribute outside the whitelist), one pane style and one title run (read on `1130fa9`). `format-target.twb` and `format-bare.twb` have no sheet `style-rule`. Build targets with explicit sheet formats in the test from `format-bare.twb` text.

- `test_extract_sheet_defaults`: extracting `format-source.twb` with `scopes=("sheets",)` gives `sheet_defaults == [{"element": "header", "formats": [{"attr": "font-weight", "value": "bold"}]}]`; the `field=` format is in `report["field_skipped"]`; `line-visibility` is in `report["unsupported"]`.
- `test_sheet_field_formats_never_copied`: no `field` key can appear in `sheet_defaults`; applying never writes a `field` attribute.
- `test_scope_rows_cols_keyed_separately`: a target with `header/font-size` at `scope="rows"` and a style with the same attr without scope gives an `add` (different key), and with `scope="rows"` and another value gives `skip`.
- `test_pane_style_untouched`: `table/panes/pane/style` byte-equal before and after.
- `test_sheet_explicit_kept_force_replaces`: explicit `header font-weight normal` in the target: default `skip` (value stays), `force=True` replaces in place.
- `test_field_format_is_not_the_same_key_for_sheets`: a target `header` format with `field=` and the same attr: the name-free format is added beside it; the field-bound one is unchanged.
- `test_unknown_sheet_name_raises`: `sheets=["Nope"]` raises `StyleError` listing the sheet names.
- `test_sheet_title_runs_untouched`: `layout-options/title/formatted-text/run` of every sheet byte-equal before and after (pins the BLOCKED Q4 default).
- `test_sheets_scope_is_opt_in`: the default `plan_style` call has no `sheets` rows; `style apply` without `--scope` leaves `table/style` unchanged.
- `test_sheet_apply_schema`: apply onto `format-bare.twb` with `--scope sheets`: `new_schema_errors(before, after) == []`, `TwbParser` opens it.
- `test_self_apply_is_noop_for_sheets`: extract with sheets and apply onto the same workbook: only `same`/`skip` for sheets, equal tree.
- CLI: `style extract SRC --scope sheets -o x.style.json` writes `sheet_defaults`; `style apply x.style.json format-bare.twb --scope sheets --write -o out.twb` returns 0.
- Remove or update #213's tests that expect `sheets` rows to be `unsupported` (search `WP7-2d` in `tests/`).

## Docs

- `docs/styles.md` "Formatting": the sheet whitelist (elements and attributes, `rows`/`cols`), "only with `--scope sheets`", "field-bound formats, pane formats and title runs are never copied", "sheet-level formats may win over workbook formats in Tableau; not checked".
- `docs/cli.md`: `style extract` and `style apply` scopes.
- `docs/tableau-check.md`, `docs/verify-in-tableau.md`, `scripts/make_tableau_check_pack.py`: row **45** (sheet header and label fonts: `format.style.json` applied with `--scope sheets` to `format-bare.twb`; pass: the header text is bold in `Sheet 1`; fail: a dialog or no change). Update `tests/test_tableau_check_pack.py`.
- `AGENTS.md` `style.py` row: "2d: `sheet_defaults` read and written under `--scope sheets`; pane styles and title runs untouched".
- `docs/wp7-style-plan-slice2.md` status row; `docs/ROADMAP.md` B4 row.

## How to verify

```bash
PYTHONPATH=$PWD /home/claude-user/ai-sandbox/py-tbparse/.venv/bin/pytest -q tests/test_style_formats.py tests/test_style_apply.py tests/test_style.py tests/test_schema.py tests/test_tableau_check_pack.py tests/test_api_doc.py
```

then the whole non-browser suite. If the corpus is fetched: a manual loop `extract_style(wb, scopes=("sheets",))` over the 200 workbooks with `nice`, `timeout` and a log; report exceptions and the count of `field_skipped` (the plan expects about 40 percent of sheet rules to carry `field=`).

## Not verifiable without Tableau Desktop

Plan section 10 item 3: the merge order between workbook, sheet and zone rules, so whether a written sheet format shows. Pack row 45 is for the owner.

## Risks

- Sheet rules may override workbook fonts in Tableau, so 2b's workbook fonts may "do nothing" where sheets have their own; the docs must say "not checked" until rows 42 and 45 come back.
- Scope creep into field-bound formats: the whitelist test and the `field` tests guard it.

## Definition of done

Extract and apply of `sheet_defaults` under `--scope sheets`, tests above, pack row 45, docs, whole non-browser suite and CI green, no version bump.
