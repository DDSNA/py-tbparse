# WP7 plan: style templates, slice by slice

Written 2026-10-05 for the agent that implements WP7 (roadmap: `docs/template-roadmap-plan.md`, section WP7, and its
sections 0 and 3, which still apply). Evidence: `docs/style-model.md` (corpus census, re-run with
`scripts/style_census.py`). House style and shared pieces follow `docs/wp6-library-design.md` on branch `wp6-library`.
Nothing here has been opened in real Tableau; every such assumption is listed in section 8.

## 1. Decision: the first slice is a palette library, not a restyle

Slice 1 reads named custom colour palettes from workbooks, `Preferences.tps` files and a small JSON file, and writes
them into a new `Preferences.tps`, a JSON file, or a copy of a workbook. It makes palettes **selectable in the colour
picker**. It recolours nothing: colours in use are written per value into datasource `mark` encodings
(`style-model.md` finding 3), and slice 1 never touches those. Every user-facing message and the guide must say this.

Why this slice: `<color-palette name type><color/>` is the only style object that is name-free, has the same shape in a
`.twb` and a `.tps` (help page; corpus agrees), has an XSD definition in `tests/schemas/twb_2026.2.0.xsd`
(`ColorPalette-G`, `Preferences-G`) and needs no knowledge of how Tableau merges style rules.
Honest scope: only 3 of 200 corpus workbooks have a named palette. The value is in replacing hand-edited `.tps` XML for
teams that share a corporate palette, not in corpus frequency.

| Slice | Content | Status |
|---|---|---|
| 1 | palette library: `style show/export/import/check` | **build now** (sections 2-6) |
| 1b | export unnamed inline ramps (`encoding/color-palette name=""`, 10 wbs) as named palettes | next, small (section 7) |
| 2 | name-free formatting transfer (workbook style rules, dashboard zone-style by role, whitelist of sheet formats) | deferred, needs owner answers |
| 3 | template integration (`apply_template(style=)`, `template make --with-style`) | deferred until slice 2 |
| never | per-value mark colours, device layouts, bitmap/logo zones, column `default-format` | not transferable (section 7) |

## 2. XML facts slice 1 relies on

- Palette element (XSD `ColorPalette-G`): `<color-palette name=".." type="regular|ordered-sequential|ordered-diverging">`
  with one or more `<color>` children whose text matches `#[0-9A-Fa-f]{6}|#[0-9A-Fa-f]{8}`. Optional boolean attrs:
  `custom`, `not-reference-band`, `not-filled`, `not-categorical`, `not-quantitative`.
- `<preferences>` holds `<preference name value/>*` first, then `<color-palette>*` (XSD sequence).
- In a workbook, `<preferences>` comes after `document-format-change-manifest` and `repository-location` (both
  optional) and before `style-theme`, `style`, `datasources` (XSD `WorkbookFile-CT`).
- `.tps` shape (help page, no real file seen): `<?xml version='1.0'?><workbook><preferences><color-palette ...>`.
  It may also hold `<preference>` elements; anything we do not understand is kept untouched.
- Only `/workbook/preferences/color-palette` counts as a palette. Ignore inline `encoding/color-palette` (slice 1b) and
  built-in ids in `palette="green_10_0"` attributes (never copy). Never touch `document-format-change-manifest` or any
  `_.fcp.*` element.

## 3. Style file format v1 (`*.style.json`, UTF-8, `indent=2`, `ensure_ascii=False`, keys sorted)

```json
{"format": "py-tbparse-style", "version": 1, "name": "Acme palettes", "description": "",
 "created": "<_now()>", "py_tbparse_version": "<_version()>",
 "sources": ["Brand.twbx", "Preferences.tps"],
 "palettes": [
   {"name": "Acme Brand", "type": "regular", "colors": ["#1A3A5C", "#C9973A"], "attrs": {"custom": "true"}}]}
```

- `palettes` keeps source order (picker order may follow file order, section 8). `colors` keeps order and the exact
  text (no case change). `attrs` holds every other `<color-palette>` attribute verbatim, as strings.
- `load_style` raises `StyleError` on another `format`, a `version` above 1, an unknown top-level key (the names
  `fonts`, `workbook_rules`, `dashboard`, `sheet_defaults` are reserved for v2 and also rejected in v1), a palette
  that fails section 4's checks, or two palettes with the same name.
- Reuse `templates._now` and `templates._version` (injectable clock for tests). Do not reuse `templates.MANIFEST_*`.

## 4. API (new module `py_tbparse/style.py`, exported from `__init__.py`)

