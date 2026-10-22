# Spec B6: WP7-2f, the closing docs pass and the Tableau check rows of slice 2

Track: WP7 slice 2. Plan: [wp7-style-plan-slice2.md](../wp7-style-plan-slice2.md) section 8 "WP7-2f" and section 9. Common rules: [README.md](README.md#common-rules-for-every-spec) (follow the agent rules file).

- Branch: `docs/wp7-slice2-2f`
- PR title: `Docs for WP7 slice 2: one Formatting guide, status lines, the Tableau check rows (WP7-2f)`
- PR body starts with: `Refs roadmap card: Templates style templates slice 2 (WP7-2f)`
- Depends on: B3 (2c), B4 (2d) and B5 (2e) merged. Last package of slice 2.

The plan says 2f is done "with each package"; 2b to 2e each update their own docs. This package is the pass over the whole that makes the pages read as one and closes the slice. It is mostly `.md`, but `scripts/make_tableau_check_pack.py` and its test may change, so CI runs fully if they do.

## Checklist

Read each page whole on `main` and fix what slice 2 left inconsistent. Do not restate the plan; describe what is built.

- [ ] `docs/styles.md`: one "Formatting" section (from #213 and later), ordered: what it does and does not do ("adds or changes formats; recolours no marks"), the style file v2 sections (link to the plan for the format), `style extract`, `style apply` (scopes, `--dashboard`, `--sheet`, `--on-clash skip|fail`, `--force`, the explicit rule and the boilerplate line), the GUI card, the exit codes (link to `docs/cli.md`), "not opened in Tableau" with the list of pack rows.
- [ ] `docs/cli.md`: `style extract`, `style show --what`, `style apply`, `style check` entries and the exit-code rows match the code (run each `--help` and compare).
- [ ] `docs/api.md`: every public name slice 2 added has a bullet (the test enforces it); the bullets say what each does in one line.
- [ ] `docs/gui.md` and the README user's guide "Styles": the Formatting card.
- [ ] `README.md`: the Guides link to `docs/styles.md` mentions formatting; "Limits" says formatting is schema-checked and not opened in Tableau.
- [ ] `docs/verify-in-tableau.md`: a "Formatting (WP7 slice 2)" section with the unverified assumptions of plan section 10 (the nine items), each marked "not checked" until the owner reports.
- [ ] `docs/tableau-check.md` and `scripts/make_tableau_check_pack.py`: rows 42 (fonts, from #213), 43 (dashboard defaults, 2c), 44 (keep vs `--force`, #213), 45 (sheet fonts, 2d) all exist, each with the exact command in `commands.txt`; `tests/test_tableau_check_pack.py` lists the files. Add any that a package forgot.
- [ ] `docs/wp7-style-plan-slice2.md`: the status row in section 1 ("2a built, 2b onwards not started") -> "2a to 2e built (PRs ...); slice 3 waits for Tableau checks 42 to 44". Answered questions in section 11 get the answer and date (Q1 and Q3 answered 2026-10-16 "build all"; Q2, Q4 with the owner's answers if given, else "open").
- [ ] `docs/wp7-style-plan.md`: the slice table row 2 -> built; section 7 "Deferred" item 2 -> "built as slice 2".
- [ ] `docs/template-roadmap-plan.md`: the WP7 line of the status box.
- [ ] `docs/ROADMAP.md`: Track B rows B3 to B6 -> built (unreleased), B8 (slice 3) still blocked on the Tableau checks.
- [ ] `AGENTS.md` `style.py` row: one coherent description of slice 1 and slice 2 (2a to 2e), the whitelist table, "zone roles from `dashboards.zone_kind`", "device layouts, pane styles, title runs and `field=` formats never touched", and the note that the format half should move to `styleformat.py` (a refactor PR, not part of this one).
- [ ] The GitHub project card "Templates: style templates slice 2 (fonts, formatting)": the owner moves it; say in the PR that it can go to Done once this merges.

## How to verify

```bash
PYTHONPATH=$PWD /home/claude-user/ai-sandbox/py-tbparse/.venv/bin/pytest -q tests/test_api_doc.py tests/test_tableau_check_pack.py tests/test_exit_codes.py
for a in show extract apply check; do PYTHONPATH=$PWD /home/claude-user/ai-sandbox/py-tbparse/.venv/bin/python -m py_tbparse.cli style $a --help; done
PYTHONPATH=$PWD /home/claude-user/ai-sandbox/py-tbparse/.venv/bin/python scripts/make_tableau_check_pack.py /home/claude-user/.claude/jobs/b5d69d0e/tmp/pack-2f && ls /home/claude-user/.claude/jobs/b5d69d0e/tmp/pack-2f
```

Check every link you add (relative links inside `docs/`, absolute `https://github.com/DDSNA/py-tbparse/blob/main/...` links in the README, as `AGENTS.md` requires for PyPI).

## Not verifiable without Tableau Desktop

Everything in the "Formatting" section of `verify-in-tableau.md`. The owner runs rows 42 to 45.

## Definition of done

Every box ticked or explained in the PR, tests above green, CI green, no version bump.
