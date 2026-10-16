# WP7 plan, slice 2: fonts and formatting rules

Written 2026-10-16 for the agent that implements WP7 slice 2 (roadmap: `docs/template-roadmap-plan.md`, section WP7).
Slice 1 (palette library, `style show/export/import/check`, GUI Styles view) is on `main`; its plan is
`docs/wp7-style-plan.md` and this page imitates its shape and reuses its rules. Evidence is `docs/style-model.md`
(corpus census, re-run with `scripts/style_census.py`) plus the committed fixtures and `tests/schemas/twb_2026.2.0.xsd`.
**Nothing here has been opened in Tableau Desktop.** Every assumption that needs Tableau is in section 10 and the
questions only the owner can settle are in section 11. This page is a plan: no code changed with it.

## 1. Decision, scope and non-goals

Slice 2 reads **name-free** formatting from one workbook (fonts and workbook-wide style rules, dashboard zone styles by
role, a whitelist of sheet formats) into the `py-tbparse-style` file, and writes it onto other workbooks as a restyle that
**never replaces a format the target already has unless `--force` is given**. Every restyle first prints a plan, and every
run reports counts per scope: applied, same, skipped, forced.

In scope:
- `fonts` and `workbook_rules`: the workbook's `<style><style-rule element=...>` (roadmap: "workbook-wide fonts/colors").
- `dashboard`: background, padding and border defaults and the title zone, written as `zone-style` formats chosen by zone
  role, plus the dashboard's own `<style>` rules for `dash-title`, `dash-subtitle`, `dash-text`.
- `sheet_defaults`: a whitelist of name-free formats under `worksheet/table/style` (last work package, gated by Q3).
- A plan table, a report, a CLI (`style extract`, `style apply`), a GUI card in the existing Styles view, docs.

Non-goals (not done in this slice, and the guide says so):
- Recolouring marks. Per-value colours are data-bound (`datasource/style/.../encoding/map/bucket`, 98 workbooks,
  `style-model.md` finding 4). Palettes stay slice 1.
- Anything with a `field=` attribute (680 of 1711 sheet rules, `style-model.md` row "format with field"), `encoding`
  children, `column@default-format`, number formats.
- Device layouts, `bitmap`/logo zones, dashboard size, `style-theme`, `document-format-change-manifest` and every
  `_.fcp.*` element (kept byte-for-byte, never read as style).
- Installing or checking fonts, converting Power BI themes, merging or inheriting styles.
- Template integration (`apply_template(style=)`, `template make --with-style`): stays slice 3, after owner Q8.
- Editing a file in place: output is always a new file (slice 1 owner decision, 2026-10-06).

| Slice | Content | Status |
|---|---|---|
| 1, 1b | palette library; unnamed inline ramps | 1 done; 1b still open |
| **2** | **fonts, workbook rules, dashboard defaults, sheet whitelist (this page)** | **plan** |
| 3 | `apply_template(style=)`, `template make --with-style` | after slice 2 |
| never | per-value marks, device layouts, bitmaps, column formats | not transferable |

## 2. What is read from workbooks (evidence, and what is not known)

Facts below are from `style-model.md` (200-workbook corpus, indicative only; the corpus is not committed, the census
script is) unless marked "fixture" or "XSD".

**Workbook level** (`/workbook/style/style-rule`)
- Only 7 of 200 workbooks have a workbook `<style>`; rule elements: worksheet 3, all 3, title 2, tooltip 2, animation 1,
  story-title 1. Two of the seven carry `font-family`. Fonts otherwise live on leaves: title/label `<run fontname>` (Tableau
  Bold 25 workbooks, Benton Sans Book 14, Tableau Semibold 5, ...), sheet `table/style` `font-family`, pane and dashboard
  style (`style-model.md` section 4). So Tableau rarely writes a workbook font: **what Format > Workbook writes is an
  unknown** (which `element`, which attributes). Plan: read what is there, do not guess what Tableau would write.
