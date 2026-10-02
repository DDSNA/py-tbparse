# py-tbparse GUI redesign plan: smoother, clearer, more accessible

Target: phases 0-1 (the file split and the new look) go out as **0.4.1**, and phase 2 (the table) as **0.4.2**, both decided by the user on 2026-10-02: patch releases, because nothing breaks. The versions for phases 2-4 are open (the earlier proposal was 0.5.0 and 0.6.0).
Method: design-critique, accessibility-review and design-system frameworks applied to the real GUI
(9 screenshots: start, overview, fields, renames, graph, dark, phone; one 190-field workbook), plus measurements from the page's CSS and JS.
No third-party UI-redesign skill was installed; the three installed design skills were used.

## 1. Where the GUI is today

**Works well:** one clear job per screen; sidebar grouped with live row counts; real dark theme from
CSS variables; semantic `<button>` navigation with `aria-current`; `aria-sort` on headers; a visible
`:focus-visible` ring; a polite live region for status; sticky top bar; helpful empty state;
phone layout swaps the sidebar for a select; tabular numerals on counts.

### Findings (from the critique)

| # | Finding | Evidence | Severity |
|---|---|---|---|
| 1 | **No motion at all.** View switches, table rebuilds, loading and results just snap. | 0 `transition`, 0 `@keyframes`, 0 `prefers-reduced-motion` in 1,124 lines | 🟡 Moderate (this is the "smoothness" gap) |
| 2 | **Filtering rebuilds the whole table on every keystroke**, no debounce, no virtual rows. A large workbook will jank. | `renderTable()` does `innerHTML = ''` and creates every row; `input` event calls it directly | 🟡 Moderate, 🔴 on big tables |
| 3 | **Opening a workbook means typing a path.** No file picker, drag-and-drop or recent files. | Start screen has only the path box | 🟡 Moderate |
| 4 | **The relationship "graph" is DOT source text**, not a graph. | Screenshot 05 | 🟡 Moderate (biggest missed opportunity) |
| 5 | **Overview is only counts**; zeros look as loud as real numbers and say nothing about problems. | Screenshot 02: 5 of 7 tiles read 0 | 🟡 Moderate |
| 6 | **Tables are width-wasteful**: internal ids (`federated.1yoogmp19z69...`) fill a whole column, the real columns clip (`semant`), no resize/hide/pin. | Screenshots 03, 04 | 🟡 Moderate |
| 7 | **The Field renames toolbar wraps into three rows** of mixed-width controls; filters and the main action (Create) share one cluster; no preview or confirmation. | Screenshot 04 | 🟡 Moderate |
| 8 | **Rows expand by mouse only.** `<tr>` has a click handler but no tabindex/role, so keyboard users cannot expand them. | `tr.addEventListener('click')` | 🔴 Critical (keyboard) |
| 9 | **Contrast failures.** Zero counts and empty-cell dashes are faded with `opacity` instead of a real colour. | table below | 🔴 Critical |
| 10 | **Redundant chrome**: the loaded path is shown in the input, in the "Loaded:" line and the workbook name. | Screenshot 02 | 🟢 Minor |
| 11 | **Phone**: tiles stack one per row (7 screens tall); the panel does not fill the viewport. | Screenshot 06 | 🟢 Minor |
| 12 | Header sort works on Enter only (not Space); no skip link; nav and action targets are ~32 px tall. | JS/CSS | 🟢 Minor (24 px is the WCAG 2.2 AA floor, 44 px the stricter guideline) |

### Contrast (computed from the CSS variables and opacities)

| Element | Light | Dark | Needs |
|---|---|---|---|
| Body text | 15.99 ✅ | 14.07 ✅ | 4.5 |
| Muted text on panel | 5.66 ✅ | 6.62 ✅ | 4.5 |
| Sidebar zero-count (muted at 45%) | **1.93 ❌** | **2.37 ❌** | 4.5 |
| Empty-cell dash (muted at 55%) | **2.29 ❌** | **2.93 ❌** | 4.5 |
| Active nav (accent on accent-soft) | **4.31 ❌** | 5.48 ✅ | 4.5 |
| Primary button label | 4.99 ✅ | 7.06 ✅ | 4.5 |

