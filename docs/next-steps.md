# py-tbparse: where things stand (history of WP0 to WP5)

> **This file is history.** The plan is `docs/template-roadmap-plan.md` (research, every work package, order). For
> what is current, do not trust any page in `docs/`: run `git log --oneline -20`, `gh pr list` and `gh issue list`,
> and read `pyproject.toml` for the version. Rules for the work and the release: `AGENTS.md` ("Versioning",
> "Release rules"). `docs/template-next-plan.md` keeps the detailed designs of packages A to F, all built now.

Last refreshed 2026-10-06 (main at `4469dfa`, version 0.5.3 released as `v0.5.3`). Sections 1 (from "What was built")
to 6 below were written on 2026-10-02 to 2026-10-05 and are kept for what was built, the decisions and the known
gaps; whatever they say is open or unreleased is out of date unless the table here agrees.

## Current state (2026-10-06)

| Package | State on `main` |
|---|---|
| WP0 verification harness | done (`verify.py`, XSD differential; the owner opened the CSV and workbook outputs in Tableau) |
| WP1 answers, ids, matcher, explain | done |
| WP2 Excel input, WP3 `template update` (stages A, B), WP4 `apply-folder` | done; WP3 stage C (three-way merge) not started, not wanted yet |
| WP4b part 1 database targets (MySQL, PostgreSQL, SQL Server, Snowflake) | done; leftovers in issue #39; part 2 (Oracle, Spark, Mongo, published data sources) has no samples and stays refused without `--experimental` |
| WP5 `template check`, `show --markdown`; WP19 tokens | done |
| WP6 libraries of calculated fields and parameters | first slice done; GUI Libraries view done |
| WP7 colour palettes | slice 1 done (`style show/export/import/check`); GUI Styles view done; fonts and formatting not started |
| WP8 writer fidelity | minimum done (`diff-xml`, `template apply --xml-diff`) |
| WP9 GUI Templates view | done |
| WP10 audit (A001-A011), WP10b `prune`, WP11 data dictionary | done at the basic level; GUI Audit view done |
| WP12 `sanitize` | done (fake data from an SQL-type schema is not) |
| WP16 dashboard scaffolds | first slice done (16a, 16b: zone resolver, `scaffold make/show/apply`) |
| WP17 17b, 17c many files as one source, `template drift` | done |
| WP18 JUnit, SARIF and GitHub output | done |
| WP13, WP14, WP15, rest of WP16 | not started |

Open at this date: issue #39 (WP4b leftovers), #76 to #84 (bugs and follow-ups), #82 (nothing generated has been
opened in Tableau beyond the WP0 pack). Nothing written for Excel, databases, tokens, scaffolds or styles has been
opened in Tableau.

## 1. What was built (written 2026-10-05, WP0 to WP5)

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

### Done since (merged: WP2 to WP4 through #18, released in 0.4.6; WP19, WP4b part 1 and WP5 through #20, #21 and #23, released in 0.5.0)

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
- **WP4 batch apply** (`py_tbparse/template_batch.py`, `tests/test_template_batch.py`, CLI `template apply-folder`): one
  workbook per file, `summary.csv`, sidecar CSV for per-file parameters and sheet, tolerance gate (`--min-mapped`),
  `--on-error`, `--workers`. Owner confirmed the folder-of-customers use case (2026-10-04). Connection targets (live DBs,
  published data sources: standard DBMS + Spark, Mongo if feasible, standard connectors, no credentials) are WP4b:
  part 1 is merged as #21 (open leftovers: issue #39), part 2 has no samples and will not get any (section 2).
