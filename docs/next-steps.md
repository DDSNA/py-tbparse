# py-tbparse: where things stand and what to do next

Written 2026-10-02 for the next agent. Verify against the repo before relying on anything: `git log`,
`gh pr list -R DDSNA/py-tbparse`, `git ls-remote --heads origin`. How to work with the owner and in this sandbox:
`CLAUDE.md` (local, not tracked; if it is missing, the rules are: commit as Dan with no Claude attribution, never
push / PR / merge / release unasked, work in a fresh worktree off `origin/main`, templating releases are 0.5.x).
Architecture and testing conventions: `AGENTS.md`. The long plan with research and all work packages (WP0 to WP19):
`docs/template-roadmap-plan.md` on the branch `docs/template-roadmap`.

## 1. State

| What | Where | State |
|---|---|---|
| `main` | origin | 0.4.5, tagged `v0.4.5`. PRs #15 to #17 (themes, screenshots, Docker server mode) merged. No open PRs. |
| WP0: verification | branch `worktree-wp0-verification` (3 commits) | pushed, no PR. Schema + reference checks, Tableau pack, 3 template-apply bugs fixed, 1 more found in Tableau. |
| WP1: answers, ids, matcher, explain | branch `wp1-answers-matcher` (1 commit on top of WP0) | pushed, no PR. Based on 0.4.4; a dry-run merge into current `main` is clean (no conflicts). |
| WP3 (stages A, B) and WP2 (Excel) | branch `wp3-template-update`, two commits on top of WP1 (`b71b5e1` WP3, then WP2) | **local only, not pushed, no PR.** Built 2026-10-02 after this file was first written; see "Done since" below. WP2 stacks on WP3 (both touch `templates.py`); to get two PRs, cherry-pick the WP2 commit onto a branch off WP3. |
| The plan | branch `docs/template-roadmap` | pushed, unmerged. |
| Stale | `worktree-docker-server` (merged as #17) | can be deleted; ask the owner. |

Tests on the WP1 branch: 449 non-browser tests pass (about 3.5 minutes, corpus included). **The browser (GUI)
suites were not run on either branch** (no page code changed, but `main` has since changed `webgui.py` and the page).

What was built, in one paragraph each:

- **WP0** (`py_tbparse/verify.py`, `tests/schema_check.py`, `tests/test_schema.py`, `tests/test_verify.py`,
  `scripts/make_verification_pack.py`, `docs/verify-in-tableau.md`): everything that writes a workbook is checked
  against Tableau's published XSD (vendored in `tests/schemas/`, Apache-2.0) and by `validate_workbook()` for
  dangling references. Both are differential (only what the output has and the input did not), because real
  workbooks mostly fail the 2026.2 schema already. The owner opened the pack in Tableau: the CSV-backed and
  workbook-backed outputs drew their sheets.
- **WP1** (`py_tbparse/templates.py`, `cli.py`, `tests/test_templates_v2.py`, `test_matcher.py`, `test_explain.py`):
  manifest version 2 (template `id`, `revision`, a `uid` per field), answers version 2 (per-datasource entries,
  `profiles`, a schema fingerprint; never credentials), `apply_template(answers=, profile=)` through
  `resolve_apply()` / `ApplyPlan`, matcher improvements (alias, deterministic ties, `role differs`), `check_data()`,
  `explain()`, and `broken_sheets()` naming dashboards, calculations and filters. CLI: `--answers`, `--profile`,
  `--explain`, `--check`, `--deep`. Documented in `docs/templates.md`.

### Done since (branch `wp3-template-update`)

- **WP3 stages A and B** (`py_tbparse/template_update.py`, `tests/test_template_update.py`, CLI `template update`,
  `make_template(revision_of=)`): the report (`template_update_report`, `diff_template_revisions`) and the re-apply
  (`update_from_answers`) as designed in section 3 below, with these decisions: apply now keeps a manifest snapshot
  (`answers["template"]["manifest"]`) and `data.columns` in the answers, so the "before" needs no old template file
  (`--old` for answers made before that); a renamed field (same source column or caption, new local name) carries its
  saved column; a saved parameter value the template no longer accepts is dropped and reported rather than stopping;
  a new required field or a saved column of the wrong type stops it unless `--allow-missing` / `--mapping`; a workbook
  made from several datasources is refused (re-applying one would drop the others' connections). Stage C is not started.
- **WP2 Excel** (`read_data(sheet=)`, `_excel_connection`, `tests/test_excel.py`, `--sheet`, extra `py-tbparse[excel]`,
  `openpyxl` in `[test]`): the connection shape and remote types were measured from the 88 `excel-direct` corpus
  workbooks (string 130, integer 20, real 5, date and datetime 7, boolean 11; `gridOrigin`, `[Sheet$]`). `.xls`/`.xlsb`
  are refused (assumed decision, still the owner's). The verification pack has `4-template-on-excel.twbx`: **not yet
  opened in Tableau**, that is the owner's check. `_csv_connection` and `_excel_connection` now share `_file_connection`
  (the CSV output is byte-identical to before). Not done: `check_data` reads values only from CSV; a template over several
  tables is still unproven for Excel as for CSV.
- Tests: whole non-browser suite (see the final report of the job); the browser suites were not run (no page code changed).

## 2. Do first

1. **Land WP0 and WP1.** Ask the owner how: two PRs in order (WP0 into `main`, then WP1 retargeted to `main`), or one.
   Before opening, rebase or merge `origin/main` into the branch, run the whole suite including the browser suites
   (`./scripts/setup-browser-libs.sh` once; `pytest -q tests/test_gui_*.py`, one Chromium at a time), and update
   `AGENTS.md` if `main` changed anything it describes. Squash-merge is what the owner uses.
2. **Version.** When the owner plans the merge, bump `pyproject.toml` to **0.5.0** in the branch (not before). Release
   notes follow `/home/claude-user/ai-sandbox/release-0.4.5.md`; the pre-release and wheel smoke-test checklist is in
   `release-plan-0.4.5.md` and `AGENTS.md`. A release is the owner's call, never yours.
3. **More Tableau checks (the owner does them; you prepare the files).** Re-run
   `python scripts/make_verification_pack.py <new folder>` on the merged code, and extend it for what is still
   unchecked: a workbook that writes the object model in the plain form (corpus example
   `AlexAlkhatib__alex-the-analyst__Classeur.twb`), a template over several tables, and file 1 (renamed) with its
   data reachable so the new captions can be seen. Record results in the Status section of
   `docs/verify-in-tableau.md`. The first run found a real bug the tests missed: expect that to happen again.
4. **Backlog hygiene** (only if asked): the JSON and GitHub Project 6 do not yet list WP0, WP1, WP5 or the
   "connection targets" stretch. See `CLAUDE.md`.

## 3. Next work packages

Order the owner approved in principle: WP3 stages A and B, then WP2. Both depend only on WP1. Everything below is
my design; the plan has more detail. Each package is one branch and one PR, test-first, with a corpus smoke test,
docs and CLI help, and no version bump until a merge is planned.

### WP3: `template update` from saved answers (stages A and B)

Goal: the author improves a template; a user re-applies it to the same data and mapping and learns what changed.
Stage C (three-way merge) is **not** to be started: it needs a design note and the owner's go.

1. `make_template(..., revision_of=OLD)`: keep the old template's `id`, set `revision = old + 1` (today
   `make_template` accepts `template_id` but always writes revision 1).
2. **Stage A, report only**: `diff_template_revisions(old_manifest, new_manifest) -> DataFrame` (fields added /
   removed / renamed by `uid`, falling back to name; `required` flag changes; type changes; parameters added,
   removed, default or allowed values changed; sheets and dashboards added or removed). Then classify each against
   the saved mapping: `auto-carry`, `needs-mapping` (new required field), `orphaned` (mapping targets a removed
   field), `type-conflict`. CLI: `template update NEW_TEMPLATE WORKBOOK` prints it and writes nothing.
3. **Stage B, re-apply**: `update_from_answers(template, workbook, output_path=None, overwrite=False, report=None)`
   = `resolve_apply(new, answers=workbook)` plus `apply_template`. Stop and list `needs-mapping` rows unless
   `--allow-missing`. Use the data's fingerprint (WP1) to say which columns appeared or vanished and re-suggest only
   those.
4. Guards: same `manifest_sha256` in the answers = no-op, say so; different template `id` = refuse (already done in
   `resolve_apply`); answers from a version 1 template (no `id`) = allowed, say it cannot be checked.
5. Tests: add a field, remove a field, rename a caption (uid unchanged), change a parameter default, change a type,
   moved data file, answers from another template, a snapshot of the stage A table. Corpus: for every workbook make
   revision 2 identical to 1 and expect an empty report.

### WP2: Excel input (`.xlsx`, `.xlsm`)

1. `openpyxl` as an optional extra (`excel = ["openpyxl>=3.1"]`) and in the `test` extra; import lazily and raise
   `TemplateError("install py-tbparse[excel]")`. Legacy `.xls`: refuse with a clear message (owner decision pending,
   assumed no). It is not installed in the shared venv yet.
2. `read_data(path, datasource=None, sheet=None)`: sheet by name or index; several visible sheets and none chosen =
   fail listing them; hidden sheets ignored unless named; first non-empty row is the header; duplicate headers get a
   suffix and a warning; read 2000 rows for type inference with the existing `_infer_csv_type`. `DataSource` gets
   `sheet`; answers record it (`data.sheet`); CLI `--sheet`.
3. **Connection writer** `_excel_connection(data, local_of, model, object_id)` beside `_csv_connection`, same two
   object-model dialects (`_object_model()`), same rules (keep the template's object id, table column after
   `<aliases>`). **Copy what Tableau writes**: 88 corpus workbooks use `excel-direct`
   (`grep -l excel-direct tests/corpus/files/*`). Check the relation name (`[Sheet$]`), the `cols`/`map` shape, the
   remote-type codes for Excel (they differ from text files: measure them from the corpus, as was done for CSV),
   and whether an Excel datasource keeps its `<named-connection>` the same way.
4. Tests: small workbooks built with openpyxl in `tmp_path`; multi-sheet error; header offset; duplicate headers;
   dates; missing extra gives the install hint; the differential schema and reference checks from `tests/test_schema.py`
   on an Excel-backed output; extend `make_verification_pack.py` with an Excel-backed file for the owner.

### After that

Plan section 4b.4 suggests: WP19 template tokens (with WP1 answers and WP4 batch), WP12 sanitize, WP10 audit and
prune, WP18 CI output formats, then WP13, WP14, WP17, WP16; park WP15 (downgrade writer), Power BI conversion and
publishing. WP4 (batch apply) and WP5 (template check) are small and high value. WP9 (GUI Templates view) waits for
the owner and for Tableau results.

## 4. Questions for the owner (do not decide them)

- How to land WP0 and WP1 (section 2.1), and the 0.5.0 timing.
- `.xls`; three-way merge; whether batch / folder-of-customers is a real use case and a sidecar CSV is enough; live
  database and published-datasource targets; `.tps` palettes first or the whole style template; which of WP10 to
  WP19 matter; whether synthetic fake-data generation is in scope; whether py-tbparse should also be an audit tool.
- Delete the stale remote branch `worktree-docker-server`, and the shared venv and main checkout need an update
  (`git pull --ff-only` there, then `.venv/bin/pip install -e .`); that is theirs to do or to allow.

## 5. Known gaps and things I would check

- **Templates over several tables**: a CSV feeds one table. `_csv_connection` writes one object and one table
  column; sheets that count another table's rows (`[__tableau_internal_object_id__].[cnt:...]`) would point at
  nothing. The corpus differential test passes, but it only applies the first datasource with fields and excuses
  fields the CSV cannot feed, so this is not proven either way. Look at multi-object workbooks (corpus files with
  `relation:collection` or `relation:join`) before relying on it.
- `field_usage` did not report the set `BurstoutSet` as depending on a field in `filtering.twb`, so `explain` and
  `broken_sheets` name the sheets and dashboard but no calculation or set there. Check how `_datasource_fields`
  reads `<group>` elements.
- `explain` does not follow parameters; `check_data` reads values only for a CSV and its key heuristic is a guess
  at names (`*_id`, `*_key`, `*_code`).
- Profiles must be written into the answers file by hand; there is no `template profile` command and no command that
  extracts a standalone `*.answers.json` from a workbook (the Python `read_answers` does).
- `verify.py`'s `calc-reference` findings are warnings because a bracketed word inside a string counts as a
  reference; the corpus has 14 such findings in its original workbooks already.
- The schema is 2026.2 only; most corpus workbooks are 18.1. The differential approach hides that, but a real
  `<ManifestByVersion/>` / version alignment (see `tests/schemas/UPSTREAM-README.md`) is untested.
- `tests/test_version.py` fails in this sandbox on a branch whose version differs from the owner's checkout (the
  shared venv's editable install); not a branch bug.

## 6. Starting a package (checklist)

1. Read `AGENTS.md`, `CLAUDE.md` if present, this file, and the plan section for the package.
2. `EnterWorktree` (fresh, off `origin/main`) or, for a stacked package, `git worktree add -b NAME PATH BRANCH` and
   `EnterWorktree` with `path`. Fetch the corpus: `python3 scripts/fetch_corpus.py`.
3. Baseline: `PYTHONPATH=. /home/claude-user/ai-sandbox/py-tbparse/.venv/bin/python -m pytest -q` for the files you
   will touch. Write the failing test first.
4. Build; run the corpus tests; run the differential checks if you write XML; update docs, CLI help, `AGENTS.md`.
5. Commit as Dan (no attribution), check authors, and stop: push, PR and merge only when told.