## 2. Principles

1. **Motion explains, never decorates.** It shows where something came from or went; every animation has a reduced-motion version.
2. **Keep it local, light and dependency-free.** No CDN, no build step, no telemetry: `pip install` and go.
3. **Fast before pretty.** Interaction budgets are tests, not wishes.
4. **Every state is designed**: loading, empty, error, success, disabled.
5. **Same patterns everywhere**: one toolbar, one table, one detail panel, one way to confirm an action.

## 3. Architecture

Today the whole UI is one raw Python string (about 670 lines of CSS, HTML and JS) inside `webgui.py`.
That kept installation trivial but blocks linting, editor support, diffs and testing of the front end.

**Recommendation: stay zero-build, but split it into real files.**

```
py_tbparse/webui/
  index.html          # shell, landmarks
  tokens.css          # the design tokens (below)
  app.css             # layout and components
  js/{store,api,table,views,motion,a11y}.js   # native ES modules, no bundler
```

Served by the existing handler from package data (add to `package-data`). The security rules stay: server values
still go through `_json_for_script`, same Host/Origin checks, no cross-origin loads. The structural tests that
guard the raw string become ordinary tests of real files.

Considered and rejected: React/Vite or similar (needs Node and a build, breaks "just pip install");
vendoring htmx/Alpine/Preact (adds third-party code to audit for little gain at this size); keep the single
string (cheapest now, but every later phase gets harder).

### Design tokens (design-system pass)

Existing colour tokens stay; add the missing categories so nothing is hard-coded:

| Category | Tokens |
|---|---|
| Colour | existing set + `--text-faint` (a real colour that passes 4.5:1), `--accent-strong` for active nav, `--success`, `--warning`, state-layer colours for hover/pressed |
| Space | `--space-1..8` on a 4 px scale |
| Type | `--text-xs/sm/md/lg/xl`, `--leading-*`, one mono stack |
| Radius / elevation | `--radius-sm/md/lg`, `--shadow-1/2` |
| Motion | `--dur-fast: 120ms`, `--dur-base: 200ms`, `--dur-slow: 320ms`; `--ease-out`, `--ease-in-out`; all set to `0.01ms` under `prefers-reduced-motion: reduce` |
| Density | `--row-h` for comfortable (default) / compact |

Components to document and own (states, variants, a11y): Button, Field, Select, Toolbar, Nav item, Stat tile,
Data table, Row detail drawer, Toast, Empty state, Skeleton, Dialog.

## 4. Smoothness: concrete motion spec

Durations follow common UI guidance (micro-interactions 100-200 ms, UI transitions 200-300 ms, ease-out for entering).

| Where | Motion | Duration / easing |
|---|---|---|
| Buttons, nav hover/press | colour + slight lift | 120 ms ease-out |
| View switch | content cross-fade + 8 px rise; nav highlight slides between items | 200 ms ease-out |
| Table first paint | brief row stagger (first 20 rows only) | 200-320 ms |
| Sort / filter | rows reorder with the View Transitions API where available, plain update otherwise | 200 ms |
| Loading | skeleton rows instead of "Loading..." text; progress on Load | until ready |
| Result messages | toast slides in, auto-dismisses (errors persist) | 200 ms in, 4 s hold |
| Row detail | drawer slides from the right, focus moves into it and back | 200 ms |
| Reduced motion | all of the above become instant or a plain fade | `0.01ms` |

Same-document View Transitions are widely supported now (Chrome/Edge 111+, Safari 18+, Firefox from 133-144 depending on
the source), so use them as progressive enhancement behind a feature check, never as a requirement.

## 5. Phases

### Phase 0: foundation (no visible change)
- Split the page into `webui/` files; keep behaviour identical; port the structural tests.
- Add `tokens.css`; replace hard-coded values.
- Test scaffolding: Playwright screenshot baselines (light, dark, phone) for each view; a contrast test that reads the computed styles.
- **Done when:** the full suite is green and screenshots are pixel-identical to today.

