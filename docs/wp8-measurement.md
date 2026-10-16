# WP8 stretch: how much does each writer rewrite? (measurement)

Part of [py-tbparse](https://github.com/DDSNA/py-tbparse). Roadmap card: Writer byte-preserving output.

The WP8 stretch in [template-roadmap-plan.md](template-roadmap-plan.md) is text-level patching of the original XML,
and says to measure first how many lines differ. This page is that measurement only. It proposes no design.

## What was measured

`scripts/measure_writer_diffs.py` runs each writer that rewrites a workbook on every `.twb` of the corpus
(200 files, not in git) and on the 12 committed demo and fixture workbooks, with inputs made from the workbook itself.
For each output it compares the workbook XML with the input:

- **Raw lines / raw bytes**: added plus removed lines of a plain line diff, and the bytes of those lines. This is what a
  reviewer sees in `git diff`.
- **Normalised lines**: `diff-xml` ([diff-xml.md](diff-xml.md)) line count, the real edit with formatting ignored.
- **Zero unrelated churn**: the share of files where raw lines minus normalised lines is 0. This is a rough proxy: the
  two counts use different line units (the canonical form puts each element open and close on its own line), so
  read it as "the output differs from the input by no more than the edit", not as an exact count.

How each writer was fed (all automatic, no hand-made files):

| Writer | Input made from the workbook |
|---|---|
| roundtrip | `build_renamed_workbook` with an empty table (a save with no edit; the baseline) |
| rename | the suggested field renames; if none, the first field renamed once |
| sanitize | default settings |
| slice | the first dashboard (no dashboard: not applicable) |
| prune | default settings (unused calculations and parameters) |
| sheet-copy, dashboard-copy | the first sheet or dashboard copied into the same workbook with `on_clash="rename"` |
| scaffold | scaffold of the first dashboard applied to the same workbook |
| style-import | one synthetic palette |
| library-import | the workbook's own library with each formula wrapped in parentheses, imported with `on_clash="rename"` |
| template-apply | a template made from the workbook, applied to a synthetic one-row CSV with a column per field |
| template-update | the same template as a new revision, applied over the workbook from the previous step |

## Results

Corpus, 200 workbooks. "Ran" is the number of files the writer produced an output for; "N/A" means the workbook had
nothing to act on (no dashboard, no calculation, nothing renamed); "Failed" counts files where the writer raised.
Cells are median / p90 / max.

| Writer | Ran | N/A | Failed | Raw lines | Raw bytes | Normalised lines | Zero unrelated churn |
|---|---|---|---|---|---|---|---|
| roundtrip (no edit) | 200 | 0 | 0 | 830 / 3,206 / 7,570 | 57,593 / 226,886 / 430,284 | 0 / 0 / 0 | 0% |
| rename | 156 | 44 | 0 | 972 / 3,282 / 7,134 | 64,902 / 240,430 / 430,393 | 6 / 28 / 278 | 0% |
| sanitize | 200 | 0 | 0 | 1,650 / 4,829 / 9,111 | 114,517 / 343,907 / 517,048 | 664 / 2,144 / 3,625 | 0% |
| slice | 107 | 92 | 1 | 1,554 / 3,879 / 7,570 | 109,980 / 277,214 / 429,174 | 0 / 1,398 / 3,324 | 0% |
| prune | 200 | 0 | 0 | 828 / 3,198 / 7,570 | 57,323 / 226,886 / 429,174 | 0 / 12 / 28 | 0% |
| sheet-copy | 156 | 44 | 0 | 1,067 / 3,362 / 7,679 | 70,168 / 226,215 / 445,636 | 96 / 172 / 406 | 0% |
| dashboard-copy | 76 | 124 | 0 | 1,843 / 4,822 / 8,109 | 118,977 / 298,876 / 470,228 | 464 / 1,129 / 2,099 | 0% |
| scaffold | 0 | 92 | 108 | - | - | - | - |
| style-import | 200 | 0 | 0 | 836 / 3,212 / 7,576 | 57,803 / 227,096 / 430,494 | 6 / 6 / 8 | 0% |
| library-import | 85 | 115 | 0 | 1,256 / 4,678 / 7,134 | 85,824 / 302,807 / 431,336 | 6 / 17 / 78 | 0% |
| template-apply | 180 | 0 | 20 | 906 / 3,318 / 7,810 | 66,900 / 237,394 / 460,111 | 266 / 827 / 2,530 | 1% |
| template-update | 180 | 0 | 20 | 906 / 3,318 / 7,810 | 66,900 / 237,394 / 460,111 | 266 / 827 / 2,530 | 1% |

The 12 committed workbooks give the same picture on a smaller scale (a no-edit save: median 205 raw lines, 0
normalised; one of 12 saves with no raw difference at all). Their full table is printed by the script.

Failures: scaffold raised `ScaffoldError` on 108 workbooks (a dashboard layout it does not support, which is the
documented behaviour), template apply and update raised `TemplateError` on 20, slice `SliceError` on 1. No writer
timed out and none ran out of memory. Those files are left out of the rows above, so the rows describe the workbooks
each writer can handle.

Run on 2026-10-16: 255 s for all 212 workbooks and 12 writers, one process, `nice -n 10`, `ionice -c3`. Peak memory
of the process 100 MB; 1-minute load 0.35 at the start, peak 2.08 during the run; 6.6 GB free before. No file was over
20 MB, so none was skipped.

## What the numbers say

1. Most of what a reviewer sees is not the edit. A save with no edit already changes a median of 830 lines (p90
   3,206, max 7,570) and no workbook of 200 comes out line-identical, yet `diff-xml` finds 0 differences in all 200.
   The writer changes formatting only, and it does so on every file.
2. For writers whose real edit is small, the edit is a tiny share of the diff. Rename (median 6 normalised lines
   against 972 raw), style import (6 against 836), library import (6 against 1,256) and prune (0 against 828) would
   shrink by two orders of magnitude if the output kept the input's formatting.
3. For writers whose real edit is large (sanitize, slice, dashboard copy, template apply and update), text patching
   would still remove the formatting part, but the edit itself dominates: the gap is smaller in relative terms and
   still in the hundreds of lines.
4. Nothing here shows that a writer changes content it should not. That was already the finding of
   [diff-xml.md](diff-xml.md).

## Recommendation

Text-level patching is worth doing, first for the small-edit writers: rename, style import, library import and
prune (and the connection swap and parameter values of template apply). That is where an edit of a handful of lines
is buried in around a thousand lines of churn, and where the reviewability argument of the roadmap (the PBIP lesson)
is strongest. For sanitize, slice and the copy writers, the gain is real but smaller, and they are the ones with the
most structural edits, so patching them is the costly part. A cheaper first step that falls short of full
byte-preservation, such as keeping the input's attribute order and quote style when re-serialising, is not measured
here and is not recommended or ruled out by these numbers.

How sure: fairly sure (about 80%) of the size of the churn, because it is measured on 200 real workbooks and
reproducible. Much less sure (about 50%) that it is worth the work, because the number says nothing about how often
anyone diffs a py-tbparse output in a pull request or in git, and about what it costs: the risk is a patcher that
produces XML which no longer matches the tree the rest of the code reasons about. Treat the recommendation as
"worth a design spike on the small-edit writers", not "build it".

## What was NOT measured

- Whether Tableau opens any output, or whether it treats a byte-preserved file differently. Nothing here was checked
  in Tableau Desktop. Tableau rewrites the whole file when it saves, so a file passed back and forth through Tableau
  gets reformatted anyway; how much of the churn that already causes was not measured.
- What the churn consists of (quote style, attribute order, entity escapes, line endings, indentation). The causes
  were not broken down, so how much a cheaper fix would remove is unknown.
- `.twbx` workbooks of the corpus (it holds `.twb` files only) beyond the few in the fixtures; the archive members
  other than the workbook; and the Tableau Prep or `.tds` writers.
- Workbooks over 20 MB, none of which exist in the corpus.
- Writers fed with realistic user input: a hand-edited rename table, a real Excel or database target for template
  apply, a library exported from a different workbook, a sheet copy between two different workbooks. Copies went into
  the same workbook, and template data was a synthetic CSV, so the connection swap edit is representative but the
  mapping work is not.
- The unrelated-churn share is a proxy (see above), not a line-exact figure; the two line units differ.
- The cost, risk and complexity of a patcher, and how many writers could share it.
- The 108 corpus workbooks scaffold rejects, the 20 that template apply rejects, and the 1 that slice rejects.

## Re-running

The corpus is not in git: `python scripts/fetch_corpus.py` downloads it first. The script uses one process and
no new dependency. The way it was run for the table above:

```bash
PYTHONPATH=. nice -n 10 ionice -c3 timeout 5400 .venv/bin/python scripts/measure_writer_diffs.py \
    --json measure.json > measure.log 2>&1
```

Options: `--max-files N` caps the corpus (and fixture) files, `--writers rename,prune` picks writers,
`--timeout S` is the limit per writer per file (default 60), `--mem-limit-mb` caps the address space (default 3000),
`--files A.twb B.twbx` measures only those files, `--no-fixtures`, `--corpus-dir`, `--workdir`. It pauses while the
1-minute load is above 3.5 or less than 1.5 GB of memory is available, skips files over 20 MB, stops on a low disk
(under 500 MB free), and stops after the current file when the stop file exists
(`touch /tmp/measure_writer_diffs.stop` on Linux, or set `MEASURE_STOP_FILE`). It prints aggregates only, never file names or
content, and removes its scratch folders. The test is `tests/test_measure_writer_diffs.py`.
