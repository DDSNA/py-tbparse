# Sanitize: a share-safe copy

Part of [py-tbparse](https://github.com/DDSNA/py-tbparse).

`sanitize` writes a copy of a workbook that is safer to post in a forum or send to a vendor. It is a clean-up, not a guarantee: it reads the XML of the `.twb`/`.twbx`, takes out what it recognises and lists what it could not judge. Read the report and open the result before you share it. Nothing here was opened in Tableau.

```bash
py-tbparse sanitize sales.twb sales.shared.twb --report
py-tbparse sanitize sales.twbx shared.twbx --placeholders --keep comments
py-tbparse sanitize sales.twb demo.twbx --fake-data --seed 3
```

The input is never written, and an existing output is refused unless `--overwrite` (the input itself is refused even then). The output has the input's format: `.twb` in, `.twb` out; `.twbx` in, `.twbx` out; `--fake-data` always writes a `.twbx`. Running it on its own output changes nothing and reports zero removals. Exit code 0 on success, 2 for any error (the workbook cannot be read, the output exists or has the wrong extension, an unknown `--keep`, a wrong option); there is no 1. Every command's codes: [cli.md](cli.md#exit-codes).

From Python: `sanitize(path, out, keep=(), placeholders=False, fake_data=False, seed=0, fake_rows=20, overwrite=False, report=None)`; `report` is a dict that is filled in, and `format_report(report)` prints it.

## What it removes

| Category | What |
| --- | --- |
| `usernames`, `passwords` | `username` and `password` of every connection |
| `servers` | `server`, `port`, `warehouse`, `service`, `tenant`, `odbc-connect-string-extras`, and the `xml:base` of the workbook (the server it was published to) |
| `databases`, `schemas` | `dbname`, `schema`, and the same names in the qualifier of a relation's `table` (`[acme_dw].[orders]` becomes `[schema].[orders]`) |
| `paths` | an absolute `directory`; the folder part of a `filename` (the file name stays) |
| `custom_sql` | custom SQL (replaced by `SELECT 1`), `<initial-sql>`, `one-time-sql`. The report says where, never the text |
| `extracts` | extract definitions, `.hyper` and `.tde` files in a `.twbx` |
| `packaged_data` | the other data files in a `.twbx` (CSV, Excel, ...) |
| `comments` | XML comments, annotations, field descriptions |
| `user_filters`, `user_specific` | user filters; author ids and the user of a group filter |
| `repository` | the `<repository-location>` of a published workbook or data source |
| `thumbnails` | the `<thumbnails>` block and `Thumbnails/` in a `.twbx` |
| `captions` | a datasource or connection caption that contained a removed value (often the server name) |

Blanks are the default; `--placeholders` writes `server.example.com`, `database`, `schema` and `user` instead. `--keep CATEGORY` (repeatable) leaves a category alone.

## Leftovers

The report ends with what it could not judge, each with where it is (never the value):

- a removed value (a user, server or database name) that still appears elsewhere: in a calculation, a title, a relation or object-model `name`, an object id;
- a calculation that calls `USERNAME()`, `FULLNAME()`, `USERDOMAIN()`, `ISMEMBEROF()` or `USER()` (kept, not rewritten);
- an e-mail address, a web address or an absolute path in some other text;
- a connection attribute it does not know (kept);
- table names (kept, because worksheets and the object model refer to them);
- the other files in a `.twbx` (images, shapes, embedded `.tds`), kept and not opened;
- titles, captions, field names, formulas and text boxes, which it does not read for personal or company information.

## Fake data (optional, experimental)

`--fake-data` replaces the connection of each simple datasource with one to a small generated CSV (`Data/synthetic/<name>_<n>_synthetic.csv` in the `.twbx`; `--rows`, default 20; seeded, so the same run gives the same file). The columns and types come from the datasource's recorded fields; the values are made up (strings `Name 1`..`Name 7`, numbers, dates in 2024), never taken from the real data. The connection is written by the same code as `template apply`. Datasources with joins, unions or relationships, a published source, or no recorded fields are skipped and listed in the report. Not opened in Tableau.

## What was checked

Over the 200-workbook corpus: no workbook raised, every output re-parses, a second run is byte-identical and counts zero, and no server, password or user name from a connection survives in the output text (a user name that is also the connection class, such as `postgres`, stays as the class). `--fake-data` over the same files gives output that parses and has no more validation findings than the input. Not checked: that Tableau opens any output; that nothing identifying remains in free text.