### Phase 1: accessibility and motion quick wins
- Fix findings 8, 9, 12: real colours instead of opacity, rows focusable and expandable with Enter/Space, Space on headers, skip link, `main`/`nav`/`header` landmarks, focus moves to the view heading on navigation.
- Add motion per the spec above, with `prefers-reduced-motion`.
- Debounce filter (about 120 ms); skeleton loading; toasts replace the status line for results (the live region stays for screen readers).
- Fill-height panel, 2-column tiles on phones, remove the redundant "Loaded:" line.
- **Done when:** every contrast row passes; a keyboard-only test can load, filter, sort, expand a row and create a renamed workbook; reduced-motion test passes.

### Phase 2: a better table
- Windowed rendering (only visible rows in the DOM) with the filter running off the main render path.
- Column menu: hide, resize, pin first column, copy column; sticky header and first column.
- Readable datasource labels (caption, with the full id on hover and copy), density toggle (comfortable/compact), per-column filter chips.
- Row detail drawer instead of inline expansion; "copy row as JSON".
- **Budgets (tests):** 50,000 rows filter in under 100 ms of main-thread time per keystroke; first paint of a 1,000-row table under 150 ms; no layout shift on sort.

### Phase 3: opening, overview, graph
- **Open:** drag-and-drop and a file picker (the local server accepts the bytes; nothing leaves the machine), recent files, clearer errors. Dropped files have no path on disk, so "create beside the original" becomes "download" for them; say so in the UI.
- **Overview as a report card:** tiles stay but zeros are quiet; add a health summary (validation findings, unused fields, calculations that nothing uses, missing references) with links into the tables; show the workbook's sheets/dashboards at a glance.
- **Real graph:** render joins and relationships as SVG (simple dependency-free layered layout, pan and zoom, hover highlights); keep DOT export.

### Phase 4: guided workflows (needs the Tableau check first)
- **Field renames / report renames:** a two-pane preview (current -> suggested, filter by reason, per-row exclude), a single toolbar, the destructive-looking action clearly separated, and a confirmation panel that shows the output path.
- **Templates view** (deliberately held back earlier): make/apply as steps: choose template, choose data, review mapping with type-filtered dropdowns and "what would break", set parameters, create.
- **Gate:** build the Templates view only after one generated workbook has been opened in Tableau.

## 6. How we will know it worked

- Accessibility: all text and UI contrast rows pass AA in both themes; keyboard-only and reduced-motion tests pass; manual check with at least one screen reader (VoiceOver or NVDA), which I cannot do from here.
- Performance: the budgets above, enforced in tests.
- Regression: screenshot baselines for every view in light, dark and phone.
- No JavaScript errors in any browser test (already a rule in AGENTS.md).

## 7. Risks

- **Scope.** Phases are independent releases; stop after any phase.
- **Regressions in a hand-rolled UI.** Phase 0 baselines exist to catch them.
- **Testing blind spots.** My audit used screenshots and static measurements of one workbook; real screen-reader and low-vision testing are still needed.
- **Drag-and-drop trust.** Accepting uploaded bytes on a local server must keep the existing Host/Origin checks and size limits.
- **Browser support.** Everything new is feature-detected; the baseline experience works without View Transitions.

## 8. Decisions (confirmed 2026-10-02)

