# Spec C5: #84 WP4, the layout panel on a phone, in every colour theme, and its docs

Track: #84 layout preview. Plan: [plan-84-layout-preview.md](../plan-84-layout-preview.md) ("Phone layout", "WP4", "Keyboard and screen reader"). Common rules: [README.md](README.md#common-rules-for-every-spec) (follow the agent rules file). GUI rules: `AGENTS.md` "Testing the GUI" (tokens, contrast test, themes).

- Branch: `feat/layout-preview-phone`
- PR title: `Layout panel on a phone and in every colour theme; docs for the preview (#84, WP4)`
- PR body starts with: `Refs #84`. The last package of the preview: say that #84 can be closed by the owner after this merges (WP5 was dropped on 2026-10-18), not "Closes #84".
- Depends on: C4 (WP3) merged.

## Re-read first

The merged `layout.js`, the `.lpanel`/`.lp-*` rules in `py_tbparse/webui/app.css`, and `tests/test_gui_layout_preview.py`. At #215's head (`a307526`) the CSS already puts the panel under the table below 1000 px (`@media (max-width: 999px)`: `.body-split` becomes a column) and caps the list at `max-height: 42vh`. The order inside the panel is header, facts, count, then the body that `render` fills (drawing, note, legend, list: read `drawn()` in `layout.js` for the real order on `main`).

## What this package adds

1. **Phone order (under 760 px):** inside the panel body the order is list, then note, then drawing (plan: "the list is the content"). Do it with CSS (`order` on the three blocks inside a flex column, under `@media (max-width: 760px)`), not by building the DOM twice, so the reading order for a screen reader matches what is shown: if `order` would make the visual order differ from the DOM order, change the DOM order in `render` for narrow widths instead (read `matchMedia('(max-width: 760px)')` once per render and on change), and say which you chose.
2. **No sideways scroll at 375 px** with the WP2 fixtures `mixed_overlap_workbook`, `huge_extent_workbook` and `many_overlap_workbook` open.
3. **Themes:** every colour theme in `webui/themes.css`, light and dark: the zone fills (including the 0.55 fill of crossing zones over each other), outlines, the halo, the selection overlay, labels with their stroke, the dashed frame and the 100000 marker keep contrast. Use tokens only; `tests/test_webui_tokens.py` checks pairs in the CSS. For the drawn shapes, add the computed check below.
4. **Docs** (below).

## Tests (`tests/test_gui_layout_preview.py`, Chromium)

At 375 px wide (a `phone` fixture next to `wide`, like the cards' phone test in `tests/test_gui_cards.py`):

- `test_phone_has_no_sideways_scroll` (parametrised over the three fixtures): `document.documentElement.scrollWidth <= innerWidth`.
- `test_phone_panel_is_under_the_table_and_list_comes_first`: the panel's top is below the table's bottom; inside the panel the list's top is above the note's top, which is above the drawing's top.
- `test_phone_labels_fall_back_on_screen_pixels`: with `nested_workbook`, names that showed at 1360 px are letters or nothing at 375 px, no two label boxes intersect, and the note's "names not shown" count is higher than at 1360 px.
- `test_note_wraps_and_is_not_clipped`: repeat the text-spacing check of `tests/test_gui_layout.py` (find it there; it sets `line-height`, `letter-spacing`, `word-spacing` per WCAG 1.4.12) with the note on screen: the note's `scrollHeight <= clientHeight` or it grows, and nothing overflows the panel.
- `test_wide_panel_is_beside_the_table`: at 1360 px the panel's left is right of the table's left edge plus half the table width (beside, not under).
- `test_cards_phone_test_still_passes`: run the existing cards phone test unchanged (no new test; list it in the PR as run).
- `test_axe_in_every_theme_with_overlap` (parametrised over every theme id in `webgui.THEMES` and both modes): axe as in `test_the_cards_view_passes_the_accessibility_checks_in_both_modes`, with `mixed_overlap_workbook`'s panel open and a zone selected.
- `test_drawn_contrast_in_every_theme`: for each theme and mode, read the computed `stroke` of a `.dzone` outline and the panel background, and the computed `fill` of label text and its stroke, and assert a contrast ratio of at least 3:1 for outlines (WCAG 1.4.11, non-text) and 4.5:1 for label text against its halo stroke colour. Reuse the contrast helper the browser tests already have (search `tests/test_gui_a11y.py` for "contrast").

Memory: these are many browser runs; check `free -m`, run this file alone with `nice` and `timeout`, and skip it under 1.5 GB (say so).

## Docs

- `docs/gui.md`, Dashboards: the preview (what the drawing and the list show; the overlap hints; "a sketch from stored positions, not how Tableau draws it"; the census numbers: overlapping zones in 29 percent of the corpus dashboards, 39 of 135; no zone in the corpus has a floating attribute, so the preview has no floating rule; the 200-zone cap as "N largest of M"; the overlap sentence only above 5 crossing pairs; the phone order).
- `README.md` user's guide, "Dashboards" section: one paragraph for the panel (click or Enter on a row; arrows; Escape; "All columns"; the provisional note). README images stay absolute URLs; do not retake screenshots (owner rule: only at a major release).
- `docs/design/84/README.md`: the option-B status line -> "built (#215 and the WP3/WP4 PRs)".
- `docs/plan-84-layout-preview.md`: a status line at the top: WP2 to WP4 built, WP5 dropped, and the "Questions for the owner" section marked answered (2026-10-16 and 2026-10-18, as recorded on #84).
- `AGENTS.md`: the Dashboards paragraph (layout panel on phones, themes).
- `docs/ROADMAP.md`: C4, C5 rows -> built.

## How to verify

```bash
PYTHONPATH=$PWD /home/claude-user/ai-sandbox/py-tbparse/.venv/bin/pytest -q tests/test_webui_tokens.py tests/test_webgui.py tests/test_layout_fixtures.py
free -m && PYTHONPATH=$PWD nice -n 10 timeout 2400 /home/claude-user/ai-sandbox/py-tbparse/.venv/bin/pytest -q tests/test_gui_layout_preview.py tests/test_gui_cards.py tests/test_gui_layout.py
```

then the whole non-browser suite.

## Not verifiable here

- A screen-reader pass (none on this machine): ask the owner to try the panel with one (NVDA or VoiceOver) and report.
- A comparison of a few real dashboards with Tableau Desktop: the owner's, not claimed.
- Real phones and tablets: only Chromium at 375 px is tested.

## Risks

- CSS `order` that makes visual and reading order differ is an accessibility bug; prefer the DOM order change if in doubt.
- The 0.55 fills over each other can fail contrast in a dark theme; the computed test is the guard. If a theme fails, change its tokens, not the opacity rule, and say so.

## Definition of done

Phone order, no sideways scroll, axe and drawn-contrast tests in every theme, docs and status lines, CI green (including `gui`), no version bump.