- XSD: `style-rule/@element` is `StyleElement-ST` (includes `all`, `worksheet`, `title`, `tooltip`, `dash-title`,
  `dash-subtitle`, `dash-text`, `dash-zone`, `header`, `label`, ...). `format/@attr` is `StyleAttribute-ST` and contains
  `font-family`, `font-size`, `font-style`, `font-weight`, `color`, `background-color`, `text-align`, `border-*`,
  `margin`, `padding`. There is **no** `font-color` attribute: text colour is `color`.
- Fixture `tests/fixtures/public/filtering.twb` has a workbook `<style>` holding only an `_.fcp.MarkAnimation...style-rule`
  element (a feature-flag tag, not style). No committed fixture has a workbook font. Fixtures for this slice are hand
  made (section 8), exactly as slice 1 did.
- The `<style>` block sits after `preferences` and `style-theme` and before `datasources` (XSD
  `WorkbookStylesheet-G`; slice 1 section 2).

**Dashboard level**
- `zone-style` formats are name-free: 88 workbooks, 1455 zones, 6598 formats, `border-color`, `border-style`,
  `border-width`, `margin`, `padding`, `background-color` (`style-model.md` section 5). Fixture
  `tests/fixtures/public/filtering.twb` shows the shape: leaf sheet zones carry `border-color #000000`, `border-style
  none`, `border-width 0`, `margin 4`; the root layout zone carries the same with `margin 8`. In the XSD `zone-style` is
  the **last** child of `zone` and holds only `format(attr, value)`.
- Most of it is boilerplate: sheet leaves border none 669 of 709, margin 4 in 691; background colours appear on leaves in 6
  workbooks and on containers in 9 zones. A dashboard background is therefore a `background-color` on the root or a
  container zone, not a dashboard attribute. Any "default" is only a value Tableau wrote, not a marker of choice.
- Dashboard `<style><style-rule>` (`dash-title`, `dash-subtitle`, `dash-text`, `table`, `parameter-ctrl`,
  `story-point-caption`): 23 of 135 dashboards, name-free, carries `background-color`, `color`, `font-*`, `text-align`.
- Title zones (`type-v2="title"`, 26 workbooks) hold style in `zone-style`; title text is elsewhere and is not copied.
- `dashboards.zone_kind()` is the only way to classify a zone (AGENTS.md): `layout-basic` and `layout-flow` containers,
  `sheet`, `title`, `text`, `filter`, `bitmap`, ...

**Sheet level** (`worksheet/table/style/style-rule`; pane rules `table/panes/pane/style` are out)
- 24 distinct elements; the popular ones: `cell` 67 workbooks, `label` 46, `header` 45, `worksheet` 42, `table` 33,
  `gridline` 29, `title` 14. Name-free means no `field=` attribute and `scope` empty, `rows` or `cols` (XSD
  `StyleFieldScope-ST`). About 40 percent of rules carry `field=` and are skipped and counted.
- Sheet title text runs (`layout-options/title/formatted-text/run`, `fontname`, `fontsize`, `fontcolor`; XSD attributes
  exist) may embed `<[ds].[field]>`: the **style** is name-free, the text is not. Run formatting is **not read** in this
  slice (open item Q4).

**Unknown, not guessed**: how Tableau merges workbook, sheet and zone rules and which wins; which values the user chose
versus Tableau wrote; whether a font that is missing on the machine is substituted silently (the census says "Tableau *"
faces ship with Tableau, others may be missing; not checkable here); whether Tableau accepts a new workbook `<style>`
rule it did not write itself; whether anything cleans or regenerates device-layout zone styles after a zone changes.

## 3. The style file, version 2

`*.style.json`, same encoding rules as slice 1 (UTF-8, `indent=2`, `ensure_ascii=False`, sorted keys). Slice 1 already
reserved `fonts`, `workbook_rules`, `dashboard`, `sheet_defaults` and rejects them in a version 1 file; version 2 allows
them. `load_style` accepts versions 1 and 2. `make_style` still writes version 1 when only palettes are given, and version 2
as soon as any formatting section is non-empty (so existing `.style.json` files and the slice 1 GUI keep working; Q6).

