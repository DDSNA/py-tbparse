# Plan: the layout preview for the Dashboards view (rest of #84)

Issue #84 asked for four things after #73: names of filters and parameters, image/text/web zones, per-dashboard cards, and a small layout preview. The names and zone counts shipped in #116, the cards (option A of `docs/design/84/README.md`) in #197. What is left is the **layout preview**, option B of the design note: a large drawing of one dashboard with the zone names, and a list of every zone. This page plans it and changes no code.

Status: **WP0 (corpus census, #209), WP1 (`GET /dashboard-layout`, #211) and WP2 (the panel) with the row hook of WP3 (#215) are merged.** The rest of WP3 (arrow keys and filter updating the panel, sort and filter keeping the selection) and WP4 are not started. This revision (against `main` at e1d9aea) replaces the guesses of the first plan with the census numbers in `docs/layout-census.md` and changes WP2 to WP4 so that overlapping zones are drawn and listed honestly. Nothing was run in a browser for this plan, and nothing is verified in Tableau Desktop.

## Owner decisions already made

- **The panel replaces the row drawer on the Dashboards table** (option 1 below). The full-column details move to an "All columns" button in the panel header. Every other table keeps the drawer.
- **The zone cap is 200, shown as "N largest of M"** (not paged). The list and the drawing use the same cap.

## What the census found (and what it did not)

From `docs/layout-census.md` (200 workbooks, 135 dashboards, main layouts only, counts only):

| Finding | Number | What it means for the preview |
| --- | --- | --- |
| Dashboards with at least one overlapping pair of leaf zones | 39 of 135 (29%) | Overlap is the normal case to design for, not an edge case. |
| Overlapping pairs | 255: 96 nested (one rectangle completely inside the other), 159 partly crossing | Two different looks are needed. |
| Overlapping pairs with a text or image zone | 111 | A label or a picture often sits on a bigger zone. |
| Explicit floating attribute on any zone | none in the corpus | Floating was only a proxy (leaf directly in a non-root `layout-basic`: 70 of the 255 pairs). The preview has **no** floating rule and must not claim one. |
| Largest dashboard | 40 leaf zones (59 with containers); 0 over 40, 0 over 200 | The 200 cap has a factor of 5 to spare in the corpus. The cap path can only be tested with generated fixtures. |
| Extent past 100000 | 11 of 129 dashboards with placed zones (21 zones); 7 of them have a fixed pixel size | The 0 to 100000 grid is not safe to assume. |
| Negative `x` or `y` | 5 zones in 3 dashboards | The drawing must include them, not clip them. |
| Zones narrower than 40 px at 500 px wide | 38 of 821 (4.7%), in 21 dashboards (15.6%) | The letter fallback is regular but rare. |
| Zones narrower than 5 px at 500 px wide | 12 (1.5%); narrowest 0.5 px | Some zones would be invisible at true size. |
| No full position | 10 zones in 1 dashboard | "N zones have no stored position" is needed but rare. |
| Nesting | median depth 4, deepest 16; leaves never stick out of their parent container's rectangle | Flat drawing of leaves at their stored positions does not push children out of containers. |

Not measured, so unknown: whether the 159 partial crossings are real covering in Tableau or come from how Tableau stores layouts (padding, relative positions); the unit of positions outside the grid; Tableau's own drawing order; container padding and margins; zone-name lengths. See "What is unverified".

## What #197 and WP1 already give the preview

| Piece | Where | Reuse |
| --- | --- | --- |
| All zones of the main layout, flat, in document order, with `kind`, `name`, `x, y, w, h` (`<NA>` when missing) | `dashboards.dashboard_layout`, `TwbParser.get_dashboard_layout(name)` | As is. Device layouts are left out. Tests in `tests/test_dashboard_cards.py`. |
| Kind mapping and filtering (containers dropped, zones without a full position or with `w` or `h` of 0 or less dropped, kinds folded to `sheet/filter/param/text/bitmap/web/other`) | `webgui._layout_zones`, `_CARD_KINDS` (shared by cards and preview since WP1) | Done. Cards and preview cannot disagree. |
| **`GET /dashboard-layout?name=X`** | `webgui._layout_answer`, `PREVIEW_ZONES_MAX`; tests `tests/test_dashboard_layout_preview.py` | Done (#211). Exact answer below. |
| Sketch SVG: `viewBox`, one `rect` per zone, class `dzone dk-<kind>`, letter in a zone that is big enough, legend, "no positions stored" empty state | `webui/cards.js` (`sketch`, `legend`), `app.css` `.dk-*` | Colours, outline styles and the letter scheme stay the same. The larger drawing is a second module, `webui/layout.js` (WP2). |
| Kind letters and the "S F P T I W" legend | `cards.js` `LETTER`, `LEGEND` | Reuse. |
| Page-at-a-time loading, `mine !== req` guard against stale responses | `cards.js` `render` | Same guard for the preview fetch. |

### The answer of `GET /dashboard-layout` (as merged)

Read from `py_tbparse/webgui.py` and `AGENTS.md`:

```
{ name, total,
  zones: [[kind, x, y, w, h, label, zone_id], ...],   // placed zones, at most `cap`, the largest by area, in layout order
  width, height,                                        // largest x+w and y+h over ALL placed zones (not only the capped ones), 0 when none
  unplaced,                                             // number of non-container zones without a usable position
  unplaced_zones: [[kind, label, zone_id], ...],        // the same zones, at most `cap`
  cap }                                                 // PREVIEW_ZONES_MAX = 200
```

Status codes: no workbook 400; none or several names 400; unknown name 404. `kind` is one of `sheet/filter/param/text/bitmap/web/other`. `x, y, w, h` are whole numbers as stored. `label` is the field of a filter zone, the parameter of a control, else the sheet or zone name, `""` when there is none. `total` is the number of placed zones before the cap.

What this answer does **not** carry, and the plan accepts that: container rectangles, parent ids, nesting depth, drawing order, and any floating flag. The drawing therefore works from leaf rectangles only. Nested versus crossing is worked out in the browser from the rectangles (at most 200 zones, so at most about 20,000 pairs; no cost worth worrying about). If WP2 finds that a server-side answer is needed (for example the parent container, to say "inside the container X"), that is a change to the merged endpoint and gets its own small PR; the plan does not assume it. `width` and `height` start at 0 and ignore negative starts; the browser takes the left and top edges from the zones it has, and the corpus has negative starts in 3 of 129 dashboards.

Two limits follow from the cap. The cap keeps the **largest** zones, which means the zones dropped are the small ones, which are exactly the ones that sit on top of bigger zones. With 40 leaves at most in the corpus this does not happen there, but in a 250-zone dashboard the drawing would lose overlays first. The note under the drawing therefore says "Showing the N largest of M zones; the smallest are not drawn", and the overlap hints (below) are computed from the zones that were returned only, and say so.

## What the preview adds

1. **A big drawing** (about 500 px wide on a desktop, scaling down) of one dashboard, with the name of each zone written in it when it fits (otherwise the letter, otherwise nothing), under the overlap rules below.
2. **A zone list** next to or under the drawing: one line per zone with the kind letter, the name, the kind in words, the position, and, for zones that overlap another, a short hint ("inside Sales map", "crosses Filter: Region"). This list is the real content.
3. **Linked hover and selection.** Hovering or focusing a list line highlights the zone, and the other way round. Clicking a zone or pressing Enter on a line "selects" it: it stays highlighted and the line scrolls into view.
4. **Header facts** for the selected dashboard: size text, counts, filter and parameter names, the existing **Show its sheets and positions** button, and (since the panel replaces the drawer) **All columns**, which opens the details drawer for the row. Optionally **Copy zone list** (tab-separated text).
5. **A visible note when the drawing may not match Tableau** (below). Not a footnote: a line of text directly under the drawing, in the reading order, whenever one of the listed conditions holds.
6. **Where it lives.** The Dashboards table stays; picking a row opens the panel beside it (under it below 1000 px). In Cards view the card's sketch could open the same panel (WP5, optional).

## Drawing rules (overlap, scale, size)

These are readability rules for a sketch. They are **not** Tableau's rules: nobody has compared them with Tableau Desktop.

### Draw order

- Zones are drawn **largest area first, smaller on top**; equal areas keep layout order (the later one on top). In the SVG the shapes are appended to the DOM in exactly this order, so a test can read the order from the DOM.
- Why: it is the only order that cannot hide a zone completely behind a bigger one, whatever Tableau does. It does not use the floating proxy (no zone in the corpus has the attribute) and does not claim to be Tableau's order. Tableau's real order is unknown; the document order is the best guess for it and is deliberately not used, because with it a late large zone would cover earlier small ones.
- The **list stays in layout order** (document order), not in draw order, so it reads like the workbook. Each line carries its draw position only in the overlap hint, not as a number.
- Clicking where several zones overlap selects the **topmost** one. Every zone stays reachable from the list; a selected zone also gets an outline overlay drawn above all shapes (a separate element, so selection never changes the draw order).

### Nested versus partly crossing

Two zones are related when their rectangles share more than 1% of the smaller one's area (the census threshold, so the numbers in the docs and the drawing agree). Then:

- **Nested** (one rectangle completely inside the other; 96 pairs in the corpus): the inner zone is drawn on top of the outer one with its own full outline; the outer zone keeps its fill. List hint on the inner line: "inside NAME" (the smallest enclosing zone; "and N more" when it has several). Outer line: "contains N zones" (a count, not names).
- **Partly crossing** (159 pairs): both fills are semi-transparent (fill opacity about 0.55 for every zone in a drawing, so the shared area is visibly darker), and both outlines are drawn in full. List hint on both lines: "crosses NAME" (first two names, then "and N more"). This is the case most likely to be a storage artefact rather than real covering in Tableau, which is why it is the one that triggers the visible note.
- Outlines are never made transparent, are drawn with a thin contrasting halo (a second, wider stroke behind, `paint-order: stroke`) and keep `vector-effect: non-scaling-stroke`, so they stay one to two pixels whatever the extent. Kind is still told by letter and outline style as in the cards; the overlap look adds only fill transparency, so colour is never the only signal.
- Identical rectangles (none in the corpus) count as nested in both directions; the hint says "same position as NAME".
- Both relations are recomputed from the zones that came back (at most 200), in the browser, once per response.

### Labels that do not collide

- Labels live in their own layer above all shapes, so a shape never covers a label.
- Placement: inside the zone, top left, inset 3 px, measured width (cut with an ellipsis; never `textLength` stretching). A label is placed only if its box lies inside its zone's visible area on screen and does not intersect a label already placed.
- Order of placement: topmost zone first (the reverse of draw order), so the zone you can see wins. A zone whose name does not fit or collides tries its **letter**; if the letter collides or the zone is under 12 px wide on screen, it gets nothing.
- A nested inner zone puts its label at its own top left, which may collide with the outer zone's label; the inner one is placed first and the outer one loses. Hence the outer name may be missing from the drawing: the list always has it.
- The count of zones that got neither name nor letter is stated: "N names are not shown in the drawing; the list has all of them". The count is a test target.

### Scaling for huge extents

- The viewBox is built from the zones, not from 100000: left and top are the smaller of 0 and the smallest `x`, `y` seen; right and bottom are the server's `width` and `height` (taken over all placed zones, capped or not). Negative starts are therefore drawn, not clamped. 11 of 129 corpus dashboards go past 100000; they are scaled to fit like any other.
- Strokes are non-scaling (above), text is sized in screen pixels and not in viewBox units, so an extent of 250,000 is as readable as one of 100,000.
- When the extent is past 100000 or a start is negative, a dashed marker shows where 100000 is, labelled "100000", and the visible note says so (below). Positions are drawn as stored; whether they are pixels of a fixed-size dashboard is **not** known (7 of the 11 have a fixed size, 4 do not).
- The drawing's height is capped at about 70% of the viewport height (`preserveAspectRatio` stays "meet"). For a very tall or very wide extent (aspect ratio over 4:1 or under 1:4) the zones are drawn at their true proportion in a frame that is not stretched; the list is the way to read it, and the note says "very wide/tall".
- Percentages in the list are of the drawing's extent (what the viewer sees), with the stored values in the tooltip.

### Minimum size for tiny zones

- A zone is drawn at least **3 x 3 screen pixels**, grown around its own centre, outline only (no fill) so it cannot be mistaken for a real size. Such a zone's list line says "drawn larger than stored". 12 of 821 corpus leaves are under 5 px at 500 px wide (narrowest 0.5 px); 38 (4.7%) are under 40 px.
- Under 40 px on screen a zone shows its letter instead of its name; under 12 px, nothing (list only). These limits are on screen pixels and are recomputed when the drawing is resized (resize observer, debounced).
- A zone enlarged to the minimum is counted in the note ("N tiny zones are drawn larger than they are").

### The visible note

A line of plain text under the drawing (`role="note"`, not an alert; it is not announced on every selection), shown when **any** of these holds, with the numbers filled in; the first sentence is always the same:

> A sketch from stored positions, not how Tableau draws it.

plus one extra sentence per condition that applies:

- zones overlap: "N pairs of zones overlap (M inside another, K crossing). The order and look here is for reading; Tableau may draw them differently."
- extent past 100000, negative start: "Positions go past the 100000 grid (to X by Y) or start below 0; they are drawn as stored and their unit is not known."
- zones without positions: "N zones have no stored position and are only in the list."
- cap: "Showing the N largest of M zones; the smallest are not drawn, so some overlaps may be missing."
- tiny zones: "N tiny zones are drawn larger than they are."
- names not shown: "N names are not shown in the drawing; the list has them."

When the note has any extra sentence, the drawing's frame is dashed instead of solid, so the picture itself looks provisional, not only its caption. The note is rebuilt per dashboard and per resize; a late response for a dashboard that is no longer selected must not change it (same `req` guard). In the corpus the overlap sentence would show for 29% of dashboards and the extent sentence for 8%; if that proves noisy in use, the owner can raise the threshold (question 3), but the plan prefers noise over a confident wrong picture.

## Keyboard and screen reader

- The zone list is the accessible content: a real `<ol>` of `<li>` lines, each readable on its own ("Worksheet, Customer list, position 24, 0, size 76 by 46 percent, inside Sales map"). The drawing is `role="img"` with a short label ("Layout of NAME: N zones; the list below has them all") and its zone shapes are `aria-hidden`; no screen-reader user needs the drawing. The note is real text, outside the `aria-hidden` part, read in order after the drawing.
- Keyboard: lines are reachable in list order. Plain Tab stops (`tabindex="0"` on every line) would put up to 200 stops in the page; the plan is a roving tabindex (one stop, arrow keys move, Home/End jump), the way the graph view handles its tables. Enter selects. Escape clears the selection and leaves focus in the list.
- The panel is not a dialog: no focus trap, no `aria-modal`. It is a labelled region (`aria-labelledby` the dashboard name). When a row is picked, focus stays on the row (so arrow keys keep moving through the table) unless the owner decides otherwise (question 1); the panel announces itself with a polite status line ("Layout of Customer detail: 5 zones").
- Hover is never the only way to learn anything: the name, kind, position and overlap are in the list, and selection shows by outline thickness and a background, not only colour. Contrast must hold in the dark theme and the other colour themes, including semi-transparent fills. None of this has been checked with a screen reader; WP4 asks for a manual pass, since no screen reader is available on this machine.
- `prefers-reduced-motion`: no animation on highlight or panel open.

## The row drawer (owner decision: option 1)

Today a click or Enter on any table row opens the details drawer with every column (`openRow`, `closeDrawer` in `webui/app.js`, focus moved to the drawer title, Escape closes). The owner chose:

- **Option 1: the panel replaces the drawer on the Dashboards table only.** Row click or Enter selects the row and shows the panel; the full-column details move to a button in the panel header ("All columns"), which opens the existing drawer. Everything else in the app is unchanged. One code path (`openRow`) gets a small hook for this one table. The panel is its own module and does not call the drawer, so the rejected options stay a small change.

The rejected options, for the record: option 2 (panel beside the drawer behind a **Layout** button; two panels at 1360 px make the table very narrow) and option 3 (click selects, Enter opens the drawer; different behaviour for mouse and keyboard).

## Phone layout

Under 760 px the app already turns lists into stacked cards. For the preview: the panel moves under the table (below 1000 px), the drawing is full width with `height: auto`, and the label rules above apply on screen pixels, so at 375 px most names fall back to letters. On a phone the list comes first, then the note, then the drawing, since the list is the content. No sideways scroll at 375 px. Tapping a zone selects it; there is no hover on touch, so selection must show everything hover shows. If the drawing is too small to read, the list is the fallback and the plan does not add pinch-zoom.

## Data limits and caps

- The sketch caps at `CARD_ZONES_MAX` = 40 zones, keeping the largest. The preview caps at `PREVIEW_ZONES_MAX` = 200, same rule; the panel says "Showing the 200 largest of N zones" (owner decision). The list is capped by the same number so list and drawing always agree. The corpus maximum is 40, so the note will not appear for any corpus dashboard.
- One dashboard per request, never a page of them. Only one drawing and at most 200 list lines are ever in the DOM (plus at most 200 more list lines for unplaced zones: `unplaced_zones` is capped by the same number, so the panel shows at most 400 lines in the worst case, and a test pins that bound).
- Names are cut at a length (about 60 characters in the list, with the full text in a `title`) and are always set with `textContent`, never `innerHTML`: sheet names are workbook content.
- Numbers: `x, y, w, h` are whole numbers, assumed to be on Tableau's 0 to 100000 grid for the main layout; the census shows that the assumption is false for 8% of dashboards, so nothing in the drawing depends on it.
- Zones with a missing or non-positive size are left out of the drawing but not out of the count: the panel says "N zones have no stored position" and the list names them (from `unplaced_zones`), without position.
- The request takes a dashboard name, never a path, and is refused without a workbook. Server mode needs no change (state is per session through `_STATE`).

## Work packages

Each package is one PR, in this order. No package changes `pyproject.toml`'s version; the release bump is separate.

### WP0: corpus check of overlap and odd sizes: DONE (#209)

`scripts/layout_census.py`, `tests/test_layout_census.py`, results in `docs/layout-census.md` (the numbers above). Peak memory 23 MB, 200 files in about 10 seconds. It measured; it did not compare anything with Tableau. The three questions the first plan put to it were answered: overlap is common (29% of dashboards), there is no floating attribute to build a rule on, and the 100000 grid is not safe. The plan changed accordingly (this revision).

### WP1: server side, one dashboard's zones with names: DONE (#211)

`GET /dashboard-layout?name=...`, `PREVIEW_ZONES_MAX` = 200, shared `_layout_zones` and `_largest` with the cards, labels from `dashboards.dashboard_zone_labels()`, 404 for an unknown name, `unplaced_zones` for the list. Tests in `tests/test_dashboard_layout_preview.py`. The answer shape is above. No page uses it yet.

### WP2: panel, drawing and list (no table integration yet)

Files:

- `py_tbparse/webui/layout.js` (own closure, like `cards.js`, helpers passed in) with `render(host, info)`: the drawing under the rules above (draw order, nested/crossing look, label placement, viewBox from the zones, marker at 100000, minimum size), the list with overlap hints, linked hover/selection, roving tabindex, legend, the note, the empty state. SVG built with `createElementNS`, text with `textContent`.
- `py_tbparse/webui/app.css`: only variables from `tokens.css`; new `.dzone` modifiers for the overlap look and the dashed frame.
- A line in `AGENTS.md`'s module table for `layout.js`.
- **Fixture builders (to be written in this package; not written by this plan)**, in a new `tests/layout_fixtures.py` in the style of `tests/cards_fixtures.py` (each returns the text of a small `.twb` that can be served through the existing test server). Each makes one case, so each acceptance test below names its fixture:
  - `nested_workbook()`: one dashboard, a large sheet zone with a small text zone and a small filter zone completely inside it, plus a second nesting level (a zone inside the text zone).
  - `crossing_workbook()`: two sheet zones that cross at a corner (shared area about 20% of the smaller), plus a third that crosses both.
  - `mixed_overlap_workbook()`: the nested and crossing cases in one dashboard, plus two zones with identical rectangles and two with the same area but different positions (tie rule).
  - `label_collision_workbook()`: an outer zone with a long name and an inner zone with a long name whose top-left corners are within 10 px at the test width, plus a zone with a name longer than its width.
  - `huge_extent_workbook()`: positions up to x+w = 250000 and y+h = 180000, one zone with a negative start, a fixed pixel size.
  - `grid_workbook()`: a dashboard that stays within 0 to 100000 (the control: no marker, no extent sentence).
  - `tiny_zones_workbook()`: zones of widths 1000, 100 and 10 on a 100000 grid (5, 0.5 and 0.05 px at 500 px), one of them also inside another zone.
  - `many_overlap_workbook(n=250)`: n zones, every fifth nested in a bigger one, so the cap drops small overlays.
  - `unplaced_workbook()`: a dashboard with some zones without a position, one with all of them without.
  - `hostile_names_workbook()`: names with `<script>`, quotes, non-ASCII, and a 300-character name.
  The existing `cards_workbook` stays for the no-overlap and plain-cap cases.

Acceptance, non-browser: the served page contains the `layout.js` script tag and `webgui` serves it (extend the static-file test that lists `cards.js`). The fixture builders produce well-formed workbooks that `TwbParser` reads and whose `GET /dashboard-layout` answers have the zone counts and rectangles the builders promise (so a mistake in a fixture is caught without a browser). The JS has no non-browser syntax check here, so it is covered by the Playwright tests.

Acceptance, Playwright (`tests/test_gui_layout_preview.py`; the name `tests/test_gui_layout.py` is already taken by the page-layout tests; marker and skip rules like `tests/test_gui_cards.py`; Chromium is not run by the plan or by non-browser CI):

Basic panel:
- the panel for a mixed dashboard has one SVG with N zone shapes and a list with N lines, same set, each line with kind word and name;
- hovering a zone gives its list line the highlight class and the reverse; focusing a line does the same;
- Enter/click selects and the selected line is `aria-current`, and Escape clears it;
- arrow keys move through the list with exactly one `tabindex=0` line; Home/End work;
- the drawing has `role="img"` and its shapes are `aria-hidden`; the list has an accessible name;
- a name with `<script>` in it renders as text (no injected node), a 300-character name is cut and has the full text in `title` (`hostile_names_workbook`);
- axe checks (as in `test_the_cards_view_passes_the_accessibility_checks_in_both_modes`) in light and dark, with overlapping zones on screen.

Draw order (`mixed_overlap_workbook`):
- the DOM order of the shapes is largest area first; for two zones of equal area the later one in the layout comes later in the DOM;
- a small zone inside a bigger one is after the bigger one in the DOM, and a click at its centre selects the small one (topmost), while a click on the bigger zone outside it selects the bigger one;
- the list is still in layout order, not in draw order;
- the selection overlay is the last element of the shapes layer, and selecting does not change the shape order.

Nested versus crossing (`nested_workbook`, `crossing_workbook`):
- in the nested fixture the inner line says "inside NAME" and the outer says "contains 2 zones"; the two-level case names only the smallest enclosing zone;
- in the crossing fixture both lines say "crosses NAME"; both shapes have the overlap fill (opacity below 1) and a full-opacity outline; a zone with no overlap has neither the hint nor the overlap fill;
- identical rectangles give "same position as NAME";
- with the threshold at 1% of the smaller zone: a pair touching at an edge or sharing under 1% gets no hint (add a fixture pair for each side of the line).

Labels that do not collide (`label_collision_workbook`):
- no two visible label boxes intersect (computed from `getBBox` in the test), and every visible label lies inside its own zone;
- when the inner label collides it wins and the outer one is missing from the drawing but present in the list;
- a name longer than its zone is cut with an ellipsis and its list line has the full name; a zone too small for the name shows its letter; a zone under 12 px shows neither;
- the "N names are not shown" count in the note equals the number of zones without a name or letter in the drawing.

The visible note (`mixed_overlap_workbook`, `grid_workbook`, `huge_extent_workbook`, `unplaced_workbook`, `many_overlap_workbook`):
- a dashboard without any condition (`grid_workbook`) shows the standing sentence only and a solid frame; each condition adds exactly its own sentence with the right numbers and makes the frame dashed;
- the overlap sentence's counts equal the nested and crossing hints counted over the list;
- the note is outside the `aria-hidden` subtree, is not a live region, and is rebuilt when another dashboard is selected (no sentence from the previous dashboard remains, also when the earlier response arrives late);
- the note is visible without scrolling the panel at 1360 px.

Scaling (`huge_extent_workbook`, `grid_workbook`):
- the viewBox of the huge fixture contains every zone, including the negative start, and the 100000 marker is present only there;
- an extent of 250,000 gives outlines of 1 to 2 screen pixels (computed stroke width with non-scaling stroke), and label font size in pixels equal to that in the grid fixture;
- the drawing height stays under 70% of the viewport height and the aspect ratio of the zones is unchanged (no stretching);
- the extent used is the server's `width`/`height`, taken over all placed zones before the cap: with `many_overlap_workbook` the viewBox still reaches the far edge of the zones that were dropped.

Minimum size (`tiny_zones_workbook`):
- a 0.5 px zone is drawn at least 3 x 3 screen pixels, without fill, and its line says "drawn larger than stored"; a 5 px zone is not enlarged beyond 3 px and not flagged if it is at least 3 px;
- the note counts the enlarged zones; after resizing the viewport (500 to 1000 px wide) the enlarged count falls and the labels are recomputed;
- every tiny zone is still a line in the list.

Caps (`many_overlap_workbook`, `unplaced_workbook`):
- a 250-zone dashboard shows 200 shapes and 200 lines, the text "200 largest of 250", and the note's cap sentence; the DOM node count of the panel stays under a fixed bound;
- the dropped zones are the smallest (none of the shown is smaller than a dropped one);
- the overlap hints are computed over the shown zones only (a dropped inner zone does not appear in an outer zone's "contains N" count) and the cap sentence says so;
- a dashboard with no positions shows the empty state, still lists its zones, and has no drawing note about overlap.

### WP3: Dashboards table integration (the drawer decision is made: option 1)

Row selection opens the panel (split layout, under the table below 1000 px); the details drawer opens only from the panel's "All columns" button on this table; selection survives sorting and filtering by dashboard name, not by row position; changing table or reloading a workbook closes the panel and cancels the in-flight request (same `req` guard as the cards); focus handling as above; the 404 for an unknown name (a selection kept across a reload) clears the panel with a short message instead of an error.

Acceptance (Playwright): click, Enter, Escape and focus return for the panel on the Dashboards table; "All columns" opens the details drawer with the same content as before; the details drawer still works on every other table; sort and filter keep or clear the selection correctly; the panel updates when the arrow keys move to another row (debounced, so holding a key does not send a request per row: the test counts requests); another workbook loaded clears the panel; **overlap state does not leak between dashboards**: select an overlapping dashboard, then a clean one, and the note, the dashed frame and the hints are gone (also when the first response arrives after the second row was selected); the table stays at 50,000-row speed in a workbook with many dashboards (a generated one with several hundred dashboards, rows virtual, one drawing in the DOM).

### WP4: phone layout, themes, docs

Under 1000 px the panel goes under the table; under 760 px list first, then the note, then the drawing; no sideways scroll at 375 px; dark theme and the other colour themes, including contrast of semi-transparent fills over each other and of the selection overlay. Update `docs/gui.md` (the Dashboards paragraph and the "not compared with Tableau" sentence, with the census numbers: overlap in 29% of the corpus dashboards, and the sentence that no zone in the corpus has a floating attribute), the README line, and the option-B status line in `docs/design/84/README.md`. Re-take the GUI screenshots only if a major release is being prepared (owner rule: `scripts/gui_screenshots.py` at major releases).

Acceptance (Playwright), at 375 px with the fixtures of WP2:
- no horizontal scroll with `mixed_overlap_workbook`, `huge_extent_workbook` and `many_overlap_workbook` open; the panel is under the table; the order in the panel is list, note, drawing;
- the minimum size and label rules use screen pixels: at 375 px the nested fixture shows letters or nothing where it showed names at 1360 px, with no overlapping labels, and the note's "names not shown" count rises accordingly;
- the note wraps and is not clipped (the text-spacing check of `test_gui_layout.py` is repeated with the note on screen);
- at 1360 px the panel is beside the table; the phone test for the cards still passes;
- axe in both modes and in the other colour themes, on a dashboard with overlap;
- a manual pass with a screen reader, and a comparison of a few real dashboards with Tableau Desktop, are requested from the owner, not claimed.

### WP5 (optional): open the panel from a card

A button on the card sketch opens the panel for that dashboard in the Dashboards view. Only if the owner wants the two entry points; the card keeps its small sketch (flat, no overlap look).

## What is unverified

- **How Tableau draws nested, overlapping and floating zones.** The code treats every zone as a rectangle at its stored `x, y, w, h`. The draw order (largest first), the transparency and the labels above are choices for readability, not Tableau's behaviour. The census shows 255 overlapping pairs but not whether they cover each other in Tableau or are an artefact of how positions are stored; container padding and inner margins were not measured. No Tableau Desktop is available, so the docs must keep saying "a sketch from stored positions, not how Tableau draws it".
- **Floating.** No zone in the corpus has a floating attribute; the proxy (leaf in a non-root `layout-basic`) is an assumption. The preview has no floating rule. A workbook outside the corpus with real floating zones may behave differently.
- **The unit of positions beyond 100000** (pixels of a fixed-size dashboard or something else): unknown. 7 of the 11 corpus dashboards past the grid have a fixed size.
- **The thresholds** (1% overlap, 3 px minimum, 40 px for names, 12 px for letters, opacity 0.55, 70% height) are the plan's choices; the 1% and 40 px come from the census, the others are guesses to be tuned in WP2 on real screens.
- **The 200-zone cap** is safe for the corpus (maximum 40) but untested on a real large workbook; the corpus has no file over 20 MB.
- **Whether a visible overlap note on 29% of dashboards is too noisy**: unknown until someone uses it.
- Screen reader behaviour, dark-mode contrast and the other colour themes of the panel: nothing built yet, nothing checked. The mockup was only looked at in Chromium at 1360 px and 375 px.
- Phone and tablet layouts are not drawn (as in the counts and cards); a dashboard whose main layout is empty but which has a phone layout will look empty.
- Whether a debounce of row changes is enough for a server on a slow link: untested.
- None of the acceptance tests above exists yet; this plan was not run against any browser, and the fixtures are described, not written.

## Risks

- **Drawing something wrong with confidence.** A big, named drawing looks more authoritative than the 150 px sketch. Mitigation: the standing sentence, the per-condition sentences, the dashed frame, the cap note, and the census numbers in the docs.
- **Overlapping zones hide each other.** Mitigated by the draw order (smaller on top), transparency, full outlines, topmost-wins clicking and the list hints. A zone entirely behind another cannot happen with this order unless two rectangles are identical; those get the "same position" hint.
- **The cap hides overlays first.** The dropped zones are the smallest, which are the ones that sit on others. Stated in the note; the overlap hints are over the shown zones only.
- **Hints that look certain.** "inside" and "crosses" describe rectangles, not what Tableau shows. The wording stays geometric, and the note says Tableau may differ.
- **Drawer interplay** breaks muscle memory on the most used table in the app. Mitigated by keeping the drawer reachable from the panel ("All columns") and testing the drawer on all other tables.
- **Narrow table.** Beside the panel the table has about 40 percent of the width; column count and pinned columns may need a scroll.
- **DOM growth and request storms.** One drawing, at most 200 list lines (400 with unplaced), a request per selected row with a stale-response guard and a debounce. A bug here is what killed earlier sessions, so WP3 has a test that counts nodes and requests.
- **Script injection through names.** `textContent` only; tested in WP2.
- **Duplicate facts** (cards, table, panel) drifting apart. Mitigated by the shared server helper and by one test comparing the zone counts of cards and preview.
- **Resize cost.** Label placement and the minimum size are recomputed on resize; with at most 200 zones this is cheap, but it is debounced and tested with a repeated resize.
- **Size of the work.** The design note says medium to large. WP2 and WP3 are the bulk.

## Questions for the owner

Answered: the row drawer (option 1, panel replaces it on the Dashboards table) and the cap (200, "N largest of M"). Still open:

1. When a row is picked, should focus stay on the row or move to the panel? The plan keeps it on the row so arrow keys keep working.
2. Do you want the second entry point from a card (WP5)?
3. Is a visible overlap sentence on every dashboard with any overlap (29% in the corpus) acceptable, or should it only show above some number of crossing pairs? The plan prefers showing it.
4. May WP2 change the merged endpoint if it turns out the parent container is needed (to say "inside the container X")? The plan assumes not.