```python
class StyleError(ValueError): ...
STYLE_FORMAT = "py-tbparse-style"; STYLE_VERSION = 1
PALETTE_TYPES = ("regular", "ordered-sequential", "ordered-diverging")
CLASH_POLICIES = ("fail", "skip", "rename", "replace")
PALETTE_COLUMNS = ["source", "name", "type", "n_colors", "colors", "status", "reason"]
PLAN_COLUMNS = ["name", "type", "n_colors", "action", "target_name", "reason"]

def read_palettes(source: str | os.PathLike | TwbParser, report: dict | None = None) -> list[dict]
def palettes_table(source_or_palettes) -> pd.DataFrame          # PALETTE_COLUMNS, one row per palette found
def make_style(palettes: list[dict], name=None, description=None, sources=()) -> dict
def save_style(style: dict, path, overwrite: bool = False) -> str
def load_style(path) -> dict
def tps_bytes(palettes: list[dict]) -> bytes                    # a fresh Preferences.tps
def check_style_file(path) -> list[str]                         # problems in a .tps or .style.json; [] = fine
def plan_palette_import(target, palettes, on_clash: str = "fail", select=None) -> pd.DataFrame
def build_with_palettes(target, palettes, on_clash="fail", select=None, report=None) -> bytes
def import_palettes(target, palettes: list | dict | str, output_path=None, on_clash="fail", select=None,
                    overwrite: bool = False, report: dict | None = None) -> str
def export_palettes(sources: list, output_path, select=None, on_clash="fail", name=None,
                    overwrite: bool = False, report: dict | None = None) -> str
```

- **Source dispatch by suffix** (case-insensitive): `.twb`/`.twbx` through `TwbParser`; `.tps` through
  `etree.parse(path, etree.XMLParser(resolve_entities=False, no_network=True))` (user files: no entity expansion);
  `.style.json` through `load_style`. Anything else: `StyleError`. A `.tps` whose root is not `workbook` is an error.
- **Validation per palette** (in `read_palettes`): empty or missing `name`, a `type` outside `PALETTE_TYPES`, zero
  colours, or a colour not matching the XSD pattern makes it `invalid` (row `status="invalid"`, `reason` says why;
  never exported). An 8-digit colour is valid but adds a `warning` in `reason` ("alpha not confirmed for .tps").
  `report` gets `found`, `invalid`, `warnings` (lists of names).
- **Identity**: two palettes are identical when name, type and colours match (colours compared upper-cased, order
  matters). `attrs` are ignored for identity and copied as they are.
- **Clash** = same `name` (exact, case-sensitive) with a different definition. Names that differ only in case are
  not a clash but give a warning. Policies, decided for the whole plan before anything is written:
  `fail` raise `StyleError` listing the clashes; `skip` keep the target's palette; `rename` add as `"<name> (2)"` or the
  next free `(n)`; `replace` swap the target's element in place (same position). Plan actions: `add`,
  `skip-identical`, `skip`, `rename`, `replace`, `invalid`.
- `select`: palette names to take (exact); a name not found raises `StyleError`.
- `export_palettes` merges sources in argument order, applying `on_clash` between sources too, then writes by the
  output suffix: `.tps` via `tps_bytes`, `.style.json` via `save_style`, anything else `StyleError`.
- **Writing into a target** (`build_with_palettes`): deep-copy the root. Find `/workbook/preferences`; if missing,
  create it and insert it after the last of `document-format-change-manifest` / `repository-location` that exists,
  else as the first child. Append new palettes after the last `color-palette`, else after the last `preference`, else
  at the end of `<preferences>`. Write attributes as `name`, `type`, then `attrs` keys sorted; one `<color>` per
  colour. Match the indentation of siblings (copy the `tail` of the last sibling) so the diff stays readable.
- **Output**: `.tps` target gives `.tps` bytes with an XML declaration; `.twb` gives `.twb` bytes; `.twbx` gives a
  `.twbx` with every other member copied untouched. Extract the zip-copy code at the end of
  `rename.build_renamed_workbook` into `rename._workbook_bytes(parser, doc) -> bytes` and use it from both (no
  behaviour change; WP6 asks for the same helper: if `wp6-library` has merged into `main` first, reuse its helper
  instead and do not add a second one).
- `import_palettes` writes to `<stem>_palettes<ext>` beside the target by default. The output must keep the target's
  suffix, never equals the input, and opens with `"wb" if overwrite else "xb"` (same rules as
  `rename.apply_field_renames`). It never edits a user's real `Preferences.tps` in place (owner question Q2).
- `report` on import/export: lists `added`, `skipped_identical`, `skipped`, `renamed` (as `"old -> new"`),
  `replaced`, `invalid`, `warnings`, plus `counts` (a dict of their lengths). Deterministic: no sorting of palettes,
  no clock except `created`.

## 5. CLI (`py-tbparse style ...`: reserve it in `cli.main` like `template`, with `build_style_arg_parser`)

