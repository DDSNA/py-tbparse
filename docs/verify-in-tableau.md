# Checking py-tbparse output in Tableau

Part of [py-tbparse](https://github.com/DDSNA/py-tbparse).

Everything py-tbparse writes (renamed workbooks, templates, templates applied to new data) is checked by tests
against two things, and **never against Tableau itself**:

| Layer | What it proves | Where |
|---|---|---|
| Tableau's schema (the published `twb` XSD, 2026.2) | The structure is one Tableau's own schema allows. It says nothing about whether Tableau opens the file. Real workbooks are older than the schema and already fail it, so only errors the output has and its input did not are counted. | `tests/schema_check.py`, `tests/test_schema.py` |
| Reference checks (`py_tbparse.verify.validate_workbook`) | No worksheet uses a field its datasource lacks, no dashboard or window names a sheet that is gone, no text-file column points at a column the file does not list, types and Tableau's remote-type codes agree. | `py_tbparse/verify.py`, `tests/test_verify.py` |
| **Opening it in Tableau** | Everything else. This page. | you |

Both automated layers run over every workbook in the 200-workbook corpus (`python scripts/fetch_corpus.py`).
They found three real defects so far, all fixed: a template applied to a CSV dropped the object model of
workbooks that write it in the newer, unprefixed form; it gave the table column a new id the worksheets did not
use; and it could put the table column ahead of `<aliases>`. Opening the first pack in Tableau found a fourth that
neither check could see at the time: a worksheet summing `[Number of Records]` errored, because the template left out the
data column of that name and the built-in had no formula; apply now gives it the formula `1`, and
`validate_workbook` reports a `built-in-count` finding for the same state.

## Status

Done once, by the owner, with the default pack (`tests/fixtures/public/filtering.twb`): file 0 and file 1 asked for the
SQL Server connection (expected); files 2 and 3 opened without a prompt and drew both worksheets on the dashboard. Treated
as verified for the template path of that workbook shape (prefixed object model, one CSV table). Not yet looked at:
the plain object-model form, templates over several tables, and the renamed captions of file 1 with its data reachable.

## Make the files

On the machine that has Tableau Desktop (the CSV connection stores the CSV's absolute path):

```bash
python scripts/make_verification_pack.py ~/tbparse-pack            # from tests/fixtures/public/filtering.twb
python scripts/make_verification_pack.py ~/tbparse-pack2 --workbook my.twbx   # or any workbook Tableau wrote
```

It refuses a folder that is not empty and prints the schema and reference result for each file.

| File | What it is |
|---|---|
| `0-original.twb` | The workbook as it was. The baseline: if this does not open, the rest says nothing. The default one reads a SQL Server database that does not exist for you, so Tableau asks for a server connection; the workbook itself should still open and list its sheets, and its sheets cannot draw. |
| `1-renamed.twb` | Every rename py-tbparse suggests, applied (field and dashboard captions). Renaming does not touch the connection, so it asks for the same server as file 0. |
| `2-template-on-csv.twbx` | A template made from the original, applied to `data/*-sample.csv` (made-up values, every column the template needs). |
| `3-template-on-workbook.twbx` | The same template applied to file 2, so the connection is borrowed from a workbook instead of written from a CSV. |
| `4-template-on-excel.twbx` | The same template applied to `data/*-sample.xlsx` (the CSV's rows in one sheet called `Data`, with real Excel dates and booleans); only made when `openpyxl` is installed. Not yet opened in Tableau: check that it opens without a prompt, that the sheets draw, and that date fields are dates. |

## What to look at

For each of 1, 2 and 3, in this order. Stop at the first thing that is wrong and keep the message word for word.

1. **Does it open?** No error dialog, no "repair" or "unsupported feature" message. A server-connection prompt on
   files 0 and 1 is expected; on files 2 and 3 it is not (they read the CSV and contain no server).
2. **The data pane.** The datasource is listed with the name you expect. Fields have the captions the rename
   gave (file 1) and the types the template says (files 2 and 3: a date column shows the calendar icon,
   numbers the `#` icon). Look for a red `!` beside any field: that is a field Tableau cannot find.
3. **The sheets.** Each worksheet draws. In files 2 and 3 it should show the sample values. A sheet that shows
   "unknown field" or is blank is a reference that did not survive. Check the Number of Records measure too:
   worksheets name it through the table column, which is the part this package once got wrong.
4. **The dashboard.** Opens and shows its sheets; in file 1 its tab has the new name and its filters and actions
   still work.
5. **Data > the datasource > Edit Data Source.** For 2 and 3 you should see one table, the CSV, with its columns;
   *Refresh* works. For 1 nothing about the connection has changed.
6. **Save and reopen.** Save the workbook from Tableau, close, reopen. If Tableau writes warnings at save time
   (repairs, dropped items), note them.

## Reporting back

For each file, one line: `opens / opens with a message / does not open`, then what you saw. A screenshot of
any dialog helps most. The roadmap's backlog item "Verify generated workbooks open in Tableau" stays open until
this has been done; the automated checks above do not close it.

Tableau Cloud 2026.2 and Server also offer a *Validate Workbook* REST call (syntactic and semantic); it needs a
site and credentials, so it is not part of the tests.
