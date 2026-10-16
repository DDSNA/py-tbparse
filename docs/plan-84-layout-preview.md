# Plan: the layout preview for the Dashboards view (rest of #84)

Issue #84 asked for four things after #73: names of filters and parameters, image/text/web zones, per-dashboard cards, and a small layout preview. The names and zone counts shipped in #116, the cards (option A of `docs/design/84/README.md`) in #197. What is left is the **layout preview**, option B of the design note: a large drawing of one dashboard with the zone names, and a list of every zone. This page plans it and changes no code. Everything below was read from `main` at e5dabdd; nothing was run in a browser for this plan, and nothing is verified in Tableau Desktop.

## What #197 already gives the preview

| Piece | Where | Reuse |
| --- | --- | --- |
| All zones of the main layout, flat, in document order, with `kind`, `name`, `x, y, w, h` (`<NA>` when missing) | `dashboards.dashboard_layout`, `TwbParser.get_dashboard_layout(name)` | As is. Device layouts are already left out. Tests in `tests/test_dashboard_cards.py`. |
| Kind mapping and filtering (containers dropped, zones without a full position or with `w` or `h` of 0 or less dropped, kinds folded to `sheet/filter/param/text/bitmap/web/other`) | `webgui._cards_answer`, `_CARD_KINDS` | Move the per-dashboard part into a helper both endpoints call, so cards and preview cannot disagree. |
| Extent of the drawing (`width`, `height` = largest `x+w`, `y+h` of the kept zones) | same | Reuse. The extent is taken from the zones, not from the dashboard size. |
| Sketch SVG: `viewBox`, one `rect` per zone, class `dzone dk-<kind>`, letter in a zone that is big enough, legend, "no positions stored" empty state | `webui/cards.js` (`sketch`, `legend`), `app.css` `.dk-*` | Colours, outline styles and the letter scheme stay the same so a user who knows the card knows the preview. The drawing code is small; share the colour classes, write the larger drawing as a second function in the same file or a new `webui/layout.js` (decision for the WP, see below). |
| Kind letters and the "S F P T I W" legend | `cards.js` `LETTER`, `LEGEND` | Reuse. |
| Page-at-a-time loading, `mine !== req` guard against stale responses | `cards.js` `render` | Same guard for the preview fetch. |

What the cards do not give: names in the zones (the response has no names), nested structure, the zone list, selection, and anything for assistive technology beyond one `aria-label` on the sketch.

## What the preview adds

1. **A big drawing** (about 500 px wide on a desktop, scaling down) of one dashboard, with the name of each zone written in it when it fits (otherwise the letter, otherwise nothing). Names come from `name` of `dashboard_layout`: the sheet name, or the zone's own name. A filter or parameter zone is better named by the field it points at (`filter_fields`, `parameter_names` already compute that through `_zone_field_name`); the plan is to add a `label` column or extend the response with it, decided in WP1.
2. **A zone list** next to or under the drawing: one line per zone with the kind letter, the name, the kind in words, and the position. This list is the real content (see below).
3. **Linked hover and selection.** Hovering or focusing a list line highlights the zone, and the other way round. Clicking a zone or pressing Enter on a line "selects" it: it stays highlighted and the line scrolls into view.
4. **Header facts** for the selected dashboard: size text, counts, filter and parameter names, and the existing **Show its sheets and positions** button (opens Dashboard sheets filtered to it). Optionally **Copy zone list** (tab-separated text).
5. **Where it lives.** The design note's picture: the Dashboards table stays; picking a row opens the panel beside it (under it below 1000 px). In Cards view, the card's sketch could open the same panel. That second entry point is optional (WP5).

## Keyboard and screen reader

- The zone list is the accessible content: a real `<ol>` of `<li>` lines, each readable on its own ("Worksheet, Customer list, position 24, 0, size 76 by 46 percent"). The drawing is `role="img"` with a short label ("Layout of NAME: N zones; the list below has them all") and its zone shapes are `aria-hidden`; no screen-reader user needs the drawing.
- Keyboard: lines are reachable in list order. Plain Tab stops (`tabindex="0"` on every line, as in the mockup) would put up to the zone cap of stops in the page; the plan is a roving tabindex (one stop, arrow keys move, Home/End jump), the way the graph view handles its tables. Enter selects. Escape clears the selection and leaves focus in the list.
- The panel is not a dialog: no focus trap, no `aria-modal`. It is a labelled region (`aria-labelledby` the dashboard name). When a row is picked, focus stays on the row (so arrow keys keep moving through the table) unless the owner decides otherwise (question 1); the panel announces itself with a polite status line ("Layout of Customer detail: 5 zones").
- Hover is never the only way to learn anything: the name, kind and position are in the list, and selection shows by outline thickness and a background, not only colour. Kind is told by letter and outline style as well as colour (as in the cards), and contrast must hold in the dark theme and the other colour themes. None of this has been checked with a screen reader; WP4 includes a manual pass that the plan can only ask for, since no screen reader is available on this machine.
- `prefers-reduced-motion`: no animation on highlight or panel open.