```json
{"format": "py-tbparse-style", "version": 2, "name": "Acme", "description": "", "created": "...",
 "py_tbparse_version": "...", "sources": ["Brand.twb"],
 "palettes": [{"name": "Acme Brand", "type": "regular", "colors": ["#1A3A5C"], "attrs": {}}],
 "fonts": {"all": {"font-family": "Segoe UI", "font-size": "10"},
           "title": {"font-family": "Segoe UI Semibold", "font-size": "14", "color": "#1A3A5C"}},
 "workbook_rules": [{"element": "worksheet", "formats": [{"attr": "background-color", "value": "#FFFFFF"}]}],
 "dashboard": {
   "background": "#F5F5F5",
   "roles": {"root": {"margin": "8"}, "container": {"margin": "8"},
             "sheet": {"margin": "4", "border-style": "solid", "border-color": "#CCCCCC", "border-width": "1"},
             "title": {"background-color": "#1A3A5C", "padding": "0"}},
   "rules": [{"element": "dash-title", "formats": [{"attr": "font-family", "value": "Segoe UI Semibold"}]}]},
 "sheet_defaults": [{"element": "header", "formats": [{"attr": "font-weight", "value": "bold"}]}]}
```

- **Values are strings exactly as in the XML** (`"10"`, `"#1A3A5C"`), never converted. Colours are not case-folded.
- `fonts` is a **convenience view of workbook rules**, keyed by element (`all`, `worksheet`, `title`, `tooltip`), allowed
  attributes `font-family`, `font-size`, `font-weight`, `font-style`, `color`. It expands to `workbook_rules`
  entries when applied. A file that gives the same (element, attr) in both `fonts` and `workbook_rules` is a `StyleError`
  (one canonical place). Extraction puts font attributes in `fonts` and every other workbook-rule format in
  `workbook_rules`.
- `workbook_rules`: list of `{element, formats: [{attr, value, scope?}]}`. Elements allowed: `all`, `worksheet`, `title`,
  `tooltip` (the four seen in the corpus; the rest of `StyleElement-ST` is reported `unsupported`, not written).
  Attribute names must be in `StyleAttribute-ST` (the XSD list is loaded by `check`, not copied by hand: Q5 on whether to
  keep a static copy). `field` and `encoding` are not representable, so they cannot be put in the file.
- `dashboard.background` is shorthand for `background-color` on the `root` role and is the only place it may be set for
  the root (setting it in `roles.root` as well is a `StyleError`). `roles` maps a zone role to `{attr: value}`;
  roles are `root` (the zone directly under `<zones>`), `container` (any other `layout-basic`/`layout-flow`), `sheet`
  (leaf worksheet zones), `title` (`type-v2="title"`). Attributes allowed: `background-color`, `border-color`,
  `border-style`, `border-width`, `margin`, `padding` (the six seen in the corpus; the `-top/-left...` variants exist in
  the XSD but have no corpus evidence, so they are `unsupported` for now). `rules` is the dashboard `<style>` list with
  elements `dash-title`, `dash-subtitle`, `dash-text`.
- `sheet_defaults`: same entry shape as `workbook_rules`; elements allowed `header`, `label`, `title`, `worksheet`, `cell`;
  attributes `font-family`, `font-size`, `font-weight`, `font-style`, `color`, `background-color`, `border-*`,
  `text-align`; `scope` optional (`rows` or `cols`).
- Validation (`check_style_file`, `load_style`): unknown top-level key, unknown role/element/attr, empty value, a value
  with a control character, a `_.fcp.` string anywhere, duplicates. Font names are free text; a font family not in a
  small list of faces that ship with Tableau gets a **warning** ("may not exist on the target machine"), never an error.

## 4. Restyle semantics

**Unit of change**: one format key. For workbook and dashboard-level rules the key is `(scope, element, attr, scope-attr)`;
for zones it is `(dashboard, zone, attr)`.

