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