- **WP19 template tokens** (package C, merged as #20): `py_tbparse/tokens.py`, `{{name}}` in titles, text objects, field
  and datasource captions and string parameter values; `--token` on `make`, `apply`, `apply-folder` and `update`; sidecar
  columns. **Not covered**: worksheet and dashboard names, parameter captions, default filter values (an open scope
  question for the owner). Review findings #24 to #27 were fixed in #40.
- **Docker publish workflow** (#22): see the state table; never run.
- **WP5 template check and `show --markdown`** (package D, merged as #23: `py_tbparse/findings.py`,
  `template_check.py`, `docgen.py`, `tests/test_findings.py`, `test_template_check.py`, `test_docgen.py`, a corpus test in
  `test_corpus.py`): the shared findings engine (stable rule ids, sorted deterministic frame, `table|csv|json` through a
  registry, a crashing rule becomes an `error` finding), template rules T001 to T010, `template check
  [--format --fail-on --only --skip]` (exit 1 on a finding at `--fail-on`, 2 on a usage or read error, 3 when a rule
  crashed) and `template show --markdown [-o FILE]`. T009 (the token rule) was built in #42, together with the fixes
  for #28 to #30. Not opened in Tableau: it writes no workbook.
- Tests: the whole non-browser suite was not re-run for this refresh. The numbers in the older PR bodies (519 passed
  after WP4; 668 passed with WP4b part 1) are from before later merges. The browser suites were not run on the
  merges since 0.4.6; #35 changed `webgui.py`.

## 2. Do first (out of date)

Replaced on 2026-10-06. Take the next package from `docs/template-roadmap-plan.md` and the open issues, and use the
checklist in section 6. Two items from the old list still stand: more Tableau checks are the owner's (you prepare the
files with `python scripts/make_verification_pack.py <new folder>` and record results in the Status section of
`docs/verify-in-tableau.md`), and the version rules are in `AGENTS.md`.

## 3. Next work packages (history)

History: WP3 (stages A and B) and WP2 below were built and merged through #18 (released in 0.4.6); the current plan
is `docs/template-next-plan.md`. The text below is the original design, kept as written on 2026-10-02; its
"patch release" and "no version bump" remarks are superseded by "Versioning" in `AGENTS.md`.

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

Answered since: landing (one PR per package), `.xls` (refused unless small), sample workbooks (none will come),
batch and connection targets (wanted), fake data (only from an SQL-type schema), audit (basic), versions (patch per
package, no bump inside PRs, release on his word; on 2026-10-05 he settled 0.5.0 as the first templating release, see
"Versioning" in `AGENTS.md`). Still open:

- Token scope: worksheet and dashboard names, parameter captions, default filter values are not token places yet.
- Branch protection: `main` had none when checked on 2026-10-04 (not re-checked); require CI before merge or not.
- Squash merges in the web UI make commits authored "Dan", not DDSNA; whether that matters.
- Three-way merge (WP3 stage C); `.tps` palettes first or the whole style template; WP18 or `prune` after the basic
  audit.
- Delete the merged branches still on origin (section 1). The shared venv and main checkout need an update
  (`git pull --ff-only` there, then `.venv/bin/pip install -e .`); that is the owner's to do or to allow.

## 5. Known gaps and things I would check

- **Templates over several tables**: a CSV feeds one table. `_csv_connection` writes one object and one table
  column; sheets that count another table's rows (`[__tableau_internal_object_id__].[cnt:...]`) would point at
  nothing. The corpus differential test passes, but it only applies the first datasource with fields and excuses
  fields the CSV cannot feed, so this is not proven either way. Look at multi-object workbooks (corpus files with
  `relation:collection` or `relation:join`) before relying on it.
- Fixed in the WP1 review: `field_usage` did not tie a set to its field when the set names the field by a derived
  name (`[none:Region:nk]`, 31% of group references in the corpus), so a sheet that used only the set did not make
  the field `required`. `usage._base_field` now resolves it. Other derived forms (table calculations such as
  `[pcdf:sum:Sales:qk]`) are not resolved.
- `explain` does not list parameters (none in the corpus depends on a field; there are no parameter actions either);
  `check_data` reads values only for a CSV and its key heuristic is a guess at names (`*_id`, `*_key`, `*_code`).
- `role differs` can only fire when the new data is a workbook or `.tds` (a CSV has no roles).
- Profiles must be written into the answers file by hand; there is no `template profile` command and no command that
  extracts a standalone `*.answers.json` from a workbook (the Python `read_answers` does).
- `verify.py`'s `calc-reference` findings are warnings because a bracketed word inside a string counts as a
  reference; the corpus has 14 such findings in its original workbooks already.
- The schema is 2026.2 only; most corpus workbooks are 18.1. The differential approach hides that, but a real
  `<ManifestByVersion/>` / version alignment (see `tests/schemas/UPSTREAM-README.md`) is untested.
- `tests/test_version.py` fails in this sandbox on a branch whose version differs from the owner's checkout (the
  shared venv's editable install); not a branch bug.
- **Tokens** do not cover worksheet and dashboard names, parameter captions or default filter values (owner question).
  The T009 token rule in `template check` exists (#42).
- **Windows server race, fixed in #35.** CI run 37229010116 on `main` (`4a3cfff`) failed once in
  `tests/test_webgui.py::test_load_requires_json_content_type[text/plain]` (Windows, Python 3.12) and passed on the
  re-run; `webgui._do_post` now drains the request body before an early refusal. Whether it is gone on CI has not
  been re-checked here.

## 6. Starting a package (checklist)

1. Read `AGENTS.md`, `CLAUDE.md` if present, this file, and the plan section for the package.
2. `EnterWorktree` (fresh, off `origin/main`) or, for a stacked package, `git worktree add -b NAME PATH BRANCH` and
   `EnterWorktree` with `path`. Fetch the corpus: `python3 scripts/fetch_corpus.py`.
3. Baseline: `PYTHONPATH=. python -m pytest -q` (your own venv; the author uses a shared one at a local path) for the files you
   will touch. Write the failing test first.
4. Build; run the corpus tests; run the differential checks if you write XML; update docs, CLI help, `AGENTS.md`.
5. Commit as `DDSNA` (no attribution; see `AGENTS.md`), check authors, and stop: push, PR and merge only when told.
