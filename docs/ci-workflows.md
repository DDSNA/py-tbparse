# CI workflows and branch protection

Part of [py-tbparse](https://github.com/DDSNA/py-tbparse). For the CI output formats of the CLI see [ci.md](ci.md); this page is about this repository's own GitHub Actions.

## What runs when

| Event | Workflow | What runs |
|---|---|---|
| PR with code changes | `ci.yml` | `test` on ubuntu 3.9, ubuntu 3.13, windows 3.13, macOS 3.12; `gui`; `js-unit`; `docker`; `build`; `ci-ok` |
| Push to `main`, `master`, `hotfix/**` | `ci.yml` | the same jobs, with `test` on all 20 combinations (ubuntu, macOS, windows, ubuntu-arm times 3.9 to 3.13) |
| PR that changes only `*.md` or `docs/**/*.png` | `ci-docs-only.yml` | `files`, `doc-tests` (the tests that read Markdown), `ci-ok` |
| Release published | `release.yml` | CI check on the tagged commit, tag/version check, tests (ubuntu 3.12), build, publish to PyPI |
| Release published | `docker-publish.yml` | image build, smoke test, GHCR publish (does not check CI) |

A PR does not run the whole matrix, so a failure that only shows on, say, macOS 3.10 can still first appear on `main`. The PR set has one run per system to catch the common case.

## Things that are easy to get wrong

- The `gui` job sets `CI_REQUIRE_BROWSER=1`. With it, `tests/conftest.py` fails the browser tests when Playwright is missing or Chromium cannot launch. Without the variable (local runs) those tests skip, as before. Individual tests can still skip for their own reasons (for example a browser without View Transitions); `-rs` in the job prints each reason.
- `ci.yml` ignores docs-only PRs, so `ci-docs-only.yml` runs the two tests that read Markdown: `tests/test_api_doc.py` (reads `docs/api.md`) and `tests/test_exit_codes.py` (reads `docs/cli.md`). If you add a test that reads a `.md` file, add it to the `doc-tests` job.
- Keep the job names `files` and `ci-ok`. `ci-ok` exists in both `ci.yml` and `ci-docs-only.yml`; whichever workflow applies to the PR reports it.
- `release.yml` refuses to release when no push run of `ci.yml` has concluded `success` on the tagged commit. If CI is still running, wait and re-run the job. It does not change what is published.
- `docker-publish.yml` has no such check. It builds the image from the same commit, but a red CI run would not stop it.

## Branch protection to set in GitHub settings

Nothing in this repository sets these; the owner does it once in the web UI (or with a ruleset). Repository merge settings at the time of writing: squash, merge commit and rebase merges are all allowed, "delete branch on merge" is off.

1. Settings, Branches (or Rules, Rulesets), add a rule for `main`.
2. Tick **Require a pull request before merging**.
3. Tick **Require status checks to pass before merging** and add the single check **`ci-ok`**. Do not add `test`, `gui` and the others: their names change with the matrix, and `ci-ok` already depends on them. Tick "Require branches to be up to date" if you want each PR re-tested on the latest `main`.
4. Leave **Allow force pushes** and **Allow deletions** off.
5. Do **not** tick **Require linear history** while merge commits or rebase merges are allowed. Turn it on only if you first restrict the repository to squash merges (Settings, General, Pull Requests: untick merge commits and rebase merging).
6. Optionally apply the same rule to `hotfix/**`, since `ci.yml` runs there too.

Docs-only PRs must still report `ci-ok`. They do: `ci.yml` is skipped for them, and `ci-docs-only.yml` reports `ci-ok` after its `doc-tests` job. After setting the rule, open a PR that changes only a `.md` file and check that `ci-ok` appears and turns green before relying on it. A PR that mixes `.md` and code runs `ci.yml` and reports `ci-ok` from there.
