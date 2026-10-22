# Spec B5: WP7-2e, corpus smoke test and the GUI Formatting card

Track: WP7 slice 2. Plan: [wp7-style-plan-slice2.md](../wp7-style-plan-slice2.md) sections 7 (GUI) and 8 "WP7-2e". Common rules: [README.md](README.md#common-rules-for-every-spec) (follow the agent rules file). GUI rules: `AGENTS.md` "Testing the GUI" and the Styles view paragraph.

- Branch: `feat/wp7-slice2-2e`
- PR title: `Styles view: a Formatting card to read and apply fonts and dashboard formats; corpus smoke test (WP7-2e)`
- PR body starts with: `Refs roadmap card: Templates style templates slice 2 (WP7-2e)`
- Depends on: B3 (2c) merged. If B4 (2d) is merged too, include the `sheets` scope in the card and the corpus test; if not, leave sheets out and say so. Re-read the `style.py` API on your base (`extract_style`, `format_table`, `plan_style`, `build_styled`, `STYLE_PLAN_COLUMNS`) before starting. Next: B6 (2f).

It is one PR (the plan's package). If the diff passes about 800 lines, split it: corpus test first (small, no browser), then the GUI; say so in both PRs.

## Part 1: corpus smoke test

In `tests/test_corpus.py`, next to `test_style_palettes_on_every_workbook` (around line 255; same `FILES`, `KNOWN_STYLE_ISSUES`, `schema_check.new_schema_errors` imports), add `test_style_formats_on_every_workbook(tmp_path)`:

1. For every corpus workbook not in `KNOWN_STYLE_ISSUES`: `extract_style(parser, scopes=S)` never raises (`pytest.fail` with the file name and the exception, as the palette test does), where `S` is `("workbook", "dashboards")` plus `"sheets"` if 2d is merged.
2. Self-apply with the default policy: `build_styled(parser, extracted, scopes=S)` gives a tree equal to the input (`etree.tostring` of the root), and `plan_style` has only `same`, `skip`, `no-target` actions.
3. With `force=True`, self-apply is a no-op for the `workbook` scope only (plan: for dashboard roles the modal summary differs from single zones, so it is not required there). Assert it for `scopes=("workbook",)`.
4. Pick one fixed target (`tests/fixtures/style/format-bare.twb`). For every corpus workbook whose extracted style has any formatting, `build_styled(target, extracted, scopes=S)` adds no schema error: `new_schema_errors(target, data) == []`. Collect failures in a list and fail once at the end with all names, so one run shows every problem.
5. Known failures go into a named list (a new `KNOWN_FORMAT_ISSUES = {...}` with a comment per entry saying why), never a skip.

Cost: the palette test takes the corpus once; this one roughly three times. Measure the time on this machine with the corpus fetched (`nice -n 10 timeout 1800`, a log) and put it in the PR. Corpus tests run only locally and in `corpus.yml` (not in PR CI); say whether you ran it.

## Part 2: GUI Formatting card

### Server (`py_tbparse/webgui.py`, Styles section around line 1060)

New endpoints (plan section 7), all for the open workbook, none takes a path, none writes a file:

| Route | Method | Body keys (`_STYLE_KEYS`) | Answer |
| --- | --- | --- | --- |
| `/style/formats` | GET | query `q`, `offset`, `limit` | `{total, matching, offset, limit, rows}` from `style.format_table(_STATE["parser"], scopes=...)` (rows of `FORMAT_COLUMNS`), paged at `STYLE_PAGE` = 100, plus `mixed` (first 100) and `counts` from the extract report |
| `/style/format-plan` | POST | `scopes`, `force`, `on_clash`, `offset`, `limit` | `{counts, total, offset, limit, rows, blocked, boilerplate_kept}` from `style.plan_style(parser, <uploaded style>, ...)`; `blocked` true when any row is `fail`; rows are `STYLE_PLAN_COLUMNS` |
| `/style/format-apply` | POST | `scopes`, `force`, `on_clash` | the bytes of `style.build_styled(...)` as a download named `<stem>_styled<ext>`, header `X-Style-Applied` (count of `add`+`force`) |
| `/style/format-export` | POST | `scopes`, `name` | the bytes of the extracted style (`extract_style` then `json.dumps(..., indent=2, ensure_ascii=False, sort_keys=True)`), named like `_style_filename(name, "style")` |

- Add the four routes to `_STYLE_KEYS` (POST ones) and to the GET dispatch (near `/style/palettes`, around line 1586). `_JSON_ROUTES` is built from `_STYLE_KEYS`, so the POST ones are covered by the JSON size cap.
- Validate payloads like `_style_policy`: `scopes` a list of strings from `FORMAT_SCOPES`, default `["workbook", "dashboards"]`; `force` a boolean, default `false`; `on_clash` in `FORMAT_CLASH_POLICIES`, default `"skip"`; `force` with `on_clash="fail"` is refused (the library raises `StyleError`; the handler turns it into 400).
- **The uploaded style.** `/style/upload` keeps only palette records today (`_style_upload` calls `style.palettes_from_bytes`). For a `.style.json` upload, also keep the checked style dict: add a public helper in `style.py`, `style_from_bytes(data, filename) -> dict` (parse JSON with `utf-8-sig`, `_check_style`; refuse a `.tps` with "a .tps holds palettes only; use a .style.json for formatting"), store it as `_sty_state()["style"]`, and include `has_formatting: bool` in the upload answer. `/style/format-plan` and `/style/format-apply` answer 400 "Add a .style.json with formatting first." when it is missing. Add `style_from_bytes` to `__all__` and a `docs/api.md` bullet.
- `_sty_state()` gets `"style": None` in its default dict; `/style/clear` already drops the slot.
- Server mode: these routes take no path, so they are allowed (like `/style/export`); `tests/test_server_mode.py` lists allowed routes: check whether it needs the new ones.

### Page (`py_tbparse/webui/styles.js`)

A third card **Formatting** below the two palette cards (`sectionOne`, `sectionTwo`; add `sectionThree` and call it from `draw`). Same rules as the palette cards (`AGENTS.md`): `textContent` only, tokens from `tokens.css`, no new JS file (so the script count in `index.html` and its test stay the same).

- **What this workbook has**: a paged pseudo-table of `/style/formats` rows, 100 per page, Previous/Next, a search box (`q`), grouped by the `section` column (fonts, workbook rules, dashboard roles, dashboard rules, sheet defaults). Never the whole table in the DOM. A colour value shows a chip **and** the hex as text (plan: "every colour shown has its hex in text"). A "Download as style file" button calls `/style/format-export`.
- **Apply from a file**: uses the existing upload (the palette card's file block): when the upload answer says `has_formatting`, this card shows scope checkboxes (Workbook, Dashboards, Sheets if built; default the first two), a **Replace formats the workbook already has (--force)** checkbox, **off** by default, and the skip/fail choice (default skip). The plan table with counts per action is shown (paged, 100 rows) **before** the download button is enabled; `blocked` disables the download and says why. **Download new workbook** posts `/style/format-apply` and saves the bytes (reuse `save()` in `styles.js`).
- The card repeats the fixed line: "Adds or changes formats; recolours no marks; not opened in Tableau." When `boilerplate_kept` is non-zero it shows the same sentence as the CLI (2c).
- Dark theme and the other colour themes work (tokens only); 390 px width has no sideways scroll.

### Tests

Non-browser (`tests/test_webgui_styles.py`, using its `server` fixtures):

- `test_formats_endpoint_pages_and_counts`: `/style/formats` on `format-source.twb` returns at most 100 rows, the right `total`, and colour rows carry the hex.
- `test_format_plan_needs_a_style_with_formatting`: before an upload 400; after uploading `format.style.json` 200 with counts; after uploading a `.tps` 400 with the message.
- `test_format_plan_default_is_skip_and_force_off`: no keys -> `on_clash` skip, `force` false, `blocked` false on `format-target.twb`.
- `test_format_apply_downloads_bytes_and_writes_nothing`: the answer is a workbook that `TwbParser` reads, the open workbook file on disk is byte-equal before and after, and no new file appears next to it.
- `test_format_keys_are_whitelisted`: an unknown key is 400; a `path` key is 400.
- `test_force_with_fail_is_refused`: 400 with the library's message.
- `test_format_export_is_a_v2_style_file`: the download parses with `load_style` semantics (`_check_style`) and has `version` 2.

Browser (`tests/test_gui_styles.py`; Chromium: this spec asks you to run this one file; check `free -m` first and skip it under 1.5 GB, saying so):

- `test_formatting_card_lists_formats_one_page_at_a_time`: at most 100 rows in the DOM, paging works, a colour cell has hex text.
- `test_formatting_plan_before_download`: after uploading `format.style.json`, the download button is disabled until the plan is shown; force is unchecked by default.
- `test_formatting_card_dark_and_phone`: contrast checks in both modes as `test_contrast_in_both_themes_with_a_clash_report` does, and no sideways scroll at 390 px as `test_a_phone_gets_a_readable_page_without_sideways_scroll` does.
- `test_no_path_in_any_payload`: intercept the page's requests (Playwright `page.on("request")`) while using the card and assert no body has a `path` key.

Screenshots: `scripts/gui_screenshots.py` captures the Styles view (files 12 to 23 in `AGENTS.md`); retake only at a major release (owner rule), not here.

## Docs

- `docs/gui.md`: the Styles view paragraph gets the Formatting card.
- `README.md` user's guide, "Styles" section: one paragraph for the card ("adds or changes formats; recolours no marks; not opened in Tableau").
- `AGENTS.md` Styles view paragraph: the four routes, `_sty_state()["style"]`, `style_from_bytes`.
- `docs/api.md`: `style_from_bytes` bullet.
- `docs/ROADMAP.md` B5 row.

## How to verify

```bash
PYTHONPATH=$PWD /home/claude-user/ai-sandbox/py-tbparse/.venv/bin/pytest -q tests/test_webgui_styles.py tests/test_server_mode.py tests/test_webgui.py tests/test_webui_tokens.py tests/test_api_doc.py
free -m && PYTHONPATH=$PWD nice -n 10 timeout 1200 /home/claude-user/ai-sandbox/py-tbparse/.venv/bin/pytest -q tests/test_gui_styles.py
python scripts/fetch_corpus.py && PYTHONPATH=$PWD nice -n 10 timeout 2400 /home/claude-user/ai-sandbox/py-tbparse/.venv/bin/pytest -q -m corpus tests/test_corpus.py -k style_formats > /home/claude-user/.claude/jobs/b5d69d0e/tmp/2e-corpus.log 2>&1
node --test tests/js/*.test.js     # only if node is installed; CI runs it (job js-unit)
```

then the whole non-browser suite. CI's `gui` job runs the browser tests.

## Not verifiable here

Tableau: as 2b to 2d (no new kind of output). No screen reader on this machine: ask the owner for a manual pass of the card. GHCR/Docker: the image is built only in CI.

## Risks

- DOM size: dashboards can have 1455 zones in the corpus; the table shows the extracted summary (one row per role and attribute), never one row per zone, and pages at 100.
- The upload slot now holds two things (palette records and the style dict); clearing or replacing it must clear both (test it).
- Corpus run time on a 2-CPU machine; measure and report.

## Definition of done

Corpus test in (and run locally, or the PR says why not), four endpoints with whitelisted keys, the card with plan-before-download and force off, non-browser and browser tests, docs, CI green (including `gui`), no version bump.
