# Roadmap

Part of [py-tbparse](https://github.com/DDSNA/py-tbparse). This is the one page that says what is built, what is being built, what comes next and in which order. The other plan pages keep the designs; this page points at them and does not repeat them.

Written 2026-10-22 against `main` at `1130fa9` (version 0.5.6 is the last release). Facts come from the plan pages listed below, `AGENTS.md`, the README, the GitHub project [#6](https://github.com/users/DDSNA/projects/6), the open issues and the merged pull requests. Where a line says "verified" it was checked by reading the code on `main` or running a command; everything else is read from the docs and may be out of date. **Nothing py-tbparse writes has been checked in Tableau Desktop** except one template path ([verify-in-tableau.md](verify-in-tableau.md)); the check list in [tableau-check.md](tableau-check.md) is still "not run".

How to keep this page true: when a pull request merges or the owner decides something, change the row here in the same PR. For the live state use `git log`, `gh pr list` and `gh issue list`; if they disagree with this page, they win.

## Status words

| Word | Meaning |
| --- | --- |
| built | merged to `main`. "Released in X" or "unreleased" says whether a PyPI release has it. |
| in progress | an open pull request exists. |
| planned for 0.6.0 | the owner has put it in 0.6.0. |
| planned | the owner wants it built; the release that carries it is not decided. |
| blocked | it cannot move until something outside the code happens (a Tableau check, a sample workbook, an owner answer). |
| dropped | the owner decided not to do it. |

## What shipped, by version

| Version | Main contents | Pull requests |
| --- | --- | --- |
| 0.5.5 (2026-10-16, tag at `40b6b57`) | bug fixes from the 0.5.4 review (#119, #120, #121, #122, #123, #129, #130, #134 to #139); GUI polish (#142 to #144); zone counts on the Dashboards table (refs #84); `DeprecationWarning` for the library `on_clash` default (#128); exit-code table in `docs/cli.md` (refs #127); corpus workflow (#124); build-once Docker release flow (#140) | #145 to #183 |
| 0.5.6 (2026-10-16, tag at `e099787`) | `docs/api.md` public API reference (#185); `PyTbparseError` common base (#186, first part); `pathlib.Path` accepted everywhere (#187); Node unit tests for the GUI table (#184); `rename --acronyms` (#193) | #188 to #199 |
| unreleased on `main` | Dashboards cards view (#84 option A, #197); Tableau check list and pack (#201, refs #82); review nits of 0.5.6 (#206); layout census (#209) and `GET /dashboard-layout` (#211) for #84; WP7-2a `style extract` and style file v2 (#210); WP7-2b `style apply` for the workbook scope (#213); #84 WP2 panel and drawing (#215); WP8 writer measurement (#208, #214); plan pages #203, #204, #205, #207, #212 | #197 to #215 |

The owner decides when the unreleased work ships. Merged is not released (`AGENTS.md`, "Release rules").

## The work, in order

The order below is the order the owner's decisions and the dependencies allow. Tracks A, B and C are independent of each other and can run side by side; inside a track the order is strict.

### Track A: 0.6.0 exit codes, error classes and the `on_clash` flip (issues #127, #186, #128)

Owner decisions (2026-10-16): the exit-code scheme of [plan-0.6.0-exit-codes-and-errors.md](plan-0.6.0-exit-codes-and-errors.md) is adopted (0 ok, 1 finding, 2 usage, 3 crash, 4 bad input, 5 refused, 6 integrity, 7 partial), all of it in 0.6.0 (no early 0.5.x patch for the error classes); the library `on_clash` default flips to `fail` in 0.6.0; the style default stays `fail` and `replace` stays opt-in.

| # | Item | Status | Plan | Spec | Blocked by |
| --- | --- | --- | --- | --- | --- |
| A1 | `errors.py`: base classes, `ExitCode`, `exit_code_for` (no behaviour change) | planned for 0.6.0 | exit-codes plan, WP1 | `docs/specs/exit-wp1-errors-module.md` | nothing |
| A2 | 25 `raise FileExistsError` sites become `OutputRefusedError` | planned for 0.6.0 | WP2 | `exit-wp2-output-refused.md` | A1 |
| A3 | 38 library `raise ValueError` sites get a class; feature subclasses for refusal and integrity | planned for 0.6.0 | WP3 | `exit-wp3-classify-errors.md` | A2 (owner may veto rows in the PR) |
| A4 | central exit handling in `cli.py`, crash = 3 everywhere, table commands, `diff`, `batch`, `docs` | planned for 0.6.0 | WP4 | `exit-wp4-central-handling.md` | A3 |
| A5 | checks: `validate`, `audit`, `template check`/`drift`, `diff-xml`, `style check` | planned for 0.6.0 | WP5 | `exit-wp5-check-commands.md` | A4 |
| A6 | writers: `sanitize`, `prune`, `slice`, `rename`, `scaffold`, `docs` | planned for 0.6.0 | WP6 | `exit-wp6-writer-commands.md` | A4 |
| A7 | partial results and clashes: `sheet copy`, `dashboard copy`, `library`, `style`, `template` writers, `apply-folder` | planned for 0.6.0 | WP7 | `exit-wp7-partial-and-refused.md` | A4; owner question on dry runs (below) |
| A8 | pre-commit wrapper by precedence, all docs, grep guard | planned for 0.6.0 | WP8 | `exit-wp8-precommit-and-docs.md` | A5, A6, A7 |
| A9 | `webgui.py` `ValueError` sites (optional) | blocked | WP9 | `exit-wp9-webgui-errors.md` | owner: do it in 0.6.0 or drop it |
| A10 | release notes and the 0.6.0 version bump | planned for 0.6.0 (owner-run) | WP10 | `exit-wp10-release-checklist.md` | everything planned for 0.6.0 |
| A11 | library API `on_clash` default `rename` to `fail` | planned for 0.6.0 | [plan-0.6.0-clash-default.md](plan-0.6.0-clash-default.md) | `clash-flip-library-default.md` | nothing (any time before the 0.6.0 release) |

Between A4 and A8 `main` has a mixed scheme; there must be no release in that window (the plan says the header of the `cli.md` table states it).

### Track B: WP7 slice 2, fonts and formatting (roadmap card "style templates slice 2")

Owner decisions (2026-10-16): build all of slice 2, one pull request per package; the owner runs the Tableau checks himself. Plan: [wp7-style-plan-slice2.md](wp7-style-plan-slice2.md). Slice 1 plan: [wp7-style-plan.md](wp7-style-plan.md).

| # | Item | Status | Spec | Blocked by |
| --- | --- | --- | --- | --- |
| B1 | 2a: style file v2, `style extract`, `style show --what` | built, unreleased (#210) | (plan) | |
| B2 | 2b: `style apply` for the workbook scope (fonts, workbook rules) | built, unreleased (#213) | (plan) | |
| B3 | 2c: dashboard defaults by zone role | planned | `docs/specs/wp7-2c-dashboard-roles.md` | B2 built; owner question Q2 (what counts as explicit) |
| B4 | 2d: sheet whitelist (`--scope sheets`) | planned | `wp7-2d-sheet-whitelist.md` | B2 built (B3 recommended first); owner question Q4 (title runs) only for one test |
| B5 | 2e: corpus smoke test and the GUI Formatting card | planned | `wp7-2e-corpus-and-gui.md` | B3 (and B4 if the GUI should show sheets) |
| B6 | 2f: docs and Tableau check rows 43, 45 | planned | `wp7-2f-docs-and-tableau-check.md` | B3, B4, B5 |
| B7 | slice 1b: inline ramps as named palettes | planned in the slice 1 plan, not scheduled | [wp7-style-plan.md](wp7-style-plan.md) section 7 | owner: still wanted? |
| B8 | slice 3: `apply_template(style=)`, `template make --with-style` | blocked | slice 2 plan, Q8 | Tableau check of slice 2 (rows 42 to 44) |
| B9 | Tableau checks 40 to 44 (palettes, fonts, dashboard defaults, keep vs force) | blocked | [tableau-check.md](tableau-check.md) | the owner runs them |

The plan's own advice (Q1) was not to start 2c to 2e before Tableau check 40 is back. The owner's later word was "build all of slice 2"; this page reads that as overriding the advice, but says so here in case it did not.

### Track C: #84 layout preview of the Dashboards view

Owner decisions: option A cards shipped (#197); the preview panel replaces the row drawer on the Dashboards table, focus stays on the row, 200-zone cap shown as "N largest of M", the overlap sentence only above a threshold of crossing pairs (start at 5), `/dashboard-layout` may grow additive fields, WP5 (open the panel from a card) is not planned. Plan: [plan-84-layout-preview.md](plan-84-layout-preview.md); numbers: [layout-census.md](layout-census.md); mockups: `docs/design/84/`.

| # | Item | Status | Spec | Blocked by |
| --- | --- | --- | --- | --- |
| C1 | WP0 layout census | built, unreleased (#209) | (plan) | |
| C2 | WP1 `GET /dashboard-layout` | built, unreleased (#211) | (plan) | |
| C3 | WP2 panel, drawing, list (also the row integration and two additive endpoint fields) | built, unreleased (#215) | (plan) | |
| C4 | WP3 Dashboards table integration: sort/filter survival, debounced requests, Escape, reload | planned | `docs/specs/layout-wp3-table-integration.md` | C3 built |
| C5 | WP4 phone layout, themes, docs | planned | `layout-wp4-phone-themes-docs.md` | C4 |
| C6 | WP5 open the panel from a card | dropped (owner 2026-10-18) | | |
| C7 | screen-reader pass and a comparison with Tableau Desktop | blocked | plan, "What is unverified" | the owner (no screen reader or Tableau here) |

PR #215 already does part of what the plan called WP3 (a row opens the panel instead of the drawer, "All columns", focus stays on the row, changing table closes the panel). The WP3 spec covers only what is left.

### Track D: writer fidelity (WP8)

| Item | Status | Doc |
| --- | --- | --- |
| WP8 minimum: `diff-xml`, `template apply --xml-diff` | built (0.4.x/0.5.x) | [diff-xml.md](diff-xml.md) |
| Measurement of how much each writer rewrites | built, unreleased (#208, #214) | [wp8-measurement.md](wp8-measurement.md) |
| WP8 stretch: byte-preserving output (text-level patching) | dropped (owner 2026-10-18: no spike, stay at the `diff-xml` minimum) | board card "Writer: byte-preserving workbook output" is still Todo and should be closed or moved |

### Track E: checks only a person with Tableau Desktop can do

| Item | Status | Doc / issue |
| --- | --- | --- |
| 30-minute check list for every writer | blocked: the owner runs it himself | [tableau-check.md](tableau-check.md), `scripts/make_tableau_check_pack.py`, #82 |
| Template on Excel, on a database target, several tables | blocked (same) | [verify-in-tableau.md](verify-in-tableau.md), [template-next-plan.md](template-next-plan.md) section 7 item 4 |
| WP4b leftovers: borrowed remote types, missing metadata children, Snowflake identifier case | blocked (needs Tableau or samples) | #39 |

Every planned writer change (B3 to B6) adds rows to the check list; none of them can be called "works in Tableau" until the owner reports back.

### Other open items

| Item | Status | Where |
| --- | --- | --- |
| #79 Datasources table limits | built in large part (#114, #167); the issue stays open on the owner's word (the reporter's case was never seen) | #79 |
| Rename: custom acronyms and style in the GUI | the CLI has `--style` and `--acronyms` (verified in `cli.py`); the GUI has neither (verified: no match in `webui/` or `webgui.py`). Not scheduled. | board card "Rename: custom acronyms and style in the CLI and GUI" |
| WP6 next slice: bins, `overwrite`, sets, categorical bins, folders on import, cross-datasource calcs | not scheduled | [wp6-library-design.md](wp6-library-design.md) section 9 |
| WP12 fake data from an SQL-type schema | not scheduled | [template-next-plan.md](template-next-plan.md) 5.3 |
| WP3 stage C, three-way merge | not wanted yet (owner) | [template-roadmap-plan.md](template-roadmap-plan.md) WP3 |
| WP4b part 2: Oracle, Spark, Mongo, published data sources | blocked: no samples; refused without `--experimental` | [template-next-plan.md](template-next-plan.md) 4.4 |
| WP13 localisation, WP15 compatibility report, rest of WP16 scaffolds, WP17d/f unions | not started; no card, no owner decision to start | [template-roadmap-plan.md](template-roadmap-plan.md) 4b |
| Token scope: sheet and dashboard names, parameter captions, default filter values | open owner question since 2026-10-05 | [next-steps.md](next-steps.md) section 4 |

## Old work-package numbers, board cards and issues

The WP numbers come from [template-roadmap-plan.md](template-roadmap-plan.md) (2026-10-02). The board is GitHub project #6 (read with `gh project item-list 6 --owner DDSNA` on 2026-10-22).

| Old WP | What | Board card (status on the board) | Issues / PRs | Real state |
| --- | --- | --- | --- | --- |
| WP0 | verification harness | "Verify generated workbooks open in Tableau" (Todo) | #82, #201 | harness built; the manual part is Track E |
| WP1 | answers, ids, matcher, explain | none | | built |
| WP2 | Excel input | "Templates: read Excel files directly as data" (Done) | | built |
| WP3 | `template update` | "Templates: template update from saved answers" (Done) | | stages A, B built; C not wanted |
| WP4, WP4b | `apply-folder`; database targets | "Templates: apply one template across a folder of data files" (Done) | #39 | built; #39 needs Tableau |
| WP5 | `template check`, `show --markdown` | none | #23 | built |
| WP6 | calculation and parameter libraries | "Templates: calculated-field and parameter libraries" (Done) | | first slice built; next slice not scheduled |
| WP7 | style templates | "style templates slice 1 (palettes)" (Done); "style templates slice 2 (fonts, formatting)" (In Progress) | #210, #213 | Track B |
| WP8 | writer fidelity | "byte-preserving output, minimum (diff-xml)" (Done); "Writer: byte-preserving workbook output" (Todo) | #208 | minimum built; stretch dropped: the Todo card is stale |
| WP9 | GUI Templates view | "[UI] Phase 4: guided workflows and Templates view (0.6.0)" (Done) | | built (the "0.6.0" in the card title was an early guess; it shipped in 0.5.x) |
| WP10, WP10b, WP11 | audit, `prune`, data dictionary | "Run the corpus tests in CI" (Done) is related | #75, #98, #124 | built at the basic level |
| WP12 | `sanitize` | none | #91 | built; fake data from a schema not built |
| WP13 | localisation | none | | not started |
| WP14 | combine, extract, move sheets | none | sheet copy, dashboard copy, slice | built as 14b to 14f (the roadmap's own status box still says "not started": stale) |
| WP15 | compatibility report | none | | not started, parked |
| WP16 | dashboard scaffolds | none | | 16a, 16b built; rest not started |
| WP17 | unions, `template drift` | none | | 17b, 17c built; 17d, 17f wait for samples |
| WP18 | CI output formats | none | | built |
| WP19 | template tokens | none | #20, #42 | built; scope question open |
| (UI) | redesign phases 1 to 4 | four "[UI] Phase" cards (Done) | #12 and earlier | built ([ui-redesign-plan.md](ui-redesign-plan.md) section 11) |
| (new) | exit codes, error classes | none for the plan; issues on the board | #127, #186 | Track A |
| (new) | library `on_clash` default | issue on the board | #128 | Track A, A11 |
| (new) | Dashboards cards and preview | issue on the board | #84 | Track C |
| (new) | docs/api, Path handling, Node tests | #185 (Done), #187 (In Progress), #184 (In Progress) | #189, #191, #194 | built and released in 0.5.6; #184 and #187 are closed issues still shown In Progress: stale |
| (new) | rename acronyms | "Rename: custom acronyms and style in the CLI and GUI" (Todo) | #193, #195 | CLI part released in 0.5.6; GUI part not built |

Board cards that are out of date (for the owner to move; this page does not edit the board): "Writer: byte-preserving workbook output" (dropped), #184 and #187 (closed, shown In Progress), "Rename: custom acronyms..." (half done), "Verify generated workbooks open in Tableau" (now the check list of #82).

### Old plan sections that are stale

- [template-roadmap-plan.md](template-roadmap-plan.md): the status box (WP7 line says "2b onwards not started", WP14 "not started"), section 0 (commit identity "Dan", the handoff file, `python -m pytest`), section 2 WP9 ("separate track, do not start"), section 4 (questions all answered or superseded by `AGENTS.md` "Versioning"), section 5 (first message for WP1), the "Backlog hygiene" bullet in section 3 (`py-tbparse-backlog.json` is a local file, not in the repo). Its research (section 1, 4b) and the WP texts remain the record.
- [template-next-plan.md](template-next-plan.md) and [next-steps.md](next-steps.md): history, as their own headers say. Their "Current state" tables stop at 0.5.3 and say WP7 fonts "not started".
- [wp7-style-plan.md](wp7-style-plan.md) section 7 "Deferred" item 2 (slice 2 "needs owner answers Q3 and one Tableau check before design") and Q3: superseded by the owner's "build all of slice 2".
- [wp7-style-plan-slice2.md](wp7-style-plan-slice2.md) section 6 exit codes (0/1/2) will change with Track A; its status row says "2b onwards not started" (2b is in PR #213).
- [plan-84-layout-preview.md](plan-84-layout-preview.md): the "Questions for the owner" list (all four answered, recorded in #84) and the WP3 text (PR #215 did part of it).
- [plan-0.6.0-exit-codes-and-errors.md](plan-0.6.0-exit-codes-and-errors.md): site counts and line numbers were taken at `1fa6acd`; on `1130fa9` there are 38 library `ValueError` sites (same), 40 in `webgui.py` (plan: 39) and 25 `FileExistsError` sites (plan: 24; `style.py` has four). Open question 11 (early 0.5.x patch) is answered: no.
- `docs/cli.md` "Exit codes" says the scheme is "an open design question": it is decided, not yet built.
- `AGENTS.md` `xmldiff.py` row ("The stretch ... is not built") is right but does not say it was dropped.

## Owner questions still open

Decided questions are not repeated here. These block or shape the work above:

1. Exit codes, dry runs (plan open question 5): should every dry run return the code its real run would? Plan default: `style import` dry-run clash becomes 5, `library import` dry run stays 0. The plan does not cover `sheet copy`/`dashboard copy`: their dry run with a refused sheet returns 2 today, like `--write` (read in `cli.py`), and would become 7 if it follows the write. Blocks the last commit of A7.
2. `webgui.py` errors (plan WP9, question 10): in 0.6.0 or dropped? Blocks A9.
3. This page reads "exit-code scheme adopted as in the plan" as covering the plan's choices too: `validate` broken relationship = 6, unknown dashboard or sheet name = 4, precedence 3, 2, 4, 5, 6, 7, 1, 0 for the pre-commit wrapper, `apply-folder` with nothing written = 7, no compatibility switch, no `E001` codes, no `DashboardCopyError`. Confirm, or say which differs.
4. WP7 slice 2 Q2: does any existing format count as explicit (Tableau's boilerplate `margin 4` included), so a default restyle skips it? PR #213 builds it that way for workbook rules; 2c is where it matters most.
5. WP7 slice 2 Q4: copy title run formatting (fonts in `<run>`) without the text? Plan default: no in this slice.
6. Release grouping: do WP7 slice 2 and the #84 preview ship in 0.6.0 with Track A, or in a 0.5.x before it? And does the unreleased work on `main` (cards, check list, 2a) get a 0.5.7 first?
7. WP7 slice 1b (inline ramps): still wanted?
8. Board hygiene: close or move the stale cards listed above?
9. Screenshots: `AGENTS.md` retakes them at every major release. Does 0.6.0 (a breaking minor while 0.x) count?

## Proposed product direction (a proposal, not a decision)

**This section is a proposal written from the README, the docs and the issues. The owner has not agreed to it. Nothing here changes a plan or a status above.**

What the tool is for: reading a Tableau workbook without Tableau, and making safe new copies of it. The README's first lines say it: show what is inside, check it for problems, and make a new file (cleaner names, no private details, fewer dashboards, sheets or calculations from another workbook, new data from a template), never changing the original. Every writer follows three rules that appear in every plan: never overwrite the input, report what was done and what was not, say what has not been checked in Tableau.

Who uses it (inferred from the README's two halves and the issues):

- People who build Tableau workbooks and do not program: the browser app (the user's guide is written for them; GUI work is a large share of recent issues: #84, #142 to #144).
- People who maintain many workbooks or run checks in CI: the command line, the exit codes (#127), JUnit/SARIF output, the pre-commit hooks.
- Python users: the library API (`docs/api.md`), which is why the `on_clash` default (#128) and the error classes (#186) matter.
- Teams that share the app: the Docker image behind a proxy (no login of its own).

Out of scope (from the plan pages' non-goals and the owner's past answers): publishing to Tableau Server or Cloud; Tableau-to-Power-BI conversion; editing a workbook in place; a downgrade writer; recolouring marks; byte-for-byte output (dropped, `diff-xml` instead); a login system in the app; claiming that an output opens in Tableau without a person checking it.

Questions for the owner about this direction:

1. Is the browser app or the command line the first-class interface when the two compete for time (for example, rename acronyms exist only on the command line)?
2. Should the remaining R-port gaps (formatting, tooltips, axes, sorts, actions, the replication brief) stay listed as "not yet ported", or be declared out of scope now that the project has gone its own way?
3. Is localisation (WP13) or the next library slice (sets, bins) the next feature track after 0.6.0, or neither?
4. Should every new writer wait for a Tableau check before it is released, or is "schema-valid, not opened in Tableau" in the docs enough, as now?
