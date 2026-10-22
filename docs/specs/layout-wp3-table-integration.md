# Spec C4: #84 WP3, the layout panel and the Dashboards table work together

Track: #84 layout preview. Plan: [plan-84-layout-preview.md](../plan-84-layout-preview.md) ("WP3", "Keyboard and screen reader", "The row drawer", "Risks"). Common rules: [README.md](README.md#common-rules-for-every-spec) (follow the agent rules file). GUI rules: `AGENTS.md` "Testing the GUI".

- Branch: `feat/layout-preview-table`
- PR title: `Layout panel: follows the arrow keys with one request, keeps its dashboard through sort and filter, Escape closes it (#84, WP3)`
- PR body starts with: `Refs #84`
- Depends on: **PR #215 (WP2) merged.** Next: C5 (WP4).

## Re-read first (WP2's merged shape)

This spec was written against #215's head `a307526` (branch `feat/layout-preview-panel`). Before you start, read on `main`:

- `py_tbparse/webui/layout.js`: `window.LayoutPanel = { init, show, hide, render, analyse, OVERLAP_NOTE_MIN, SHARE_MIN, MIN_PX }`; `show(panel, row, cb)` with `cb = { allColumns(button), close() }`; its own `req` counter guards late answers; a 404 shows "This dashboard is no longer in the workbook."; `hide(panel)`.
- `py_tbparse/webui/app.js`: `state.panelIdx` (an index into `state.data`, so it survives sorting), `openRow(pos)` sends the Dashboards table to `openLayoutPanel(idx)`, `closeLayoutPanel(restoreFocus)`, `openDrawerFor(idx)`; `selectTable`, `setDashboardView` and `resetCaches` call `closeLayoutPanel(false)`.
- `py_tbparse/webui/table.js`: `VTable.onRowKey` (Enter/Space call `h.openRow`; arrows, Page keys, Home/End call `focusRow`, no callback), `focusRowByIndex`, `setCurrent`.
- `py_tbparse/webui/index.html`: `#bodySplit` holding `#tableWrap` and `section#layoutPanel`.
- `tests/test_gui_layout_preview.py` (37 browser tests in #215) and `tests/layout_fixtures.py`.

If any of these changed in review, follow the merged code and say in the PR where this spec no longer matched.

## What WP2 already did (do not redo)

Row click or Enter opens the panel instead of the drawer on the Dashboards table; focus stays on the row (owner decision 2026-10-18); "All columns" opens the drawer; other tables keep the drawer; changing table closes the panel; late answers are ignored; the 404 message.

## What this package adds

1. **Arrow keys update the panel, debounced.** While the panel is open, moving the focused row on the Dashboards table (arrows, Page Up/Down, Home/End) shows that row's dashboard in the panel after the keys stop for `PANEL_DELAY` = 250 ms. Holding a key sends one request, not one per row.
   - `table.js`: give `VTable` an optional handler `moved(pos)` called from `onRowKey` after `focusRow(target)` (only when the position changed). Default no-op, so other tables are untouched.
   - `app.js`: in the `VTable` options pass `moved: (pos) => panelFollow(pos)`; `panelFollow` does nothing unless `state.table === 'dashboards'` and the panel is open; it clears and sets a timer (`PANEL_DELAY`), then calls `openLayoutPanel(vt.order[pos])` if the row's index differs from `state.panelIdx`.
   - Focus stays on the row (do not move it to the panel).
2. **Selection survives sorting, by dashboard, not by position.** After a sort the panel keeps its dashboard and the `aria-current` row is the same dashboard at its new position (`state.panelIdx` is a data index, so check that `setCurrent` is re-applied after `renderTable`).
3. **Filtering.** When the search box or a column filter hides the selected row, the panel closes (`closeLayoutPanel(false)`) and a polite status says "The layout panel closed: its dashboard is filtered out." When the row stays visible, the panel stays. This is this spec's choice for the plan's "keep or clear correctly"; it is easy to change, so say it in the PR body.
4. **Escape.** Escape with focus on a Dashboards table row while the panel is open closes the panel and keeps focus on that row. Inside the panel's zone list, the first Escape clears the zone selection (WP2 behaviour) and a second Escape closes the panel and returns focus to the row (`closeLayoutPanel(true)`). Escape inside the drawer still closes only the drawer.
5. **Reload and other workbook.** Opening another workbook or reloading the same one closes the panel and cancels the request (WP2's `resetCaches` path; add a test). If a stale panel asks for a dashboard that no longer exists, the 404 message shows (WP2) and the row selection is cleared.
6. **Cards mode.** Switching the Dashboards view to Cards closes the panel (WP2's `setDashboardView`); switching back does not reopen it.

No server change. No new file.

## Tests (`tests/test_gui_layout_preview.py`, Chromium; reuse its `wide` fixture and `tests/layout_fixtures.py`)

Write a builder `many_dashboards_workbook(n=300)` in `tests/layout_fixtures.py` (one small dashboard each, each with two zones; names `D001` ...) for the speed and request tests.

- `test_arrow_keys_update_the_panel_after_a_pause`: open the panel on row 1, press ArrowDown once, wait 400 ms: the panel title is row 2's name; focus is still on the table row.
- `test_holding_a_key_sends_one_request`: count `page.on("request")` hits to `/dashboard-layout` while pressing ArrowDown 10 times with 20 ms between presses (`many_dashboards_workbook`); after 400 ms, exactly one new request, for the final row.
- `test_sort_keeps_the_dashboard`: open the panel on dashboard X, sort by name descending: the panel title is still X and the `aria-current` row is X.
- `test_filter_that_hides_the_row_closes_the_panel`: type a filter that excludes X: the panel is hidden and the status line says so; a filter that keeps X keeps the panel.
- `test_escape_closes_the_panel_and_keeps_focus_on_the_row`: Escape on the row hides the panel; `document.activeElement` is that row.
- `test_escape_in_the_list_first_clears_then_closes`: select a zone line, Escape clears it (WP2), Escape again closes the panel and focuses the row.
- `test_all_columns_drawer_is_unchanged`: "All columns" opens the drawer, and for every column of the Dashboards table its value in the drawer equals the row's value in the table (read the table values with the column menu's "Copy column values", as `_copy_column` in the browser tests does); Escape closes only the drawer and the panel stays open.
- `test_drawer_still_works_on_every_other_table`: for each other table of the fixture workbook, click the first row: the drawer opens, no panel.
- `test_other_workbook_clears_the_panel`: open the panel, load another workbook through the page: the panel is hidden and no request is pending (`page.wait_for_load_state("networkidle")`).
- `test_overlap_state_does_not_leak` (plan): select an overlapping dashboard (`mixed_overlap_workbook`), then a clean one: the note has only the standing sentence, the frame is solid, no hint text in the list; repeat with the first answer delayed (route `/dashboard-layout` for the first name with a 500 ms delay) and the second row selected before it arrives.
- `test_many_dashboards_keep_one_drawing`: with `many_dashboards_workbook(300)` open and the panel shown, the page has one `svg.lp-svg`, and the panel's descendant count stays under a fixed bound (measure it once with the 200-zone fixture of WP2 and set the bound at that number plus a margin; write the number in the test).

Memory: check `free -m` before running the browser file; skip under 1.5 GB and say so. Run only `tests/test_gui_layout_preview.py`, `tests/test_gui_table.py` and `tests/test_gui_a11y.py` (the table and focus rules); CI's `gui` job runs the rest.

Node unit tests (`tests/js/`): if `panelFollow` or the filter check is a top-level function in `app.js`, add a case to the Node tests (`tests/js/load.js` lifts named top-level functions; read `tests/js/*.test.js`). If node is not installed here, say so; CI's `js-unit` job runs them.

## Docs

- `docs/gui.md`, Dashboards paragraph: the keyboard behaviour (arrows update the panel after a pause, Escape closes it, sort keeps it, a filter that hides the row closes it).
- `AGENTS.md`: the Dashboards paragraph (cards and layout panel): `moved` hook on `VTable`, `PANEL_DELAY`, the filter rule.
- `docs/ROADMAP.md` C4 row.

## How to verify

```bash
PYTHONPATH=$PWD /home/claude-user/ai-sandbox/py-tbparse/.venv/bin/pytest -q tests/test_webgui.py tests/test_dashboard_layout_preview.py tests/test_layout_fixtures.py
free -m && PYTHONPATH=$PWD nice -n 10 timeout 1800 /home/claude-user/ai-sandbox/py-tbparse/.venv/bin/pytest -q tests/test_gui_layout_preview.py tests/test_gui_table.py tests/test_gui_a11y.py
```

then the whole non-browser suite.

## Not verifiable here

No screen reader on this machine: whether "focus stays on the row" plus a polite status reads well is for the owner to try. The drawing is not compared with Tableau Desktop (plan, "What is unverified").

## Risks

- Request storms and DOM growth killed earlier sessions: the request-count and node-count tests are the guard; never render all 300 dashboards' drawings.
- `table.js` is shared by every table: the `moved` hook must default to a no-op, and `tests/test_gui_table.py` must pass unchanged.

## Definition of done

The six behaviours above with their tests, docs, CI green (including `gui` and `js-unit`), no version bump.
