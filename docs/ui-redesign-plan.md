# py-tbparse GUI redesign plan: smoother, clearer, more accessible

Target: phases 0-1 (the file split and the new look) go out as **0.4.1**, decided by the user on 2026-10-02: a patch release, because nothing breaks. The versions for phases 2-4 are open (the earlier proposal was 0.5.0 and 0.6.0).
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
4. **Versions:** phases 0-1 ship as 0.4.1 (the user's call, 2026-10-02). Phases 2-4 are open; the earlier proposal was 0.5.0 for phase 2 and 0.6.0 for phases 3-4.
5. **Default density:** comfortable (a compact toggle comes in phase 2).
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
  - The table has **one tab stop** with arrow-key navigation between rows (Home/End too), Enter/Space to expand, and `aria-expanded`; making all rows tab stops would mean 190 stops on the Fields table.
  - The status line became a **toast** that reuses the `#status` live region: successes fade after about 4.5 s (the text stays for assistive technology), errors and "busy" messages stay until replaced or clicked. Error copy is now "That didn’t work: ..." and the save message promises the original is untouched.
  - The skeleton appears only after 180 ms, so quick loads never flash it.
- **A bug the keyboard test found in the old code:** sorting from the keyboard destroyed the focused header (the table is rebuilt), so Enter could not flip the direction. Focus is now restored to the same column header.
- **Next: phase 2** (a better table: windowed rows, column menu, readable datasource labels, density toggle, row detail drawer). Re-capture the screenshot baseline first, since phase 1 changed the look on purpose.
- Pushed to `origin/ui-redesign` on 2026-10-02 at the user's word. Version bumped to 0.4.1 and pushed on the user's word. No PR yet; open one only when asked, and a release only on an explicit go.

## Sources

- Same-document View Transitions support: https://www.debugbear.com/blog/view-transitions-spa-without-framework and https://www.testmuai.com/learning-hub/view-transitions-api-browser-support/ (the sources disagree on Firefox's first version, hence feature detection)
- Motion durations, easing, reduced motion: https://blog.openreplay.com/prefers-reduced-motion-accessible-animation/ and https://www.joshwcomeau.com/react/prefers-reduced-motion/
- Sort animations in tables: https://patents.justia.com/patent/10115219 (illustrates the user benefit) and https://reactdatatable.com/docs/animations/
- Frameworks applied: design-critique, accessibility-review (WCAG 2.1 AA), design-system skills in this environment