**What counts as explicit.** There is no default marker in the XML (`style-model.md` section 1), so the rule is
conservative: **any `<format>` already present in the target for that key is explicit**, whatever its value, including
Tableau boilerplate like `margin 4`. Consequence: restyling a dashboard whose zones carry Tableau's default `margin 4`
changes nothing for margin unless `--force`. That is the safe reading of the roadmap's "never overwrite a format that a
sheet set explicitly unless `--force`"; whether to treat the known boilerplate values as overwritable is Q2.

**Per key the plan decides, before anything is written** (`action` column):

| action | meaning |
|---|---|
| `add` | key absent in target; written (creating the `style-rule` or `zone-style` if needed) |
| `same` | present with the same value (compared as strings, colours case-insensitively); nothing to do |
| `skip` | present with another value; kept (the default) |
| `force` | present with another value and `--force` given; value replaced in place (position kept) |
| `unsupported` | in the file but outside the whitelist (element, attr, role) |
| `no-target` | nothing to put it on: dashboard without a `title` zone, a role with no zone, unknown dashboard name |
| `fail` | `--on-clash fail` and a `skip` row exists: raise `StyleError` listing them, write nothing |

`--on-clash skip|fail`, default `skip` (the roadmap wants a report, not a stop; the slice 1 default was `fail` for palettes
because a duplicate name is ambiguous, here a skip loses nothing). `--force` and `--on-clash fail` together are refused.

