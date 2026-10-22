# Spec A10 (owner-run): the 0.6.0 release checklist

Track: 0.6.0. Plan: [plan-0.6.0-exit-codes-and-errors.md](../plan-0.6.0-exit-codes-and-errors.md) WP10 and section 4; [plan-0.6.0-clash-default.md](../plan-0.6.0-clash-default.md) "Release-note wording"; `AGENTS.md` "Versioning" and "Release rules". This is a checklist for the owner and for an agent he asks to prepare the release PR. An agent never merges, tags or publishes.

- Branch (release PR): `release-0.6.0`, changes only `pyproject.toml` (`version = "0.6.0"`).
- PR title: `Release 0.6.0`
- PR body: the release notes below, what is not verified, and how to undo.

## Before the release PR (agent may check, owner decides)

- [ ] A1 to A8 and A11 merged; A9 merged or dropped (owner's answer); the A7 dry-run commit settled.
- [ ] Owner's word on which other work rides in 0.6.0 (open question: WP7 slice 2 packages, the #84 preview packages, and everything already unreleased on `main`: cards #197, Tableau check list #201, WP7-2a #210, WP8 measurement #208, census #209, endpoint #211).
- [ ] `main` has one exit-code scheme: `docs/cli.md` has no rollout note; `tests/test_exit_codes.py::test_no_old_phrases_in_docs` passes.
- [ ] `grep -n "_resolve_on_clash\|_NOT_PASSED" py_tbparse/library.py` finds nothing (the flip is in).
- [ ] The full suite including browser tests ran on the release commit in CI (`test`, `gui`, `build`, `docker`, `js-unit`), and the corpus workflow (`corpus.yml`, on demand) ran green on that commit or the PR says it did not.
- [ ] Screenshots: `AGENTS.md` asks for `scripts/gui_screenshots.py` at every **major** release. **BLOCKED (owner):** does 0.6.0 count as major for this rule (a breaking minor while 0.x)? If yes, run it on the release commit and commit the images before the release PR.
- [ ] Packaging smoke test (`AGENTS.md` "Release / packaging"): build, `twine check`, install the wheel in a throwaway venv, `py-tbparse --help`, `py-tbparse-gui --help`, run pytest against the extracted sdist.

## Release notes (draft for the PR body and the GitHub Release)

Grouped Added / Changed / Fixed, one short entry per user-visible change, for people who run the CLI or the GUI (rules in `AGENTS.md`). The two breaking entries:

> **Changed (breaking): exit codes.** 2 now means only that the command line is wrong. Every other failure has its own code, listed once in docs/cli.md: 1 finding or difference, 3 crash, 4 bad input, 5 refused (nothing written), 6 integrity problem, 7 partial result. Commands that have no verdict (such as `rename`, `library`, `scaffold`, `sanitize`) no longer return 1. What to change in a script: `audit`, `template check`, `template drift`, `diff-xml`: an unreadable file was 2 and is now 4. `validate`: a broken relationship was 2 and is now 6; a workbook that cannot be loaded was 1 and is now 4. `sanitize`, `prune`, `slice`, `docs`: every error was 2; use 4 (input), 5 (refused), 6 (integrity). `slice` dry run predicting a refusal was 2 and is now 6. `sheet copy`, `dashboard copy`, `library import`, `style export`, `style import`: "some entries were refused, the rest is written" was 2 and is now 7; every other error was 1 and is now 4 or 5. `if [ $? -ne 0 ]` and `set -e` keep working. The pre-commit hooks still fail for the same files. Issue #127.

> **Changed (breaking for Python callers): library API `on_clash` now defaults to `fail`.** `plan_import`, `build_imported_workbook` and `import_library` used to rename a clashing calculation or parameter when you did not pass `on_clash` (and warned since 0.5.5). They now stop with a `LibraryError` on the first name clash and write nothing, as `library import`, the Libraries view, sheet copy, dashboard copy and style import already did. Pass `on_clash="rename"` (or `"skip"`) for the old behaviour. The command line and the GUI are unchanged. Issue #128.

Added (from Track A): `py_tbparse.errors` categories (`UsageError`, `InputError`, `RefusedError`, `OutputRefusedError`, `IntegrityError`), `ExitCode`, `exit_code_for`; every deliberate error derives from `PyTbparseError` and stays a `ValueError` (`OutputRefusedError` is also a `FileExistsError`). Issue #186.

Add entries for whatever else the owner puts in the release (cards view, Tableau check list, `style extract`/`style apply`, layout preview), each one line.

Not verified (say in the PR and the Release): nothing written by py-tbparse has been opened in Tableau Desktop except one template path; the Tableau check list (`docs/tableau-check.md`) results so far: fill in from #82; the Docker image is built only in CI.

How to undo: yank 0.6.0 on PyPI, delete the GHCR tag `0.6.0`, ship 0.6.1. PyPI files cannot be replaced.

## Release steps (owner)

- [ ] Merge the release PR with `--match-head-commit` after CI is green on it.
- [ ] Wait for the push CI on the release commit on `main`; all jobs green.
- [ ] `gh release create v0.6.0 --target <sha> --title v0.6.0 --notes-file <notes>`.
- [ ] Right after: `git branch hotfix/0.6.0 v0.6.0 && git push origin hotfix/0.6.0` (`AGENTS.md`).
- [ ] An agent then only reads: the `release` and `docker-publish` runs finished, PyPI shows 0.6.0, the GHCR tag exists; report anything failed, re-run nothing.
- [ ] Close #127, #128, #186 (if A9 was dropped, say so on #186), and update `docs/ROADMAP.md` ("What shipped, by version").

## Not verifiable by an agent

Publishing, PyPI trusted publishing, the GHCR image tags (the token has failed to read them before), anything in Tableau Desktop.