```
py-tbparse style show SRC [SRC ...] [--format table|csv|json]
py-tbparse style export SRC [SRC ...] -o OUT.tps|OUT.style.json [--palette NAME ...]
                        [--on-clash fail|skip|rename|replace] [--name N] [--overwrite]
py-tbparse style import LIB TARGET [--palette NAME ...] [--on-clash ...] [-o OUT] [--overwrite] [--write]
py-tbparse style check FILE            # .tps or .style.json
```

- `LIB` and `SRC` take any source type. `TARGET` is `.tps`, `.twb` or `.twbx`.
- `import` without `--write` prints the plan table and writes nothing. With `--write` it writes and prints
  `wrote <path>` and the counts to stderr, plus one fixed line: "palettes are now in the colour picker; existing
  marks keep their colours". For a `.tps` output it adds: "copy it over My Tableau Repository/Preferences.tps (keep a
  backup) and restart Tableau Desktop".
- Exit codes: 0 ok; 1 on `StyleError`, `FileExistsError`, unreadable input; 2 when any palette was `invalid` but the
  rest were written (message says so). `check` exits 1 when it finds problems.

## 6. Tests (`tests/test_style.py` unless noted)

Fixtures in `tests/fixtures/style/`, hand-made: `palettes.twb` (copy of `tests/fixtures/test_for_wenjie.twb` with a
`document-format-change-manifest`, a `<preferences>` holding one `<preference>` and three palettes, one per type, one
with `custom="true"`, plus a sheet colour encoding with an inline `name=""` ramp and a `palette="green_10_0"`
reference); `Preferences.tps` (help-page shape, one `<preference>`, two palettes, one clashing by name with
`palettes.twb`); `bad.tps` (bad colour, bad type, empty name, zero colours, one good palette).

1. `test_read_palettes_from_workbook`: three palettes in file order, attrs kept; inline ramp and built-in id ignored.
2. `test_read_palettes_from_tps_and_json`: same dicts from all three source types after export.
3. `test_invalid_palettes_reported`: `bad.tps` gives one palette and four `invalid` rows with reasons; 8-digit warns.
4. `test_style_json_roundtrip`: save then load gives the same dict; refuses to overwrite; bad `format`, version 2, an
   unknown or reserved key and duplicate names raise.
5. `test_tps_bytes_shape`: root `workbook`, one `preferences`, palettes in order; `check_style_file` returns `[]`;
   parses with the hardened parser.
6. `test_import_into_workbook_without_preferences`: `<preferences>` created after the manifest, before `datasources`;
   `tests/schema_check.new_schema_errors(before, after) == []`; `TwbParser(out)` works.
7. `test_import_keeps_existing_preferences`: new palettes go after the last palette; the `<preference>` stays first.
8. `test_self_import_is_noop`: importing a workbook's palettes into itself gives only `skip-identical` and an equal
   tree (`etree.tostring` of input and `build_with_palettes` output compare equal).
9. `test_clash_fail_writes_nothing`, `test_clash_skip`, `test_clash_rename` (`(2)`, and `(3)` when `(2)` exists),
   `test_clash_replace_keeps_position`.
10. `test_case_only_difference_warns`.
11. `test_select_palettes` (unknown name raises).
12. `test_export_merges_sources`: two sources with a clash, each policy; output `.tps` and `.style.json`.
13. `test_import_into_tps_keeps_unknown_content`: an unknown element and the `<preference>` survive unchanged.
14. `test_never_overwrites`: input as output, existing output, wrong suffix; `test_twbx_members_copied` (use
    `tests/fixtures/test_for_zip.twbx`).
15. `test_does_not_touch_marks`: after import, every `datasource/style` and worksheet `style` subtree is byte-equal.
16. `test_non_latin_palette_name` (for example `品牌色`) round trips through `.tps`, JSON and a workbook.
17. `test_workbook_bytes_refactor`: `tests/test_rename.py` passes unchanged.
18. `tests/test_cli.py`: `style show`, `export` to both formats, `import` without `--write` (writes nothing) and with
    it, `check`, and exit codes 0, 1, 2.
19. `tests/test_corpus.py::test_style_palettes_on_every_workbook`: for all 200 workbooks, `read_palettes` never raises;
    a self-import is all `skip-identical` with an equal tree; the 3 workbooks with palettes export to a `.tps` that
    `check_style_file` accepts and that re-reads to the same palettes; importing those palettes into every workbook
    (`on_clash="skip"`) adds no new schema errors (`new_schema_errors`). Failures go to a named known-issues list in the test, not a skip.

Run: `PYTHONPATH=. /home/claude-user/ai-sandbox/py-tbparse/.venv/bin/python -m pytest -q tests/test_style.py
tests/test_cli.py tests/test_rename.py`, then the corpus file with `nice -n 10 timeout 600`.

## 7. Files, docs and what is deferred