**Rules that hold for every action**
1. Never touch `field=` formats, `encoding`, `_.fcp.*` elements, datasource `style`, `pane/style`, `devicelayouts`, zones
   that are not of a named role, and the order of existing elements. Existing formats are edited in place, new ones appended
   at the end of their rule; a new `style-rule` goes after the last real `style-rule` in its `style` (a `style` with only
   `_.fcp.` tags gets the rule first; ordering among `style-rule`s is not constrained by the XSD, Tableau's habit is unknown).
2. A new workbook `<style>` goes after `preferences`/`style-theme` and before `datasources`; a new `zone-style` is the last
   child of its zone (XSD `Zone-G`). If the dashboard has no `<style>`, a new one is inserted where `Dashboard` allows.
3. Scope is explicit: `--scope workbook,dashboards,sheets` (default `workbook,dashboards`; sheets only when asked, Q3).
   `--dashboard NAME` and `--sheet NAME` (repeatable, exact, case-sensitive, **the target's own names**, no mapping) narrow
   it; an unknown name raises `StyleError`.
4. A dashboard role value applies to every zone of that role in the dashboard. Zones whose kind is not a named role are
   left alone. Device layouts are left alone, so a phone layout can keep the old look; the plan says so in one line.
5. Palettes in a v2 file are **ignored by `style apply`** unless `--palettes` is given, then handled by the slice 1
   planner with its own `--palette-on-clash` (default `fail`). `style import` stays the palette verb and ignores formatting.
6. Output and refusal rules are slice 1's: new file `<stem>_styled<ext>` beside the target, same suffix, never the input,
   never an existing file, `xb` unless `--overwrite`; `.twbx` members copied untouched through `rename._serialize_workbook`, as slice 1 does.
7. Extraction from a dashboard takes, per role and attribute, the **most frequent value** among that role's zones, ties by
   document order, and lists every attribute that had more than one value in the report (`mixed`). It is a summary of what
   the source does, not a record of one zone. No fonts or colours are invented when the source has none.

**Report** (`report` dict, also printed): lists `added`, `same`, `skipped`, `forced`, `unsupported`, `no_target`,
`warnings` (as `"scope: element/attr"` or `"dashboard/role/attr"`), plus `counts` per scope. After `--write` the CLI
prints applied/same/skipped/forced per scope and the fixed line: "formats were added to the workbook; marks keep their
colours; nothing here has been opened in Tableau".

## 5. API (extends `py_tbparse/style.py`; exported from `__init__.py`)

```python
STYLE_VERSION = 2                      # reader accepts 1 and 2
FORMAT_ACTIONS = ("add", "same", "skip", "force", "unsupported", "no-target", "fail")
STYLE_PLAN_COLUMNS = ["scope", "target", "where", "attr", "current", "new", "action", "reason"]
FORMAT_SCOPES = ("workbook", "dashboards", "sheets")

def extract_style(source, dashboard: str | None = None, scopes=("workbook", "dashboards"),
                  palettes: bool = True, name=None, report: dict | None = None) -> dict
def format_table(source_or_style) -> pd.DataFrame            # one row per format found, what a person reads
def plan_style(target, style, scopes=("workbook", "dashboards"), dashboards=None, sheets=None,
               force: bool = False, on_clash: str = "skip") -> pd.DataFrame      # STYLE_PLAN_COLUMNS
def build_styled(target, style, ..., report=None) -> bytes   # the bytes the GUI and apply_style use
def apply_style(target, style, output_path=None, scopes=..., dashboards=None, sheets=None, force=False,
                on_clash="skip", palettes=False, palette_on_clash="fail", overwrite=False, report=None) -> str
```

`style` is a dict, a `.style.json` path or a `.twb`/`.twbx` (extracted on the fly, as `import` accepts any source).
`make_style` gains the four sections; `_check_style` validates them; `palette_problems`/`check_style_file` also report
format problems. Slice 1 functions keep their signatures. Extraction and apply share one whitelist table in the module
(roles, elements, attributes) so the tests can walk it. Hardened parsing for user files is unchanged. New code must not
use `z.get("type-v2")`: always `dashboards.zone_kind`.

## 6. CLI

```
py-tbparse style extract SRC -o OUT.style.json [--dashboard NAME] [--scope workbook,dashboards,sheets]
                         [--no-palettes] [--name N] [--overwrite]
py-tbparse style apply STYLE TARGET [--scope ...] [--dashboard NAME ...] [--sheet NAME ...]
                         [--on-clash skip|fail] [--force] [--palettes] [--palette-on-clash ...]
                         [-o OUT] [--overwrite] [--write]
py-tbparse style show SRC [SRC ...] [--what palettes|formats|all] [--format table|csv|json]   # default palettes
py-tbparse style check FILE                    # now also validates the v2 sections
```

- `apply` without `--write` prints the plan table and the counts and writes nothing (as `import` does).
- `STYLE` is a `.style.json` or any workbook; `TARGET` is `.twb` or `.twbx` (a `.tps` has no formatting; refused with that
  message).
- Exit codes follow `docs/cli.md#exit-codes`: 0 fine; 1 `StyleError`, `--on-clash fail` with skips, unreadable input,
  existing output; 2 something `unsupported` or `no-target` but the rest was written. Document in `docs/cli.md`.

## 7. GUI

In the existing Styles view (`styles.js`, `/style/*`), a third card **Formatting** below the palette cards, same rules as
the palette cards: it never writes on the server and takes no path.
- Lists the open workbook's extracted formats (`format_table`) 100 rows at a time with search, grouped by scope, as a
  paged pseudo-table (never the whole table in the DOM: dashboards can have 1455 zones; the table shows the extracted
  role summary, not one row per zone).
- **Apply from a file**: upload a `*.style.json` (same 2 MB cap and in-memory `_STATE["sty"]` slot), choose scopes, `--force`
  as a checkbox (off), the skip/fail policy; the plan with counts and rows is shown before the download button works;
  **Download new workbook** returns `build_styled` bytes named `<stem>_styled.twb(x)`.
- Endpoints: `GET /style/formats`, `POST /style/format-plan`, `POST /style/format-apply`, `POST /style/format-export`
  (extracted style file, download). Add them to the endpoint whitelist with their allowed keys (as `/style/export` does).
- Every colour shown has its hex in text; the card repeats "adds or changes formats; recolours no marks; not opened in
  Tableau". Changes to `webui/` follow the AGENTS.md GUI rules (tokens, contrast checks, the screenshot script).

## 8. Work packages and acceptance tests

Hand-made fixtures in `tests/fixtures/style/` (committed fixtures have no workbook font, so these are needed):
`format-source.twb` (copy of `tests/fixtures/public/filtering.twb`; a workbook `<style>` with real `style-rule`s `all`
and `title` with fonts, a dashboard `<style>` with `dash-title`, a dashboard with a title zone, a root, two containers and
three sheet zones with `zone-style` of different values, a sheet `table/style` with a `header` rule, a `field=` rule and a
`scope="cols"` rule); `format-target.twb` (the same dashboard with other values and one explicit `title` font);
`format-bare.twb` (no `<style>`, zones without `zone-style`); `format.style.json` (v2); `bad-format.style.json`.

**WP7-2a. Read side: style v2 and `style extract`** (size M)
1. `extract_style`, `format_table`, v2 `make_style`/`_check_style`/`load_style`, `style extract`, `style show --what`.
2. Tests (`tests/test_style_formats.py`): `test_v1_files_still_load`; `test_v2_roundtrip` (save, load, equal);
   `test_v2_sections_rejected_in_v1`; `test_extract_fonts_and_rules` (fonts in `fonts`, others in `workbook_rules`);
   `test_extract_skips_field_and_fcp` (a `field=` format and the `_.fcp.` tag never appear, counted in the report);
   `test_extract_dashboard_roles_modal` (modal value, tie by document order, `mixed` listed);
   `test_extract_no_invention` (a workbook without style gives empty sections, not defaults);
   `test_check_rejects` (unknown role/element/attr, empty value, same key in `fonts` and `workbook_rules`,
   `background` plus `roles.root.background-color`); `test_font_warning_not_error`; `test_non_latin_font_name`;
   `test_whitelist_matches_xsd` (every allowed element and attribute is in `StyleElement-ST`/`StyleAttribute-ST`);
   CLI tests for `extract`, `show --what formats`, `check`.

**WP7-2b. Workbook rules and fonts: plan and apply** (size M)
1. `plan_style`, `build_styled`, `apply_style` for scope `workbook`; clash and force; output rules; `style apply`.
2. Tests: `test_apply_adds_missing_style_block` (inserted before `datasources`, after `preferences`;
   `schema_check.new_schema_errors(before, after) == []`; `TwbParser` opens it); `test_apply_adds_rule_and_format`;
   `test_explicit_format_kept` (default: `skip`, tree equal for that key); `test_force_replaces_in_place` (position kept);
   `test_same_value_is_same` (colour case); `test_on_clash_fail_writes_nothing`; `test_fcp_elements_byte_equal`;
   `test_unsupported_element_reported`; `test_self_apply_is_noop` (extract then apply onto the same workbook: only
   `same`/`skip`, equal tree); `test_never_overwrites_files` (input as output, existing output, `.tps` target refused);
   `test_twbx_members_copied` (`tests/fixtures/test_for_zip.twbx`); `test_report_counts`; CLI plan-only writes nothing;
   exit codes 0/1/2.

**WP7-2c. Dashboard defaults by role** (size L: most XML work)
1. Role classifier on `dashboards.zone_kind`; apply `roles`, `background`, `rules`; `no-target` handling; `--dashboard`.
2. Tests: `test_roles_classified` (root/container/sheet/title on the fixture, floating and storyboard dashboards report
   rather than crash); `test_zone_style_is_last_child` (schema check); `test_background_only_on_root`;
   `test_unnamed_role_zones_untouched` (filter, legend, text, bitmap zones byte-equal);
   `test_device_layouts_untouched`; `test_missing_title_zone_is_no_target`; `test_dashboard_filter_and_unknown_name`;
   `test_explicit_zone_format_kept` (the target's `margin 4` is kept without `--force`, replaced with it);
   `test_scaffold_still_works` (apply a scaffold after a restyle; `dashboards.integrity_check` passes).

**WP7-2d. Sheet whitelist** (size M, only after Q3)
1. Extract and apply `sheet_defaults` to `worksheet/table/style` of selected sheets (default none: needs `--scope sheets`).
2. Tests: `test_sheet_field_formats_never_copied`; `test_scope_rows_cols_keyed_separately`;
   `test_pane_style_untouched`; `test_sheet_explicit_kept_force_replaces`; `test_unknown_sheet_name_raises`;
   `test_sheet_title_runs_untouched` (decision recorded in Q4).

**WP7-2e. Corpus smoke and GUI** (size M)
1. `tests/test_corpus.py::test_style_formats_on_every_workbook`: for all 200 workbooks `extract_style` never raises; extract
   then apply onto itself with the default policy leaves the tree equal; applying the extracted style of every workbook that
   has formatting onto one fixed target adds no new schema errors (`new_schema_errors`). Known failures go to a named
   known-issues list in the test, not a skip. With `--force`, self-apply is not required to be a no-op for dashboard
   roles (modal summary versus individual zones); the test asserts that it is a no-op for workbook rules only.
2. GUI card, endpoints and `tests/test_webgui_styles.py`/`tests/test_gui_styles.py` additions: paged list under 100 rows in the
   DOM, the plan before download, force off by default, no path in any payload, dark theme and 390 px checks.

**WP7-2f. Docs and the Tableau check** (size S, with each package)
`docs/styles.md` (a "Formatting" section with the "does not recolour; not opened in Tableau" warning, the explicit rule and
`--force`), `docs/cli.md`, `docs/api.md`, `docs/gui.md`, README (Guides link and Limits), `docs/wp7-style-plan.md` status
line, `docs/template-roadmap-plan.md` state table line, `AGENTS.md` (`style.py` row; a new module only if the file grows
past reason: split the format half into `styleformat.py`, then add its row), `docs/verify-in-tableau.md` and
`scripts/make_tableau_check_pack.py` (rows 42 to 44, section 9).

Order: 2a, 2b, 2c, then 2e and 2d, GUI last. One PR per package; no version bump until the owner asks for a merge.

## 9. What cannot be verified without Tableau Desktop

The pack in `docs/tableau-check.md` (`scripts/make_tableau_check_pack.py`) today covers palettes only (files 40 and 41).
Slice 2 adds, to the same list and pack, files made from `format-bare.twb` and `format-target.twb`:
- **42** workbook fonts: `style apply` of a fonts-only style. Pass: opens with no dialog; Format > Workbook (and the tooltip
  and title) show the family and size; sheet text changes where it follows the workbook rule. Fail: a dialog, no change,
  or Tableau silently dropping the `<style>` block after a save and reopen.
- **43** dashboard defaults: background, padding, borders on a dashboard. Pass: draws the new background and borders on
  root, containers, sheets and title zone; the other dashboards unchanged. Fail: any dialog, a layout shift.
- **44** `--force` versus default on a workbook with explicit fonts: default keeps them, `--force` shows the new ones.
- **45** (only if 2d ships) sheet header and label fonts.

Cannot be known from files alone (all listed as unverified in section 10): whether Tableau accepts our hand-added
`style-rule`; who wins when a workbook rule, a sheet rule and a zone rule disagree (this decides whether a workbook font
visibly changes anything on sheets that already have their own font); whether a missing font is replaced silently;
whether device layouts follow a restyled dashboard; whether Tableau rewrites or drops unknown ordering on save.
A passing file would show one workbook on one Tableau version, not a general result.

## 10. Risks and unverified assumptions

Risks:
- **A restyle that visibly does nothing**: sheets that already carry their own fonts keep them (explicit rule), and the
  workbook rule may be overridden by sheet rules in Tableau's own merge order. Mitigation: the plan states per scope how
  many keys were `skip`; the guide says "sheet-level formats win unless you use `--force` on `--scope sheets`" only after
  Tableau check 44 confirms it; until then it says "not checked".
- **Boilerplate is explicit**: most dashboards already hold Tableau's default zone formats, so default restyles skip them
  (Q2). Users may find `style apply` "does nothing" for margins; the report must say why.
- **Modal extraction misrepresents a mixed dashboard**: reported as `mixed`; the style file is editable by hand.
- **Fonts**: a name that is absent on the target machine is replaced silently by Tableau (unverified); we only warn.
- **XSD-valid but Tableau-rejected**: the validation gate (`new_schema_errors`) is the same differential as other writers
  and proves schema validity only.
- **Scope creep into marks and merge semantics**: guarded by the whitelist test (`test_whitelist_matches_xsd`) and by the
  non-goals above.
- lxml re-serialises the whole workbook (quoting, whitespace), as for every writer; byte fidelity belongs to WP8 (`diff-xml`
  can show the real changes).
- Size: `style.py` is 666 lines; slice 2 roughly doubles it. Split into `styleformat.py` before it becomes unreadable.

Unverified in Tableau (none of this has been opened in Tableau Desktop):
1. A workbook `<style>` or `style-rule` added by us is read and applied (and not dropped on save).
2. Which element carries Format > Workbook fonts in current Tableau (`all`? `worksheet`?), and that our choice matches.
3. Merge order between workbook, sheet and zone rules; that sheet-level explicit formats really win.
4. `zone-style` added to a zone that had none, and new formats appended at the end of an existing one, are accepted.
5. A dashboard `<style>` with `dash-title`/`dash-subtitle`/`dash-text` rules is honoured.
6. Fonts: substitution of missing families, and that `font-weight`/`font-style` values copied as strings are valid
   (the corpus has them; their legal values are not in the XSD as an enumeration we checked).
7. Device layouts keep the old zone styles after a restyle without breaking the dashboard.
8. Style rules inside a `.twbx` behave like those in a `.twb`.
9. Older Tableau versions read the same shapes (the corpus spans versions; `_.fcp.*` flags show drift).

## 11. Questions only the owner can answer (recommended default in brackets)

Each goes through the interactive question tool when asked.

- **Q1** Is slice 2 wanted now? Slice 1's Q3 said to decide after the Tableau check of slice 1; `docs/tableau-check.md`
  rows 40 and 41 are still "not run". [Yes for planning and for 2a and 2b, which are cheap and reversible; do not start 2c
  to 2e before at least check 40 is back, because it shows whether Tableau accepts any file we add to.]
- **Q2** What counts as explicit? [Any present format, even Tableau's default boilerplate (`margin 4`, `border none`);
  `--force` replaces. Alternative: a short list of boilerplate values counts as "default-looking" and is overwritten by
  default; it needs a list we cannot verify, so not recommended.]
- **Q3** Do sheet-level whitelist formats (2d) ship at all, and is `--scope sheets` opt-in? [Defer 2d until check 42 and 44
  say how rules merge; opt-in only.]
- **Q4** Sheet and dashboard title runs (`<run fontname fontsize fontcolor>`, 111 workbooks) hold the most real fonts but sit
  beside text that may embed field names. Copy run formatting without the text? [No in this slice; revisit with the check.]
- **Q5** Whitelists: static lists in the module or read from the XSD at run time? [Static lists, with the test that
  compares them to the XSD, so the package never depends on the test schema.]
- **Q6** Version of the style file: write v2 only when a formatting section is non-empty, or always v2 from now on?
  [Only when needed, so slice 1 files and GUI stay unchanged.]
- **Q7** Default clash policy for `style apply`: `skip` with a report, versus `fail` as in slice 1? [`skip`; `fail` is
  one flag away for CI use.]
- **Q8** Template integration (slice 3: `template make --with-style`, `apply_template(style=)`): wait until the Tableau
  check of slice 2 is back? [Yes.]
- **Q9** Can you run the Tableau checks 42 to 44 (about 15 minutes more on top of the 30 in `tableau-check.md`) before the
  release that ships slice 2? [Yes; they settle assumptions 1 to 4.]
- **Q10** Release: its own 0.5.x/0.6.0 after slice 2a-2c, or together with 2d-2e? [Own release after 2c; no version bump
  in any branch until you ask for a merge.]
