# Development and tests

Part of [py-tbparse](https://github.com/DDSNA/py-tbparse).

```bash
pip install -e ".[test]"
pytest
```

The sample workbooks in `tests/fixtures/` come from the R package. `tests/fixtures/public/` holds real workbooks from Tableau's own [document-api-python](https://github.com/tableau/document-api-python) (MIT), used by the smoke tests.

`tests/corpus/` lists 200 more real workbooks from public repositories with MIT, Apache-2.0, ISC or CC0 licences, for integration tests and as examples (manifest, licence texts and where each file came from are in its README). The files themselves are not in git (about 26 MB): run `python scripts/fetch_corpus.py` to download them, checked against the manifest. `tests/test_corpus.py` then runs every feature over all of them; it skips when they are not fetched.

The GUI tests run the page in headless Chromium through Playwright and fail on any JavaScript error. They skip if the browser isn't installed. To run them:

```bash
pip install -e ".[test,browser]"
playwright install chromium         # add --with-deps if you have root
./scripts/setup-browser-libs.sh     # without root, this unpacks the system libraries locally
pytest tests/test_gui_browser.py
```

## Blocking pushes to main

`scripts/git-hooks/pre-push` refuses any push whose remote ref is `refs/heads/main` or `refs/heads/master`, which also covers force pushes and deletions of those branches. Pushes to other branches go through. It is not enabled by default; to turn it on in a clone, either point git at the folder:

```bash
git config core.hooksPath scripts/git-hooks
```

or copy it: `cp scripts/git-hooks/pre-push .git/hooks/pre-push` (in a linked worktree, use the `hooks` folder of the main `.git`). `git push --no-verify` skips it, so it stops mistakes, not a determined push. Branch protection on `main` in the GitHub repository settings is the stronger option, because the server enforces it; that setting belongs to the repository owner.
