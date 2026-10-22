# Spec B3: WP7-2c, dashboard defaults by zone role (`style apply --scope dashboards`)

Track: WP7 slice 2. Plan: [wp7-style-plan-slice2.md](../wp7-style-plan-slice2.md) (sections 3, 4, 8 "WP7-2c", 9, 10). Read sections 3 and 4 whole before starting. Common rules: [README.md](README.md#common-rules-for-every-spec) (follow the agent rules file).

- Branch: `feat/wp7-slice2-2c`
- PR title: `Style apply: dashboard background, borders, margins and title by zone role (WP7-2c)`
- PR body starts with: `Refs roadmap card: Templates style templates slice 2 (WP7-2c)` (the form #213 used).
- Depends on: **PR #213 (WP7-2b) merged.** This spec was written against #213's head `0ffa408` (branch `feat/wp7-slice2-2b`). If #213 changed after that commit, re-read `plan_style`, `_plan_formats`, `_write_workbook_rows`, `_add_child`, `_fill_format_report` and `tests/test_style_apply.py` on `main` before you start, and adapt the names below. Next: B4 (2d), then B5 (2e).

## BLOCKED (owner): what counts as explicit (plan Q2)

The plan's default, which #213 already uses for workbook rules: **any `<format>` present in the target for a key is explicit**, whatever its value, including Tableau's boilerplate (`margin 4`, `border-style none`, `border-width 0`); a default run skips it and `--force` replaces it. The alternative is a short list of boilerplate values that count as "default-looking" and are overwritten without `--force`. For dashboards this matters most: most corpus zones carry Tableau's defaults, so a default restyle will skip most margins and borders.

Build the plan default (it is the same rule #213 has, so the code stays one rule). Write the "boilerplate kept" count into the report as below so the owner can judge it. Say in the PR body that the merge waits for the owner's answer to Q2; if he picks the alternative, it is a follow-up change to `_plan_formats`, not to this design.

## Goal

`plan_style`, `build_styled` and `apply_style` (and `py-tbparse style apply`) write the `dashboard` section of a style file onto a copy of the target:

- `dashboard.roles` (`root`, `container`, `sheet`, `title`), each a map `{attr: value}` over the six `ROLE_ATTRS` (`background-color`, `border-color`, `border-style`, `border-width`, `margin`, `padding`), onto the `zone-style` of every zone of that role in each selected dashboard's **main** layout;
- `dashboard.background` as `background-color` on the `root` role only;
- `dashboard.rules` (`dash-title`, `dash-subtitle`, `dash-text`) into each selected dashboard's own `<style>`.

Today (#213) every dashboards row is `unsupported` with the reason "writing dashboards formatting is not built yet (WP7-2c)" (`_unbuilt_wants` and `_NOT_BUILT` in `style.py`). This package replaces that for the `dashboards` scope; `sheets` stays unsupported until B4.

## Code (`py_tbparse/style.py`)

`style.py` is about 1460 lines after #213. The plan says to split the format half into `styleformat.py` when it becomes too big to read. **Do not split in this package** (it would mix a move with new logic and make the review hard); say in the PR that the split is due, and propose it as its own PR after 2e.

Reuse, do not duplicate:

- `_zone_role(z, parent_is_zones)` (already in `style.py`, from 2a): `root` for a `layout-basic`/`layout-flow` zone directly under `<zones>`, `container` for any other such zone, `sheet`, `title`, else `None`. It calls `dashboards.zone_kind`. Never use `z.get("type-v2")` (`AGENTS.md`).
- `_same_value`, `_where`, `_check_names` (dashboard names; already validates `--dashboard`), `_add_child` (keeps indentation), `_fill_format_report`, `FORMAT_ACTIONS`, `STYLE_PLAN_COLUMNS`.
- The walk over zones in `extract_style` (stack of `(zone, top)` from `db.find("zones")`) is the shape to copy, so extract and apply agree on which zone has which role.

New private helpers (names are this spec's choice):

```python
def _dashboard_wants(style: dict) -> tuple[list[tuple], list[tuple]]:
    """(role, attr, value) from `background` and `roles`, and (element, attr, scope, value) from `rules`."""

def _dashboard_rows(doc, style: dict, dashboards, force: bool, on_clash: str) -> list[dict]:
    """One plan row per (dashboard, zone, attr) for roles and per (dashboard, element, attr, scope) for rules."""

def _ensure_dashboard_style(db):
    """The dashboard's own <style>, created at the XSD position (after layout-options or repository-location,
    before <size>; see DashboardDoc-G in tests/schemas/twb_2026.2.0.xsd)."""

def _ensure_zone_style(zone):
    """The zone's <zone-style>, created as the LAST child of the zone (XSD Zone-G)."""

def _write_dashboard_rows(doc, rows: list[dict]) -> None:
```

In `_plan_formats`: when `"dashboards" in scopes`, call `_dashboard_rows` instead of the `_unbuilt_wants` loop for that scope; keep `_unbuilt_wants` for `sheets`. Remove `"dashboards"` from `_NOT_BUILT`. In `build_styled`: call `_write_dashboard_rows(doc, rows)` after `_write_workbook_rows`.

### Rows (plan section 4; the unit is `(dashboard, zone, attr)` for zones)

For each selected dashboard (all dashboards of the target, or those named by `dashboards=`/`--dashboard`, exact and case-sensitive; an unknown name already raises `StyleError` through `_check_names`):

- Walk the main layout's zones (`db.find("zones")`; never `devicelayouts`). For each zone with a role that the style names, and each attr of that role (for `root`, also `background-color` from `dashboard.background`):
  - `target` column: the dashboard name; `where`: `"<role> zone <id>"` (for example `sheet zone 3`); `attr`, `current`, `new`.
  - Look for `zone-style/format[@attr=attr]` without `field` (zones' formats have no `field` in the corpus, but skip any that has one): none -> `add`; same value (`_same_value`) -> `same`; other value -> `force` with `force=True`, `fail` under `on_clash="fail"`, else `skip`, reason "the zone already sets this format; kept (--force replaces it)".
- A role the style names that has no zone in a dashboard -> one row `no-target`, `where` `"<role>"`, reason "no <role> zone in this dashboard" (plan: a dashboard without a title zone).
- A dashboard without `<zones>`, a storyboard dashboard, or one whose zones are all without roles: one `no-target` row per named role with a reason that says why; never an exception (plan test `test_roles_classified`: "floating and storyboard dashboards report rather than crash").
- Rules (`dashboard.rules`): key `(dashboard, element, attr, scope)` in the dashboard's own `<style>`; same add/same/skip/force/fail logic as `_find_formats` does for the workbook, but on `db.xpath("style/style-rule[@element=$e]/format[@attr=$a]")`.

Report: `_fill_format_report` already counts per scope. Add one key to the report dict (not to `counts`, so #213's tests keep their shape): `report["boilerplate_kept"]`: the number of `skip` rows whose `current` value is one of `margin 4`, `border-style none`, `border-width 0`, `padding 0` (the values the plan names as Tableau's habit). Print it in the CLI after the counts: "N of the kept formats are values Tableau writes by default (margin 4, no border); --force replaces them". This is information only; it does not change any action (Q2 is BLOCKED).

### Writing

- `add` for a zone: `_ensure_zone_style(zone)` then append `<format attr=... value=.../>` with `_add_child` (new formats at the end of the `zone-style`).
- `force` for a zone: set `value` on the existing `<format>` in place (position and other attributes kept), as `_write_workbook_rows` does.
- Rules: `_ensure_dashboard_style(db)`, then the same rule placement as the workbook `<style>` (a new `style-rule` goes after the last real `style-rule`; formats appended).
- Never touch: zones without a named role (filter, legend, text, bitmap, web, paramctrl, empty), `devicelayouts` and everything under it, `_.fcp.*` elements and attributes, the order of existing elements.

`_ensure_dashboard_style` position, from the XSD (`DashboardDoc-G`, read while writing this spec): children of `<dashboard>` are, in order, `layout-options` or `repository-location` (group `Dashboard-VizLayoutOptionsOrRepositoryLocation-G`), then optional `<style>`, then `<size>` (group `Dashboard-DashboardSizeOptions-G`), then datasources and dependencies, `<zones>`, optional `<devicelayouts>`, then the identifier. If the dashboard already has a `<style>` (even an empty one, as in `format-bare.twb`) return it and create nothing. Otherwise insert the new `<style>` right before the first child that belongs after it (`size`, `datasources`, `datasource-dependencies`, `zones`, `devicelayouts`, `simple-id`); check the group contents in the XSD for the exact element names before relying on this list.

## CLI (`_run_style`, `apply` branch from #213)

- No new options: `--scope` already accepts `dashboards`, `--dashboard NAME` exists.
- Update the `apply` subparser description: "writes the workbook and dashboard scopes; sheet formatting in the style file is listed as unsupported" (it says "workbook scope only" in #213).
- Print the boilerplate line above after the per-scope counts when it is non-zero.
- Exit codes: as #213 for now (0; 1 on `--on-clash fail` with kept formats or an error; 2 when something was unsupported or had no target and the rest was written). If the 0.6.0 exit-code packages (specs A4 to A7) are merged on your base, use their codes instead (5 for the refusal, 7 for "unsupported or no target, the rest written") and their table form in `docs/cli.md`.

## GUI

None in this package (B5 adds the Formatting card).

## Tests (`tests/test_style_apply.py`, next to #213's tests; fixtures in `tests/fixtures/style/`)

Fixtures already on `main` (2a): `format-source.twb` (dashboard `setTest`: root `layout-basic` id 4, title zone id 6 with `background-color #1A3A5C`, `layout-flow` containers, sheet zones, a dashboard `<style>` with `dash-title`), `format-target.twb` (same dashboard with other values: title `background-color #FFFFFF`, sheet zones `border-style solid`, `margin 1`, a filter zone id 10 with `margin 99` and `background-color #ABCDEF`, a container with `margin 2`), `format-bare.twb` (no workbook `<style>`, no `zone-style`; the dashboard already has an empty `<style />` right before `<size>`; plus a text zone id 11), `format.style.json` (v2, roles and `dash-title` rule). None of them has a device layout or a storyboard: build those in the test from `format-bare.twb` text (see below); do not commit new binary fixtures.

Tests (plan WP7-2c list, with what each asserts):

- `test_roles_classified`: on `format-target.twb`, the plan rows name zone 4 as `root`, the two `layout-flow` zones as `container`, zones 3, 5, 9 as `sheet`, zone 6 as `title`; zone 10 (filter) appears in no row.
- `test_bare_target_gets_zone_styles`: apply `format.style.json` to `format-bare.twb`: every zone of a named role gets a `zone-style` as its **last** child with the role's formats; `tests/schema_check.py` `new_schema_errors(before, after) == []`; `TwbParser` opens the output; `dashboards.integrity_check` adds nothing.
- `test_zone_style_is_last_child`: in a zone that has child zones and no `zone-style`, the new one comes after them.
- `test_background_only_on_root`: `dashboard.background` lands on zone 4 only; no other zone gets a `background-color` from it.
- `test_unnamed_role_zones_untouched`: filter zone 10 and text zone 11 are byte-equal before and after (`etree.tostring` of the element).
- `test_device_layouts_untouched`: insert into the bare fixture's text, after `</zones>` of `setTest`, a `<devicelayouts><devicelayout name='Phone' auto-generated='true'><zones><zone h='100000' id='20' type-v2='layout-basic' w='100000' x='0' y='0'><zone-style><format attr='margin' value='4' /></zone-style></zone></zones></devicelayout></devicelayouts>` block (check the XSD order: `devicelayouts` comes after `zones`); after apply, the `devicelayouts` element is byte-equal and the plan has no row for zone 20.
- `test_missing_title_zone_is_no_target`: remove zone 6 from the target text; the title role gives one `no-target` row; nothing else changes.
- `test_dashboard_filter_and_unknown_name`: with two dashboards (duplicate `setTest` in the text under another name), `dashboards=["setTest"]` writes only that one; an unknown name raises `StyleError` listing the names.
- `test_explicit_zone_format_kept`: target sheet zones have `margin 1`; the style says `margin 4`; default: `skip`, value stays `1`; with `force=True`: `force`, value `4` at the same position (index in `zone-style`).
- `test_boilerplate_counted`: a target zone with `margin 4` and a style with `margin 8` gives a `skip` row and `report["boilerplate_kept"] == 1`.
- `test_same_value_is_same_for_zones`: colour case differs only -> `same`.
- `test_dashboard_rules_written`: `dash-title` `font-family` goes into the dashboard's existing empty `<style />` of the bare target (it is reused, not duplicated: exactly one `<style>` stays in `<dashboard>`, still directly before `<size>`), and `new_schema_errors` is empty. The "created before `<size>`" case (a dashboard with no `<style>` at all) cannot be tested on the bare fixture: build it in the test by deleting that `<style />` from the fixture text, then assert the new `<style>` sits directly before `<size>`.
- `test_on_clash_fail_on_zone_writes_nothing`: `on_clash="fail"` with a zone conflict raises `StyleError` and no file is written (`apply_style` with an output path in `tmp_path`).
- `test_self_apply_is_noop_for_dashboards`: `extract_style(target)` then apply onto the same target with the default policy: only `same`/`skip`/`no-target` rows and the tree is equal (`etree.tostring` of the root before and after). Note: the extracted value is the modal value per role, so with mixed zones some rows are `skip`; that is expected (plan).
- `test_storyboard_and_zoneless_report`: a dashboard with `type='storyboard'` and one without `<zones>` give `no-target` rows with reasons, no exception.
- `test_scaffold_still_works`: apply a scaffold (`scaffold.apply_scaffold`, see `tests/test_scaffold.py` for the call) to the restyled output; `integrity_check` passes.
- `test_twbx_dashboard_restyle`: the same on `tests/fixtures/test_for_zip.twbx` if it has a dashboard (check); other members byte-equal (as #213's `test_twbx_members_copied`).
- CLI: `test_cli_dashboards_scope`: `style apply format.style.json format-bare.twb --scope dashboards --write -o out.twb` returns 0, prints the per-scope counts; a run that keeps formats on `format-target.twb` prints the boilerplate line when it applies.
- Update #213's tests that expect `dashboards` rows to be `unsupported` (search `test_style_apply.py` for `unsupported` and `WP7-2c`): they now get real actions; keep a test that `sheets` rows are still `unsupported`.

## Docs

- `docs/styles.md`: the "Formatting" section from #213: add the dashboard roles (what `root`, `container`, `sheet`, `title` are; that device layouts keep their old look; the explicit rule and the boilerplate line; "not opened in Tableau").
- `docs/cli.md`: `style apply` description and its row in the exit-code table.
- `docs/api.md`: no new public names expected (the functions exist since #213); if you export anything, add bullets.
- `docs/verify-in-tableau.md` and `docs/tableau-check.md`, `scripts/make_tableau_check_pack.py`: add row **43** (dashboard defaults: `format.style.json` applied with `--scope dashboards` to `format-bare.twb`; pass: draws the new background and borders on root, containers, sheets and the title zone, other dashboards unchanged; fail: a dialog or a layout shift). Look at how #213 added rows 42 and 44 and do the same; `tests/test_tableau_check_pack.py` lists the files.
- `AGENTS.md` `style.py` row: "2c: dashboard roles and rules written; device layouts untouched".
- `docs/wp7-style-plan-slice2.md` status row: "2c built". `docs/ROADMAP.md`: B3 row.

## How to verify

```bash
PYTHONPATH=$PWD /home/claude-user/ai-sandbox/py-tbparse/.venv/bin/pytest -q tests/test_style_apply.py tests/test_style_formats.py tests/test_style.py tests/test_schema.py tests/test_tableau_check_pack.py tests/test_exit_codes.py tests/test_api_doc.py
```

then the whole non-browser suite. With the corpus fetched (`python scripts/fetch_corpus.py`), run a quick manual loop (not a committed test; B5 adds that): for every corpus `.twb`, `plan_style(wb, extract_style(wb), scopes=("dashboards",))` must not raise. Run it with `nice -n 10 timeout 900` and a log; report the count and any exception.

## Not verifiable without Tableau Desktop

Plan section 9 and 10 items 3, 4, 5, 7: whether Tableau accepts a `zone-style` added to a zone that had none and formats appended at the end; whether a dashboard `<style>` with `dash-title` rules is honoured; who wins between zone, sheet and workbook rules; whether device layouts that keep the old zone styles still work. Pack row 43 is for the owner. Until he reports, the docs say "schema-valid, not opened in Tableau".

## Risks

- A default restyle that "does nothing" on dashboards because every zone already has Tableau's boilerplate: the boilerplate line in the report says why; the owner's answer to Q2 decides whether to change it.
- Modal extraction misrepresents a mixed dashboard (plan risk); self-apply shows `skip` rows for those.
- `style.py` grows past readability; the split is the next refactor.

## Definition of done

Dashboards scope written and planned as above, tests in, pack row 43, docs updated, whole non-browser suite and CI green, no version bump, PR says the merge waits for Q2.
