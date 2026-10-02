# Example-workbook corpus

200 real Tableau workbooks (`.twb`) from 131 public GitHub repositories whose licence lets anyone
use and redistribute them: 152 MIT, 46 Apache-2.0, 1 ISC, 1 CC0. They are for integration tests and
examples: real files from many Tableau versions and authors, including workbooks with joins,
dashboards, parameters, calculations and non-Latin field names.

- `manifest.csv`: one row per file: the repository, path in that repository, licence, the blob
  `sha` it was taken from, size and SHA-256.
- `licenses/`: each source repository's licence text, kept because MIT and Apache ask for the
  notice to travel with any copy.
- `files/`: the workbooks themselves. **Not in git** (about 26 MB). Fetch them with

  ```bash
  python scripts/fetch_corpus.py
  ```

  which downloads exactly the pinned blobs and checks every one against the manifest.
  `tests/test_corpus.py` runs every feature over them and skips when they are absent.

How the files were chosen: GitHub code search for `.twb` / `.twbx` files, kept only when the
repository declares one of MIT, Apache-2.0, BSD, ISC, Unlicense, CC0, 0BSD, Zlib, BSL-1.0 or WTFPL,
is not a fork, and the file parses as a workbook, is under 1.5 MB, is not a duplicate, with at
most 6 files per repository.

A repository's licence covers what its author could license. A workbook may in turn contain
sample data or content that someone else owns (for example a copy of a Tableau sample). Treat the
corpus as test material; if you spot something that should not be redistributed, tell us and the
row will be removed.