- Create: `py_tbparse/style.py`, `tests/test_style.py`, `tests/fixtures/style/{palettes.twb,Preferences.tps,bad.tps}`,
  `docs/styles.md` (guide: what it does, the "recolours nothing" warning, where `Preferences.tps` lives, restart).
- Change: `py_tbparse/rename.py` (`_workbook_bytes`), `py_tbparse/cli.py`, `py_tbparse/__init__.py`,
  `tests/test_cli.py`, `tests/test_corpus.py`, `docs/cli.md`, `README.md` (Guides link, Limits: "palettes only;
  follows what Tableau writes; not opened in Tableau"), `docs/verify-in-tableau.md` (add the check in Q4).
- Do not touch `pyproject.toml`, the version, `webui/` or the GUI.

Deferred, in this order, with the reason:
1. **Slice 1b, inline ramps**: `--include-inline` exports `encoding/color-palette name=""` with a generated name
   `"<workbook stem> <field caption> ramp"` (dedup with `(n)`). Small, but needs a naming rule and the field caption
   lookup; 10 workbooks have them.
2. **Slice 2, formatting transfer** (`extract_style` / `apply_style` from the roadmap): workbook `style-rule`s,
   dashboard `zone-style` matched by zone role (title, container, sheet), and a whitelist of name-free sheet formats
   (fonts, colours, borders on `header`, `label`, `title`, `scope=rows|cols` formats). Deferred because: 680 of 1711
   sheet rules carry `field=` and need a mapping; Tableau's merge order between workbook, sheet and zone rules is
   unknown; presence in the XML does not mean the user chose it (no default marker), so "respect user overrides" has
   no reliable test; workbook-level style is almost unused (7 wbs), so we would write what Tableau rarely writes.
   Needs owner answers Q3 and one Tableau check before design.
3. **Slice 3, `--with-style`**: with only palettes it would just embed palettes in the template, which slice 1
   already does for any workbook; it also touches the template manifest owned by WP1-WP3. Revisit with slice 2.
4. **Never (or a separate WP)**: recolouring marks (data-bound `map/bucket` per field and value, 98 wbs); device
   layouts (97 of 98 auto-generated, name sheets); bitmap zones (local paths and packaged assets); column
   `default-format` (per field); fonts as a workbook default (fonts live on leaves; availability unverifiable);
   Power BI theme conversion (out of scope in the roadmap); a GUI view.

## 8. Risks and unverified assumptions

Risks:
- Users expect "apply style" to recolour their workbook. Mitigation: the fixed CLI line, the guide, the README.
- No real `.tps` was ever seen. Mitigation: keep unknown content, hardened parser, `check`, Q4 manual check.
- Corpus evidence is thin (3 named palettes), so tests rest on hand-made fixtures.
- lxml re-serialises the whole workbook (quoting, whitespace), as rename already does; WP8 owns byte fidelity.
- `rename._workbook_bytes` may collide with WP6's identical refactor; resolve at merge, keep one helper.

Unverified in Tableau (none of this has been opened in Tableau Desktop):
1. A `.tps` written as in section 2 is read after a restart, and its palettes appear in Edit Colors (at most 20 shown).
2. A palette in a workbook's `<preferences>` is offered in that workbook's picker on a machine whose `.tps` lacks it.
3. `custom="true"` is optional; 8-digit (alpha) colours are accepted in a `.tps`.
4. Picker order follows file order; palette names are compared case-sensitively; what Tableau does when a workbook
   palette and a `.tps` palette share a name.
5. Adding or replacing a palette leaves existing marks unchanged (strongly suggested by finding 3, not observed).
6. A `<preferences>` inserted at the 2026.2 XSD position also loads in older Tableau versions.
7. A palette name equal to a built-in one (for example "Tableau 10") does not break the picker.

## 9. Questions only the owner can answer (recommended default in brackets)

- **Q1** Default clash policy for palettes with the same name and different colours. [`fail`, with the message
  suggesting `--on-clash replace` for "new version of our palette" and `rename` for "keep both".]
- **Q2** May `style import` update a user's real `Preferences.tps` in place (with a `.bak` copy), or always write a new
  file beside it? [Always a new file; the user copies it. Keeps the "never overwrite inputs" rule.]
- **Q3** Is slice 2 (formatting transfer) wanted at all, given the unknown merge rules and boilerplate noise?
  [Decide after slice 1 ships and Q4 is done; do not start it before.]
- **Q4** Can you run one 5-minute check in Tableau Desktop: drop an exported `.tps` in the repository, restart, look
  for the palettes; open a workbook with an imported palette. [Yes, before the release that ships slice 1; it settles
  assumptions 1, 2 and 5.]
- **Q5** Release: does slice 1 ship as its own 0.5.x or together with WP6? [Its own 0.5.x after WP6; no version bump
  in this branch until you ask for a merge.]
