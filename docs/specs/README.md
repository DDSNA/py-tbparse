# Implementation specs

Part of [py-tbparse](https://github.com/DDSNA/py-tbparse). One file per work package, written so that an agent can build the package without asking questions. The plan pages say why; these files say exactly what to change. The overall order and status are in [../ROADMAP.md](../ROADMAP.md).

Written 2026-10-22 against `main` at `1130fa9`. File names, functions and line numbers were read on that commit (and, where a spec builds on an open pull request, on that PR's head commit, named in the spec). Line numbers drift: search for the function name, not the number. Where a spec was not sure that `main` matches its reading it says so in a "Check first" line.

## Order

Three tracks, independent of each other. Inside a track, do the packages in this order; a package starts only after the one before it is **merged** (not just open).

| Order | Spec | Track | Depends on | Blocked by an owner question? |
| --- | --- | --- | --- | --- |
| A1 | [exit-wp1-errors-module.md](exit-wp1-errors-module.md) | 0.6.0 errors and exit codes | nothing | no |
| A2 | [exit-wp2-output-refused.md](exit-wp2-output-refused.md) | 0.6.0 | A1 | no |
| A3 | [exit-wp3-classify-errors.md](exit-wp3-classify-errors.md) | 0.6.0 | A2 | no (the owner may veto rows in the PR) |
| A4 | [exit-wp4-central-handling.md](exit-wp4-central-handling.md) | 0.6.0 | A3 | no |
| A5 | [exit-wp5-check-commands.md](exit-wp5-check-commands.md) | 0.6.0 | A4 | no |
| A6 | [exit-wp6-writer-commands.md](exit-wp6-writer-commands.md) | 0.6.0 | A4 (A5 not needed) | no |
| A7 | [exit-wp7-partial-and-refused.md](exit-wp7-partial-and-refused.md) | 0.6.0 | A4 | **yes**: dry-run codes (one row) |
| A8 | [exit-wp8-precommit-and-docs.md](exit-wp8-precommit-and-docs.md) | 0.6.0 | A5, A6, A7 | no |
| A9 | [exit-wp9-webgui-errors.md](exit-wp9-webgui-errors.md) | 0.6.0 (optional) | A3 | **yes**: do it at all |
| A10 | [exit-wp10-release-checklist.md](exit-wp10-release-checklist.md) | 0.6.0, owner-run | all of 0.6.0 | owner runs it |
| A11 | [clash-flip-library-default.md](clash-flip-library-default.md) | 0.6.0 | nothing (any time before A10) | no |
| B3 | [wp7-2c-dashboard-roles.md](wp7-2c-dashboard-roles.md) | WP7 slice 2 | PR #213 (2b) merged | **yes**: Q2 gates the merge |
| B4 | [wp7-2d-sheet-whitelist.md](wp7-2d-sheet-whitelist.md) | WP7 slice 2 | 2b merged; 2c first is recommended | one test waits on Q4 |
| B5 | [wp7-2e-corpus-and-gui.md](wp7-2e-corpus-and-gui.md) | WP7 slice 2 | 2c (and 2d for the sheets part) | no |
| B6 | [wp7-2f-docs-and-tableau-check.md](wp7-2f-docs-and-tableau-check.md) | WP7 slice 2 | 2c, 2d, 2e | no |
| C4 | [layout-wp3-table-integration.md](layout-wp3-table-integration.md) | #84 preview | PR #215 (WP2) merged | no |
| C5 | [layout-wp4-phone-themes-docs.md](layout-wp4-phone-themes-docs.md) | #84 preview | C4 | no |

A6 and A7 may run in parallel after A4, but both edit `docs/cli.md` and `tests/test_exit_codes.py`: the second to merge rebases on the first. The WP7 slice 2 packages add rows to the same table; whichever lands after A4 writes its rows in the new 9-column form.

**BLOCKED** in a spec marks a question only the owner can answer. The spec gives the plan's default; do not decide it yourself. Ask the caller (who asks the owner through the interactive question tool), and build only the parts the spec says are safe to build before the answer.

## Common rules for every spec

1. **Follow the agent rules** in [agent-rules.md](agent-rules.md) exactly (worktree, identity, no version bump, one PR, push command, test command, machine limits, honest report). It is the authority; this list only adds what the specs share.
2. Read `AGENTS.md` (module table, testing conventions, GUI rules) and the plan page the spec names before writing code.
3. **Branch and PR.** Branch name is given in each spec. PR title: a plain sentence of what changes. PR body: plain and specific, starts with the issue line the spec gives (for example `Refs #127` or `Refs roadmap`), says what changed, what was verified, what was not (always: nothing was opened in Tableau Desktop) and any judgement calls. No `Co-Authored-By`, `Claude-Session` or "Generated with" lines anywhere. Not a draft unless the spec says so. Never merge.
4. **Public names.** Every name added to `py_tbparse.__all__` needs a bullet `- `name`: summary` in `docs/api.md` in the same PR; `tests/test_api_doc.py` fails otherwise, and also fails for a documented name that is not public. Every public name needs a docstring (same test).
5. **New exceptions** derive from `PyTbparseError` (`tests/test_error_base.py` walks the package).
6. **A new module** gets a row in the `AGENTS.md` module table. A new file under `py_tbparse/webui/` must be added to `_ASSETS` in `webgui.py` and to the package data (`pyproject.toml` and `MANIFEST.in`).
7. **Anything that writes a workbook** passes the differential checks of `tests/schema_check.py` (`new_schema_errors(before, after) == []`) and adds a line to `scripts/make_tableau_check_pack.py` plus `docs/tableau-check.md` when it is a new kind of output.
8. **Verify like CI.** From the worktree root:

   ```bash
   free -m; uptime                                     # skip heavy work under ~1.5 GB free
   PYTHONPATH=$PWD nice -n 10 timeout 1800 /home/claude-user/ai-sandbox/py-tbparse/.venv/bin/pytest -q tests/<files you touched> 2>&1 | tail -20
   PYTHONPATH=$PWD nice -n 10 timeout 3600 /home/claude-user/ai-sandbox/py-tbparse/.venv/bin/pytest -q -m "not corpus" --ignore-glob='tests/test_gui_*.py' > /home/claude-user/.claude/jobs/b5d69d0e/tmp/<name>-suite.log 2>&1
   ```

   The second line is the whole non-browser suite (run it in the background and read the log tail). Browser tests (`tests/test_gui_*.py`) need Chromium; run them only when the spec says so, one file at a time, and say in the PR whether they ran. Corpus tests need `python scripts/fetch_corpus.py` first; say whether they ran. `tests/test_version.py` can fail in a worktree because the shared venv's editable install points at the main checkout: not a bug in the branch, say so if it happens.
9. **CI.** After pushing, wait for the PR checks (`gh pr checks <n> --watch --interval 60` with a `timeout`), and report the result. A docs-only PR gets only `files` and `ci-ok`.
10. **Report** (to the caller): PR URL, what changed, test counts, what ran and what did not, open questions. Under 300 words.

## What none of these specs can verify

Nothing py-tbparse writes has been opened in Tableau Desktop. Specs that change a writer list the rows the owner should run from `docs/tableau-check.md`; until he reports, docs and PRs say "schema-valid, not opened in Tableau". No screen reader is available on this machine; GUI specs ask the owner for a manual pass rather than claim one.