1. **Split the page into `webui/` files:** yes. Done in phase 0.
2. **Drag-and-drop upload on the local-only server:** yes, keeping the existing Host/Origin checks and adding a size limit. Dropped files have no path on disk, so "create beside the original" becomes "download" for them, and the UI says so.
3. **Graph:** write our own small dependency-free SVG layout.
4. **Versions:** phases 0-1 ship as 0.4.1 and phase 2 as 0.4.2 (the user's calls, 2026-10-02). Phases 3-4 are open; the earlier proposal was 0.6.0.
5. **Default density:** comfortable; a Compact rows button in the table toolbar switches to compact and is remembered.
6. **Branch discipline:** all redesign work lives on `ui-redesign` (pushed 2026-10-02). Later pushes and any PR only when the user says so.

## 9. Design direction: "cozy corporate meets small shop"

The feeling to aim for: the calm, trustworthy competence of a good corporate tool, with the warmth
and friendliness of a well-run small shop. A place people are glad to open, not a console.

### Principles
- **Warm, not sterile.** Paper-and-ink neutrals instead of cold greys; soft edges; generous spacing.
- **Confident, not loud.** One calm primary colour does the work; a terracotta accent is used sparingly for highlights and small moments of personality.
- **Friendly voice, precise facts.** Plain language, no jargon in headlines, exact numbers and names in the details.
- **Never at the cost of access.** Every colour pair below passes WCAG AA (verified by script); warmth does not buy lower contrast.
- **Calm motion.** Gentle ease-out, short durations, nothing bouncy; all of it off under reduced motion.

### Palette (proposed tokens, contrast verified)

| Token | Light | Dark | Use |
|---|---|---|---|
| `--bg` | #f7f3ee | #1a1714 | page background (warm paper / warm charcoal) |
| `--panel` | #fffdfa | #231f1b | cards, tables, sidebar |
| `--text` | #2b2622 | #efe9e1 | body text (14.7:1 / 13.6:1 on panel) |
| `--muted` | #6b625a | #b3a99d | descriptions, meta (5.9:1 / 7.1:1) |
| `--faint` | #736a61 | #a79d91 | zero counts, empty cells: a real colour, never opacity. Chosen to stay 4.5:1 on hovered and expanded rows too (the first proposal, #7a7067, fell to 4.1:1 there; the token test caught it) |
| `--border` | #e6dfd5 | #3a342d | dividers and card edges |
| `--primary` | #1d6b73 | #6cc0c8 | main buttons, links, focus ring (calm teal) |
| `--primary-text` | #ffffff | #10282b | label on primary (6.2:1 / 7.4:1) |
| `--primary-soft` / `--primary-on-soft` | #e3f0f0 / #17575e | #203638 / #8fd3d9 | active nav and selection (7.0:1 / 7.6:1) |
| `--accent` / `--accent-soft` | #a9482a / #f8e8df | #eb9a76 / #3a2a22 | warm highlights, badges, empty-state art (4.8:1+) |
| `--success` | #2f6b3d | #7fcf93 | saved, matched |
| `--warning` | #8a5a00 | #e6b34d | would break, close match |
| `--danger` | #b3382c | #ff8b7c | errors |

Every text/background pair the stylesheet uses (22 per theme) passes 4.5:1, and the focus ring 3:1, in both themes. `tests/test_webui_tokens.py` enforces this by reading the real `tokens.css`, and also fails on undefined CSS variables and on text faded with `opacity`.

### Shape, space, type
- **Radius:** `--radius-sm 8px`, `--radius-md 12px`, `--radius-lg 16px`; buttons and fields use md, cards lg. Nothing sharp.
- **Elevation:** one soft, warm-tinted shadow for cards and a slightly deeper one for drawers and toasts (no hard borders doing shadow's job).
- **Space:** 4 px scale; comfortable density by default (row height about 40 px, generous card padding); compact is an option, not the default.
- **Type:** system fonts only (no web fonts, nothing fetched). Body `system-ui`; headings use `ui-rounded` where the platform has it (falls back to `system-ui`) at slightly heavier weight for a friendlier feel. Mono for ids and paths.
- **Touch targets:** buttons, fields and table rows are at least 40 px tall; sidebar items are 38 px (17 of them at 40 px would scroll the sidebar on a laptop). WCAG 2.2 AA asks for 24 px, so both clear it.

### Voice and copy (examples to follow)
- Start: "Let's open a workbook" / "Drop a .twb or .twbx here, or paste its path. Everything stays on this computer."
- Empty table: "Nothing here yet. This workbook has no rows in this table."
- Success: "Saved a fixed copy next to your original." (the original is never touched, and says so)
- Error: "That didn't work: <reason>. Your original is untouched."
- Zero counts read as quiet facts ("No parameters"), not as failures.

### Small-shop touches (restrained)
- A friendly line-art illustration on the start screen and empty states (inline SVG, drawn in `--primary` and `--accent`), no stock art.
- A warm accent underline on the active nav item and the wordmark; one tiny celebratory moment when a workbook finishes loading (a soft check, not confetti), skipped under reduced motion.
- The overview greets the workbook by name and summarises it in a sentence before the numbers.

## 10. Status

- **Phase 0 done** (commit b0e275f on `ui-redesign`): page split into `webui/index.html`, `tokens.css`, `app.css`, `app.js`; served from a fixed whitelist; 321 tests pass; nine screenshots (start, overview light/dark, fields light/dark, renames, graph, phone x2) are byte-identical to before the split.
- **Phase 1 done** (see `git log`): the tokens and palette above, calm motion with reduced-motion support, the contrast/keyboard/landmark fixes, debounced filter, skeleton loading, toasts, fill-height panel, 2-column tiles on phones, friendlier copy and the shop-awning start screen. 342 tests pass (10 token tests, 11 new browser tests). Findings 1, 2 (debounce; windowing is phase 2), 8, 9, 10, 11 and 12 from the critique are addressed.
- **Decisions taken while building (they differ from the plan on purpose):**
  - Selecting a sidebar item does **not** move focus to the heading, which would drag keyboard users out of the sidebar. A polite live region announces "Showing Fields, 55 rows" instead, and the view fades in.
  - The table has **one tab stop** with arrow-key navigation between rows (Home/End too), Enter/Space to open the details drawer (`aria-current` marks the open row); making all rows tab stops would mean 190 stops on the Fields table.
  - The status line became a **toast** that reuses the `#status` live region: successes fade after about 4.5 s (the text stays for assistive technology), errors and "busy" messages stay until replaced or clicked. Error copy is now "That didn’t work: ..." and the save message promises the original is untouched.
  - The skeleton appears only after 180 ms, so quick loads never flash it.
- **A bug the keyboard test found in the old code:** sorting from the keyboard destroyed the focused header (the table is rebuilt), so Enter could not flip the direction. Focus is now restored to the same column header.
- **Phase 2 done** (see `git log`; version **0.4.2**): a windowed table with a column menu, filter chips, a details drawer, readable datasource labels and a density toggle. The page now holds about 23 rows whatever the table size. Measured on this 2-CPU sandbox, same method before and after (first paint / filter / sort):

  | rows | before | after | rows in the page |
  |---|---|---|---|
  | 1,000 | 21 / 20 / 339 ms | 13 / 21 / 15 ms | 1,000 to 23 |
  | 5,000 | 86 / 108 / 743 ms | 11 / 17 / 23 ms | 5,000 to 23 |
  | 20,000 | 317 / 280 / **4,070 ms** | 14 / 17 / 54 ms | 20,000 to 23 |
  | 50,000 | never finished (it killed the session twice) | 16 / 22 / 119 ms | 23 |

  Budgets, enforced by tests that fail at twice the figure so a slow CI machine does not flake them: first paint of 1,000 rows 150 ms, filtering 50,000 rows 100 ms per keystroke. "Filter" is a warm keystroke; the first one, typed before the search index finishes building in the background, was 6 to 20 ms in the same runs.
- **What phase 2 added:**
  - **Windowing** (`webui/table.js`, class `VTable`): rows have a fixed height (`--row-h`), spacer rows stand in for what is off screen, and the table carries `aria-rowcount` and `aria-rowindex` so assistive technology still knows its real size. Browsers cap an element height at about 33 million px, which at 40 px rows is around 800,000 rows.
  - **Fast data path** (`app.js`): one precomputed lowercase search string per row, built in 4,000-row slices right after a table is drawn (and finished at once if you type first); a typed sort with a numeric fast path and one shared `Intl.Collator`. The page records its render time as the User Timing measure `py-tbparse:table`, which the speed tests read.
  - **Column menu** (Alt+Down on a header, the context-menu key, or the visible options button): sort, filter this column, pin to the left, hide, wider/narrower/reset width, copy column values. Drag a header edge to resize. A **Columns** menu brings hidden columns back. Settings are kept per table for the session.
  - **Filter chips** for column filters, with Clear filters; they combine with the search box.
  - **Details drawer** replaces inline row expansion (fixed row height is what makes windowing cheap): every column of the row, the full text, the real datasource id, Copy row as JSON, Escape closes it and focus returns to the row.
  - **Readable datasources**: `/load` now returns each datasource's caption, so a cell reads "Listings+ (Tableau Full Project)" instead of `federated.1yoogmp19z69r21gvk5nd1r8nec2`; the tooltip, the drawer, the search and anything copied keep the real id.
  - **Density**: Compact rows (32 px rows) next to the default 40 px, remembered across reloads.
  - **Glide**: a sort (only a sort; see the review round below) animates rows to their new places with the View Transitions API where the browser has it and motion is welcome; the page itself swaps at once.
- **Decisions taken in phase 2:** search covers the visible columns only (a hidden column is not searched); long values are truncated in the table (tooltip and drawer hold the full text); column choices are not kept across reloads, density is.
- **Three bugs the tests caught while building it:** (1) a rapid second sort skipped the first view transition and surfaced an unhandled "Transition was skipped" rejection; (2) choosing "Filter this column" rebuilt the menu and wiped the form it had just opened; (3) a menu action that did not redraw the table (copying) dropped focus to the page. All fixed, all covered.
- **Review and test round** (after "Review the work here"): four review bugs fixed, then a browser suite added: `test_gui_table.py` (windowing, a Python oracle for filter/sort/search, a seeded random walk), `test_gui_a11y.py` (roles, keyboard, rendered contrast in both themes across 12 states) and `test_gui_layout.py` (no sideways overflow from 320 px, layout stability, menu/drawer/toast on screen). What they found and what changed:
  - View settings are keyed by column **name**, not index, so they survive a column being hidden or pinned.
  - Menus: disabled items use `aria-disabled` (focusable, inert); a menu follows its column across a redraw (`reanchorMenu`); the filter form is a `role="dialog"` that keyboard keys no longer steal; `aria-expanded` is kept on the options buttons.
  - Resizing: `MIN_WIDTH` 80 (a narrower header was almost all button), pointer capture, and a one-tick click guard instead of a 300 ms window that swallowed a real click.
  - Only a sort glides, for 120 ms: while a view transition runs Chromium sends clicks to the page root and no CSS (`pointer-events: none` on the pseudo-elements included) prevents it.
  - Responsive: the Field renames toolbar overflowed below about 400 px (an `inline-flex` box sizes to its content and never wraps); it is a full-width flex row on phones.
- **Process note:** measuring 50,000 rows against the OLD table crashed the session twice (400,000 page nodes plus a multi-second sort on a 2-CPU, 7.9 GB machine). The measuring scripts now check free memory, set timeouts and print progress; the heavy tests skip below 1.5 GB free.
- **Next: phase 3** (open, overview report card, rendered graph) plus colour themes: see section 11. Re-capture the screenshot baseline first, since phase 2 changed the table's look.
- Pushed to `origin/ui-redesign` on 2026-10-02 at the user's word. Version bumped to 0.4.1 and pushed on the user's word. No PR yet; open one only when asked, and a release only on an explicit go.

## 11. Plan: phase 3 (open, overview, graph) and colour themes

Drafted 2026-10-02, not started. Same branch (`ui-redesign`), same rules: every page change gets a browser
test, colours stay tokens, nothing is pushed or released without the user saying so. Before any code, re-capture
the screenshot baseline (phase 2 changed the table).

Four parts, each one shippable on its own, in this order: **3a Open, 3d Themes, 3b Overview, 3c Graph**. Themes come
second because the overview and graph are then built on the theme tokens from the start, not refitted later.

### 3a. Opening a workbook
- **Upload endpoint** `POST /upload`: raw bytes, `Content-Type: application/octet-stream`, file name in an
  `X-Filename` header. Neither is CORS-safelisted, so a foreign page cannot send it without a preflight, which this
  server never answers; the Host/Origin checks stay. Streamed to a private temp dir (`mkdtemp`, mode 0700) in 1 MB
  chunks, never held in memory whole; size limit 200 MB (answers 413); the extension and the first bytes must agree
  (`PK` zip for `.twbx`, XML for `.twb`); the previous upload is deleted when a new one arrives and at exit.
- **The page:** an "Open file..." button (`<input type=file accept=".twb,.twbx">`) next to the path box, and a drop
  overlay that appears on `dragenter` anywhere in the window ("Drop to open. It stays on this computer."). An
  upload progress line for big files.
- **No path on disk:** for an uploaded workbook "Create fixed workbook" writes into the temp dir and offers only
  Download, and the toolbar says why. `_STATE` records where the workbook came from.
- **Recent files:** the last 8 *paths* (never uploads) in `localStorage`, shown on the start screen with a remove
  button; reads and writes wrapped in try/catch. A missing file gives a friendly error, not a broken list.
- **Clearer errors:** one map from server error to copy: not found, not a workbook, broken zip, too big, no
  `.twb` inside the `.twbx`. Each says what to do next.
- **Tests:** endpoint tests (size limit, magic check, wrong content type is 415, foreign Origin is 403, temp
  cleanup); a browser test with `set_input_files` and one with a synthetic `DataTransfer` drop; recent list; the
  download-only state.

### 3d. Colour themes
The current palette stays the default ("Shop"). Each theme is a full set of **colour** tokens in a light and a
dark variant; shape, space, type and motion stay shared, so a theme can never break layout. Proposed set, each in
step with what is in fashion now but kept calm enough to work in all day:

| Theme | Light | Dark | Feel |
|---|---|---|---|
| **Shop** (default) | warm paper, teal, terracotta | warm charcoal | the current look |
| **Matcha** | oat cream, sage green, clay | deep moss | the sage/earthy trend, soft and natural |
| **Fjord** | snow, slate blue, frost cyan | polar night | cool Nordic, very low glare |
| **Pastel** | lavender milk, periwinkle, peach | soft aubergine | the pastel developer-theme look (our own palette, not a copy of a named one) |
| **Neon** | lilac white, electric violet, cyan | near-black navy with violet/cyan glow | synthwave, the loud one, still AA |
| **High contrast** | white, black, deep blue | black, white, yellow | accessibility, not fashion; 7:1 everywhere |

- **Mechanism:** `webui/themes.css` (new asset, add it to `_ASSETS` and package data) with
  `:root[data-theme="matcha"]` blocks, and dark variants under both
  `@media (prefers-color-scheme: dark) { :root[data-theme="matcha"]:not([data-mode="light"]) }` and
  `:root[data-theme="matcha"][data-mode="dark"]`. Mode is separate from theme: Auto (system), Light, Dark. Each
  mode also sets `color-scheme` so form controls and scrollbars match.
- **Picker:** a "Theme" button in the top bar opens the existing menu with a swatch per theme
  (`menuitemradio`, `aria-checked`) and an Auto/Light/Dark switch. Choices are kept in `localStorage`.
- **No flash of the wrong theme:** the theme must be on `<html>` before the first paint, so two lines that read
  `localStorage` go into the one inline config script `_render_index()` already writes (still one inline script).
- **Neon glow** is a shadow token (`--glow`), empty in every other theme, so nothing else changes.
- **Tests:** `test_webui_tokens.py` grows to every theme x mode: each defines every colour token, every
  text/background pair passes 4.5:1 (7:1 for High contrast), focus ring 3:1. A browser test switches themes and
  checks the computed colours, that the choice survives a reload, and that there is no flash (the attribute is set
  before `DOMContentLoaded`). The rendered contrast audit runs every theme on three states, not all twelve, to keep
  the suite inside this machine.

### 3b. Overview as a report card
- **`GET /overview`** (computed on first request and cached, so `/load` does not get slower): a one-sentence
  summary ("Superstore has 4 dashboards, 12 sheets and 2 datasources."), the counts, sheets and dashboards with
  the sheets each dashboard shows, and a health list. Each health item has severity, title, count and a link:
  table name plus column filters.
- **Health checks, all from code that already exists:** relationship problems (`validate_relationships`), fields
  nothing uses and calculations nothing uses (`field_usage`), inferred relationships that are not modelled,
  custom SQL and published sources (information, not problems). "Missing references" (a calculation naming a
  field that does not exist) needs a small new helper in `usage.py`, with its own synthetic-XML tests.
- **Links into the tables:** a health item opens its table with the filter chips already set (the phase 2 chip
  state takes a list of `{col, text}`), so "14 unused fields" lands on exactly those 14 rows.
- **Look:** zero tiles stay quiet, a calm "All clear" when nothing is wrong, dashboard cards with their sheets.
- **Speed:** time `/overview` on the 200-workbook corpus; budget 1 s on the largest. If `field_usage` is slower,
  run it after the first paint and fill the health card in when it arrives.
- **Tests:** `/overview` on the fixtures and on synthetic XML for each check; a corpus run that only asserts it
  never fails; browser tests that a health link opens the right table and filters.

### 3c. A real relationship graph
- **Data:** split `graph.py` into `graph_data()` (nodes and edges with kind and label) and `to_dot()` built on it;
  the DOT output must stay byte-identical (test). `/graph?format=json` returns the data.
- **Layout** (`webui/graph.js`, dependency-free, deterministic): connected components side by side; a layered
  layout (break cycles by depth-first search, longest-path layers, then four barycentre sweeps to cut crossings),
  curved edges. Joins solid, relationships in the primary colour, inferred dashed, with a legend.
- **Interaction:** drag to pan, wheel or +/- buttons to zoom, Fit. Nodes are focusable with arrow keys between
  neighbours; hovering or focusing a node lights up its edges and dims the rest; clicking an edge shows its join
  keys in the details drawer. All colours are theme tokens, so the graph follows the theme.
- **Big graphs:** above about 300 nodes, show the largest component first and a component list, rather than a
  hairball. Measure layout time on the corpus; budget 200 ms.
- **Accessible alternative:** a "View as list" switch shows the edges as a table; the SVG has a text summary.
- **Exports:** DOT stays; add SVG download.
- **Tests:** layout unit tests in the browser (no overlaps, every edge drawn, same input gives same output),
  DOT unchanged, keyboard navigation, pan/zoom without JS errors, reduced motion has no animated fit.

### Version, size and risks
- **Version:** 3a+3d could ship as **0.5.0** (new endpoint, new feature) and 3b+3c as 0.5.1, or all of phase 3 as
  0.5.0. The user decides; bump in the branch before any PR.
- **Rough size:** 3a medium, 3d medium (most of it is choosing palettes that pass contrast), 3b medium, 3c the
  largest. Each lands as its own commits with its tests.
- **Risks:** uploads on a 7.9 GB machine (streamed to disk, size-limited); layout cost on big graphs (cap and
  measure); the test suite growing past this machine (themes multiply states, so the rendered audits are
  sampled); trendy palettes failing AA (the token test decides, not taste).

## Sources

- Same-document View Transitions support: https://www.debugbear.com/blog/view-transitions-spa-without-framework and https://www.testmuai.com/learning-hub/view-transitions-api-browser-support/ (the sources disagree on Firefox's first version, hence feature detection)
- Motion durations, easing, reduced motion: https://blog.openreplay.com/prefers-reduced-motion-accessible-animation/ and https://www.joshwcomeau.com/react/prefers-reduced-motion/
- Sort animations in tables: https://patents.justia.com/patent/10115219 (illustrates the user benefit) and https://reactdatatable.com/docs/animations/
- Frameworks applied: design-critique, accessibility-review (WCAG 2.1 AA), design-system skills in this environment
