# py-tbparse GUI redesign plan: smoother, clearer, more accessible

Target: the release after 0.4.0 (proposed 0.5.0 for phases 0-2, 0.6.0 for phases 3-4).
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

## 8. Decisions needed

1. Split the page into `webui/` files (recommended), or keep the single string?
2. Drag-and-drop upload acceptable for a local-only server (with the caveat above)?
3. Graph: write the small SVG layout ourselves (recommended, dependency-free) or vendor a library?
4. Ship phases 0-2 as 0.5.0 and 3-4 as 0.6.0?
5. Default density: comfortable (today's) or compact?

## Sources

- Same-document View Transitions support: https://www.debugbear.com/blog/view-transitions-spa-without-framework and https://www.testmuai.com/learning-hub/view-transitions-api-browser-support/ (the sources disagree on Firefox's first version, hence feature detection)
- Motion durations, easing, reduced motion: https://blog.openreplay.com/prefers-reduced-motion-accessible-animation/ and https://www.joshwcomeau.com/react/prefers-reduced-motion/
- Sort animations in tables: https://patents.justia.com/patent/10115219 (illustrates the user benefit) and https://reactdatatable.com/docs/animations/
- Frameworks applied: design-critique, accessibility-review (WCAG 2.1 AA), design-system skills in this environment