## The row drawer (owner decision)

Today a click or Enter on any table row opens the details drawer with every column (`openRow`, `closeDrawer` in `webui/app.js`, focus moved to the drawer title, Escape closes). Two things on screen answering the same click is confusing, so one of these has to be chosen:

- **Option 1: the panel replaces the drawer on the Dashboards table only.** Row click or Enter selects the row and shows the panel; the full-column details move to a button in the panel header ("All columns"), which opens the existing drawer. Everything else in the app is unchanged. One code path (`openRow`) gets a small hook for this one table.
- **Option 2: the panel sits beside the drawer.** Click opens the drawer as today; the panel is toggled by a **Layout** button in the toolbar and follows the current row. Less change, but then two panels can be open on a 1360 px window and the table gets very narrow.
- **Option 3: panel on selection, drawer on Enter.** Click selects (panel), Enter opens the drawer. Splits mouse and keyboard behaviour; the plan advises against it because keyboard users would get a different thing than mouse users.

The plan recommends option 1 and builds it so that option 2 is a small change (the panel is its own module and does not call the drawer). It is the owner's call; WP3 does not start before it is answered.

## Phone layout

Under 760 px the app already turns lists into stacked cards. For the preview: the panel moves under the table (below 1000 px, as in the mockup), the drawing is full width with `height: auto`, and names inside zones fall back to letters when a zone is under about 40 px wide on screen. On a phone the list comes first and the drawing below it, since the list is the content. No sideways scroll at 375 px (the cards test already asserts this for cards; same assertion for the panel). Tapping a zone selects it; there is no hover on touch, so selection must show everything hover shows. If the drawing is too small to read, the list is the fallback and the plan does not add pinch-zoom.

## Data limits and caps

- The sketch caps at `CARD_ZONES_MAX` = 40 zones, keeping the largest. The preview needs more, because the point is to name every zone. Proposal: `PREVIEW_ZONES_MAX` = 200, same rule (largest kept, `total` says how many there were, the panel says "Showing the 200 largest of N zones"). The list is capped by the same number so list and drawing always agree.
- One dashboard per request (`GET /dashboard-layout?name=...`), never a page of them. Only one drawing and at most 200 list lines are ever in the DOM, so the table's virtual rows stay the only large thing. Any cap on the list itself stays well under the "never render tens of thousands of rows" rule.
- Names are cut at a length (about 60 characters in the list, with the full text in a `title`) and are always set with `textContent`, never `innerHTML`: the mockup builds SVG with `innerHTML` and sheet names are workbook content, so the real code must not copy that.
- Numbers: `x, y, w, h` are whole numbers in Tableau's 0 to 100000 grid for the main layout, as far as the existing tests and code assume. The list shows percent of the extent (`24, 0, 76 x 46 %`) plus the stored values in the tooltip. A dashboard with a fixed pixel size may store pixel positions for floating zones; this is unverified (below).
- Zones with a missing or non-positive size are left out of the drawing but not out of the count: the panel says "N zones have no stored position" and the list still names them, without position.
- The request takes a dashboard name, never a path, and is refused without a workbook, like `/dashboard-cards`. Server mode needs no change (state is per session through `_STATE`).

## Work packages

Each package is one PR, in this order. No package changes `pyproject.toml`'s version; the release bump is separate.

### WP0: corpus check of overlap and odd sizes (script first, no GUI)

Purpose: replace guessing with numbers before drawing anything big. `scripts/layout_census.py`, in the style of `scripts/style_census.py`: reads every `.twb`/`.twbx` in `tests/corpus/files` (fetched with `scripts/fetch_corpus.py`), one file in memory at a time, stdlib + lxml, run with `nice -n 10 timeout 300`, prints Markdown tables, writes nothing but a log. For each of the 135 dashboards, from the main layout only:

- zones per dashboard (distribution, maximum; how many exceed 40 and 200),
- zones with missing, zero or negative `w` or `h`, and with `x`/`y` outside 0 to 100000, or `x+w`, `y+h` over 100000,
- overlap: pairs of leaf zones (not containers) whose rectangles intersect by more than a small area, split into pairs where one zone is `floating` (`is-floating`/`floating` attributes, to be confirmed by the script's first pass over the attribute names) and pairs where neither is,
- containers: how deep zones nest, how many leaves sit inside a container whose own rectangle does not contain them,
- the extent (largest `x+w`, `y+h`) against the 100000 grid, and against the `<size>` of fixed-size dashboards,
- the smallest on-screen size of a zone at 500 px width (how many would get no name).

Acceptance: non-browser. `tests/test_layout_census.py` runs the script's functions on the synthetic fixture from `tests/cards_fixtures.py` plus a hand-made overlapping workbook and checks exact numbers; a corpus test (skipped when the corpus is not fetched, like `tests/test_dashboards_corpus.py`) pins the totals the script found, which the PR states as found, not as expected beforehand. The PR body quotes the tables. The result decides the drawing rules in WP2 (do floating zones need a different rule, does the order of drawing matter, is the 100000 grid safe to assume). If overlap is common, the plan changes before WP2 starts.

### WP1: server side, one dashboard's zones with names

Refactor `_cards_answer`'s per-dashboard zone loop into a shared helper; add `GET /dashboard-layout?name=...` returning `{name, total, zones: [[kind, x, y, w, h, label, zone_id]...], width, height, unplaced, cap}` with `PREVIEW_ZONES_MAX`. Add the field label for filter and parameter zones through `_zone_field_name` (the cards response stays as it is).

Acceptance (non-browser, in `tests/test_dashboard_layout_preview.py`, same server fixture as `tests/test_dashboard_cards.py`):
- a mixed dashboard returns every non-container zone with the right kind, position, and a label (sheet name, field name for a filter, parameter name for a control);
- the cap keeps the largest zones, in layout order, and `total` and `cap` are right (fixture `many_zones=250`);
- a dashboard with no stored positions returns `total` 0 and `unplaced` equal to its zone count;
- an unknown name returns an empty answer or 404 (decided in the PR and tested), more than one name is refused, no workbook gives 400;
- the cards endpoint answer is byte-for-byte what it was before the refactor (the existing tests stay green unchanged);
- a name with quotes and non-ASCII characters round-trips.

### WP2: panel, drawing and list (no table integration yet)

`webui/layout.js` (own closure, like `cards.js`, helpers passed in) with `render(host, info)`: SVG drawing with names fitted by measured width (cut with an ellipsis, never `textLength` stretching as the mockup does, which squeezes glyphs), list, linked hover/selection, roving tabindex, legend and caps note, empty state. CSS in `app.css` using only `tokens.css` variables. A line in `AGENTS.md`'s module table for the new file.

Acceptance, non-browser: `py_compile`-style syntax check is not available for JS here, so the JS is covered by WP2's Playwright tests; non-browser checks are that the served page contains the script tag and that `webgui` serves `layout.js` (extend the static-file test that already lists `cards.js`).

Acceptance, Playwright (`tests/test_gui_layout.py`, marker and skip rules like `tests/test_gui_cards.py`):
- the panel for a mixed dashboard has one SVG with N zone shapes and a list with N lines, same order, each line with kind word and name;
- hovering a zone gives its list line the highlight class and the reverse; focusing a line does the same;
- Enter/click selects and the selected line is `aria-current`, and Escape clears it;
- arrow keys move through the list with exactly one `tabindex=0` line; Home/End work;
- the drawing has `role="img"` and its shapes are `aria-hidden`; the list has an accessible name;
- a 250-zone dashboard shows 200 lines and the cap note, and the DOM node count of the panel stays under a fixed bound;
- a dashboard with no positions shows the empty state and still lists its zones;
- a name with `<script>` text in it renders as text (no injected node);
- axe checks (as in `test_the_cards_view_passes_the_accessibility_checks_in_both_modes`) in light and dark; contrast of zone outlines and selection in all colour themes.

### WP3: Dashboards table integration (needs the owner's drawer decision)

Row selection opens the panel (split layout, under the table below 1000 px); implement the drawer option the owner picks; selection survives sorting and filtering by dashboard name, not by row position; changing table or reloading a workbook closes the panel and cancels the in-flight request (same `req` guard as the cards); focus handling as above.

Acceptance (Playwright): the chosen option's behaviour for click, Enter, Escape and focus return, including that the details drawer still works on every other table; sort and filter keep or clear the selection correctly; the panel updates when the arrow keys move to another row (debounced, so holding a key does not send a request per row: the test counts requests); another workbook loaded clears the panel; the table stays at 50,000-row speed in a workbook with many dashboards (a generated one with several hundred dashboards, rows virtual, one drawing in the DOM).

### WP4: phone layout, themes, docs

Under 1000 px the panel goes under the table; under 760 px list first, drawing under it; no sideways scroll at 375 px; dark theme and the other colour themes. Update `docs/gui.md` (the Dashboards paragraph and the "not compared with Tableau" sentence), the README line, and the option-B status line in `docs/design/84/README.md`. Re-take the GUI screenshots only if a major release is being prepared (owner rule: `scripts/gui_screenshots.py` at major releases).

Acceptance (Playwright): at 375 px no horizontal scroll, panel under the table, list before drawing; at 1360 px panel beside the table; the phone test for the cards still passes; axe in both modes; a manual pass with a screen reader and in Tableau-free review is requested from the owner, not claimed.

### WP5 (optional): open the panel from a card

A button on the card sketch opens the panel for that dashboard in the Dashboards view. Only if the owner wants the two entry points; the card keeps its small sketch.

## What is unverified

- **How Tableau draws nested and floating zones.** The design note and the code treat every zone as a rectangle at its stored `x, y, w, h` and draw them flat. That is an assumption. Tableau stores floating zones with their own attributes, and the unit of their position (the 100000 grid or pixels of a fixed-size dashboard) is not confirmed here; containers with padding and inner margins may shift the visible rectangles of their children. No local Tableau Desktop exists, so the preview cannot be compared with the real thing; the docs must keep saying "a sketch from stored positions, not how Tableau draws it". The plan does not promise otherwise.
- **The corpus check.** Overlap, odd sizes, positions outside the grid, zone counts and nesting depth have not been measured on the 135 corpus dashboards. WP0 does that first, and its numbers can change WP2 (for example drawing order, a separate rule for floating zones, a bigger or smaller zone cap).
- The 200-zone cap is a guess until WP0 gives the real maximum.
- Screen reader behaviour, dark-mode contrast and the other colour themes of the panel: nothing built yet, nothing checked. The mockup was only looked at in Chromium at 1360 px and 375 px.
- Phone and tablet layouts are not drawn (as in the counts and cards); a dashboard whose main layout is empty but which has a phone layout will look empty.
- Whether a debounce of row changes is enough for a server on a slow link: untested.

## Risks

- **Drawing something wrong with confidence.** A big, named drawing looks more authoritative than the 150 px sketch. Mitigation: the caption under it, the cap note, and the numbers from WP0 in the docs.
- **Overlapping zones hide each other.** Floating zones sit on top of tiled ones in Tableau; if WP0 shows overlap is common, the SVG needs a drawing order (larger first, floating last) and the list needs to say "covers" or "is covered by". Otherwise a zone may be invisible in the drawing but present in the list.
- **Drawer interplay** breaks muscle memory on the most used table in the app. Mitigated by choosing an option explicitly, keeping the drawer reachable from the panel, and testing the drawer on all other tables.
- **Narrow table.** Beside the panel the table has about 40 percent of the width; column count and pinned columns may need a scroll. The mockup shows 6 columns; the real table has 12 or more.
- **DOM growth and request storms.** One drawing, at most 200 list lines, a request per selected row with a stale-response guard and a debounce. A bug here is what killed earlier sessions, so WP3 has a test that counts nodes and requests.
- **Script injection through names.** Handled by `textContent` only; tested in WP2.
- **Duplicate facts** (cards, table, panel) drifting apart. Mitigated by the shared server helper and by one test comparing the zone counts of cards and preview.
- **Size of the work.** The design note says medium to large. WP0 and WP1 are small and safe to merge alone; WP2 and WP3 are the bulk.

## Questions for the owner

1. Row drawer: should the panel replace it on the Dashboards table (option 1, recommended), sit beside it behind a **Layout** button (option 2), or something else? WP3 waits for this.
2. Should the preview go ahead at all now that the cards exist, or is the cards view enough until the corpus check (WP0) is done? WP0 and WP1 are cheap either way.
3. When a row is picked, should focus stay on the row or move to the panel? The plan keeps it on the row so arrow keys keep working.
4. Do you want the second entry point from a card (WP5)?
5. Is a zone cap of 200 acceptable, shown with "N largest of M", or should the list always show every zone, paged?
