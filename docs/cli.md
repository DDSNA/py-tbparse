# Command line

Part of [py-tbparse](https://github.com/DDSNA/py-tbparse).

```bash
py-tbparse workbook.twb                        # overview
py-tbparse workbook.twb tables                 # list the tables
py-tbparse workbook.twb calculated-fields
py-tbparse workbook.twb fields --format csv -o fields.csv
py-tbparse workbook.twbx dashboard-sheets --dashboard "Sales Overview"
py-tbparse workbook.twb validate               # exit code 2 if a relationship is broken (1 if it cannot load the workbook)
py-tbparse workbook.twb graph > model.dot      # --include-inferred adds the guessed links
py-tbparse diff old.twb new.twb datasources
py-tbparse diff-xml old.twb new.twb           # unified diff of the XML, formatting noise removed; exit 1 if different
py-tbparse batch ./workbooks datasources
py-tbparse rename new.twb --reference old.twb --only-changed   # suggested clean field names
py-tbparse rename new.twb -r old.twb --datasource federated.abc123 --write-workbook   # and save new_renamed.twb
py-tbparse rename report.twb --all --write-workbook       # sheets, dashboards, datasources, ... too
py-tbparse template make sales.twbx                        # see templates.md
py-tbparse template apply sales.template.twbx --data q3.csv --write
py-tbparse template check sales.template.twbx --fail-on warning   # lint a template; exit 1 on a finding at that level
py-tbparse template show sales.template.twbx --markdown -o SALES.md   # a documentation page for a template
py-tbparse template apply sales.template.twbx --answers sales_q3.twbx --explain --check   # repeat a run, and see what changes
```

Tables: `overview`, `datasources`, `parameters`, `fields`, `raw-fields`, `calculated-fields`, `joins`, `relations`, `relationships`, `inferred-relationships`, `dashboards`, `dashboard-sheets`, `custom-sql`, `initial-sql`, `published-refs`, `field-usage`, `missing-references`, `field-renames`, `report-renames`.

`--format` takes `table` (default), `csv` or `json`; `validate`, `audit` and `template check` also take `junit`, `sarif` and `github` for CI (see [ci.md](ci.md)). `graph` always prints Graphviz text. `rename` takes `--reference`, `--datasource`, `--write-workbook [PATH]`, `--style`, `--cutoff`, `--only-changed`, `--all`, `--kinds`, `--apply MAPPING.csv`, `--missing`, `--format` and `--output`. `diff` and `batch` accept the same table names except `graph`, `validate` and `tables`.

`py-tbparse diff-xml A B [-U N] [-o FILE]` compares the XML of two `.twb`/`.twbx` files (the workbook member of a `.twbx`) and exits 0 (no differences), 1 (differences) or 2 (unreadable file, or `-o` names an input). See [diff-xml.md](diff-xml.md) and [Exit codes](#exit-codes).

## Exit codes

This table is the one place that lists every exit code, per command. The codes are **not one scheme**: 1 and 2 mean different things in different commands (see "What the codes mean" below), so a script has to look up the command it runs. The per-command pages say the same as this table or link here. [ci.md](ci.md) has the CI view of `validate`, `audit` and `template check`.

| Command | 0 | 1 | 2 | 3 |
| --- | --- | --- | --- | --- |
| `WORKBOOK [TABLE]` (every table, `tables`, `graph`) | printed | workbook not found, or `TwbParser` raised `ValueError` | usage error (unknown table, a CI format on a table other than `validate`, bad option) | not used |
| `WORKBOOK validate` (any `--format`, also `junit`, `sarif`, `github`) | all relationships resolve | workbook not found or `ValueError` | a relationship refers to a table or field the workbook lacks (a finding, not a failure to read) | not used |
| `diff A B` | printed (also when the two differ) | a workbook not found or `ValueError` | usage error | not used |
| `diff-xml A B` | no differences | differences | a file cannot be read, or `-o` names one of the inputs, or usage error | not used |
| `batch DIR` | printed | `DIR` is not a directory | usage error | not used |
| `rename WORKBOOK` (also `--missing`, `--apply`, `--write-workbook`) | done | any error: workbook or reference unreadable, bad `--cutoff`, mapping unreadable, output refused | usage error (`--missing` without `--reference`, `--missing` with `--apply`) | not used |
| `audit WORKBOOK` | no finding at `--fail-on` (default `error`) | a finding at or above `--fail-on` | workbook cannot be read, bad `--only`/`--skip`, or usage error | a rule crashed (whatever `--fail-on` says; traceback on stderr) |
| `template check TEMPLATE` | no finding at `--fail-on` | a finding at or above `--fail-on` | template cannot be read (not a `.twbx` template, malformed manifest), bad `--only`/`--skip`, or usage error | a rule crashed |
| `template drift TEMPLATE FILES` | no finding at `--fail-on` | a finding at or above `--fail-on` | template, answers or data files cannot be read, no file matches, or usage error | a rule crashed |
| `template make`, `show`, `targets`, `target-make`, `update`, `apply` (dry run or `--write`) | done (a dry run, and `update` without `--write`, always 0) | any error (`TemplateError` and other `ValueError`, missing file, existing output, bad zip or JSON) | usage error (a malformed `--param`/`--token`/`--column`, `--output` without `--markdown`, `--table` missing) | not used |
| `template apply-folder TEMPLATE DIR` | every file written | any file skipped or failed, or an error | usage error | not used |
| `library export`, `show` | done | any error | usage error | not used |
| `library import` | done, or a dry run (also with entries that cannot be imported) | any error, including `--on-clash fail` meeting a clash | with `--write`: some entry failed or was skipped as a dependent; the others are written | not used |
| `style show`, `check` | `check`: no problem (warnings do not count) | any error; `check`: a problem found (an unreadable file counts as a problem) | usage error | not used |
| `style export`, `import` | done | any error; a dry run of `import` where a palette name clashes under `--on-clash fail` (nothing is written) | some palette was invalid; the others are written | not used |
| `scaffold make`, `show`, `apply` | done | any error | usage error | not used |
| `sanitize IN OUT` | written | not used | any error: input unreadable, `OUT` exists without `--overwrite`, unknown `--keep`, bad extension; or usage error | not used |
| `prune WORKBOOK` (dry run or `--write -o OUT`) | done | not used | any error: unreadable workbook, output refused, bad extension; or usage error | not used |
| `slice WORKBOOK` (dry run or `--write -o OUT`) | done | not used | any error: unreadable workbook, unknown dashboard, `--strict` would drop something, output refused; the result has new integrity problems (a dry run says so too); or usage error | not used |
| `sheet copy SRC --to TARGET` | done, or a dry run | any error or stop: unreadable file, clash under `--on-clash fail`, `--strict` refusal, no sheet named or found, nothing copyable | some sheet was refused; the others are copied (written with `--write`) | not used |
| `dashboard copy SRC --to TARGET` | done, or a dry run | any error or stop, as for `sheet copy` | some dashboard was refused; the others are copied | not used |
| `docs WORKBOOK`, `dictionary WORKBOOK` | written or printed | not used | workbook cannot be read, `-o` is the workbook itself, or usage error | not used |
| `python -m py_tbparse.precommit audit\|validate\|template-check FILE...` | every file gave 0 | the worst code of the files was 1 | the worst code was 2, or an unknown hook command | the worst code was 3 |

What the codes mean, across the table:

- **0** is success everywhere. It also means "not a finding" for `audit`, `template check` and `template drift` below `--fail-on`, and `--fail-on never` makes it the answer to any finding.
- **1** means three things: an error (most commands: `rename`, `library`, `style`, `scaffold`, `template` other than `check` and `drift`, `sheet copy`, `dashboard copy`, `diff`, `batch` and the plain table commands), a finding at `--fail-on` (`audit`, `template check`, `template drift`), and "the two files differ" (`diff-xml`). `template apply-folder` uses it for a run in which some file was not written.
- **2** means four things. (a) Any error at all: `sanitize`, `prune`, `slice` and `docs` have no 1. (b) Input that cannot be read or a wrong option, as opposed to a finding (`audit`, `template check`, `template drift`, `diff-xml`). (c) A finding: `validate` found a broken relationship. (d) A partial result, the rest being written (`sheet copy`, `dashboard copy`, `library import`, `style export`, `style import`). Every command also uses 2 for an argparse usage error.
- **3** is used only by `audit`, `template check` and `template drift`: a rule crashed, a bug in py-tbparse.
- A Python exception that no command catches ends the process with the traceback and exit code 1: an unwritable `-o` path, a malformed `.twb` or `.twbx` given to the plain table commands, `validate` or `diff` (they catch `FileNotFoundError` and `ValueError` only). Do not rely on it; it is not a designed code.
- `--help` exits 0. An argparse usage error (an unknown option, a missing argument, a bad choice, and the `ap.error` checks such as `-o` without `--write`) exits 2 in every command, including those whose own errors use 1.

Not verified in Tableau Desktop; the codes were read from `py_tbparse/cli.py` and the modules it calls, and the failure paths were run on the test fixtures. A scheme that makes the codes uniform is an open design question (issue #127, a minor version because it breaks scripts); until then this table describes what the commands do. `tests/test_exit_codes.py` runs one case per row and checks that the code is listed here.

## Templates

`py-tbparse template` has nine subcommands: `make`, `show`, `check`, `drift`, `targets`, `target-make`, `update`, `apply-folder` and `apply`. What a template is, mapping, answers, tokens, databases and the check rules are explained in [templates.md](templates.md). `py-tbparse template SUBCOMMAND --help` lists every option.

```bash
py-tbparse template make sales.twbx --token customer="Your company"   # --token NAME=DEFAULT; also --name, --description, --keep-data, -o
py-tbparse template show sales.template.twbx --markdown -o SALES.md   # --format table|csv|json without --markdown
py-tbparse template check sales.template.twbx --fail-on warning       # --format, --only T001,T003, --skip T008
py-tbparse template targets                                           # the database classes a target file can use
py-tbparse template target-make --class postgres --server db.example.com --dbname sales \
    --schema public --schema-file orders.sql -o orders.target.json    # or repeat --column NAME:TYPE
py-tbparse template apply sales.template.twbx --data q3.csv --mapping-out map.csv    # print the suggestion, save it to edit
py-tbparse template apply sales.template.twbx --data q3.csv --mapping map.csv -p "Top N=10" --token customer=ACME --write
py-tbparse template apply sales.template.twbx --data q3.xlsx --sheet Sales --write   # --sheet: a name or an index from 0
py-tbparse template apply sales.template.twbx --answers sales_q3.twbx --profile prod --write   # saved answers and a profile
py-tbparse template update sales.v2.template.twbx sales_q3.twbx --write              # bring a workbook up to a newer revision
py-tbparse template apply-folder sales.template.twbx customers/ -o out/ --inputs customers.csv --min-mapped 0.9
py-tbparse template drift sales.template.twbx 'data/sales_*.csv' --fail-on warning   # do the monthly files still fit? --answers, --sheet, --save-answers, --format
```

Notes from `--help`:

- `template apply` writes nothing without `--write`. `--explain`, `--xml-diff`, `--check` and `--deep` add reports about what the apply changes, the normalised XML diff of the template and the output (see [diff-xml.md](diff-xml.md); the workbook is built in a temporary folder), and the new data. `--datasource` and `--data-datasource` pick one datasource when there are several, `--cutoff` sets how close a name must be, `--allow-missing` writes even when a required field has no column, `--format` takes `table`, `csv` or `json`.
- `--experimental` (on `apply`, `update`, `apply-folder` and `target-make`) allows a connection class that was never checked against a workbook Tableau wrote; see `template targets`.
- `template update` takes `--old` (the revision the workbook was made from, when its answers do not keep it), `--data`, `--sheet`, `--mapping`, `--allow-missing` and `--token`.
- `template apply-folder` also takes `--pattern`, `--answers`, `--profile`, `--mapping`, `-p`, `--sheet`, `--on-error {skip,stop}`, `--workers` and `--overwrite`. Without `-o` the workbooks and `summary.csv` go to `DIR/out`. It exits 1 if any file was not written.
- `template drift TEMPLATE_OR_ANSWERS GLOB_OR_FOLDER` exits like `template check` (rules D001 to D011, see [templates.md](templates.md)).
- `template check` exits 0 (nothing at `--fail-on`), 1 (a finding at `--fail-on`), 2 (the template cannot be read or an option is wrong) or 3 (a rule crashed). The other subcommands exit 0, 1 for an error and 2 for a usage error; see [Exit codes](#exit-codes).
- `.xlsx` and `.xlsm` input needs `pip install "py-tbparse[excel]"`.

## Audit and data dictionary

`py-tbparse audit WORKBOOK [--format table|csv|json] [--fail-on error|warning|info|never] [--only A001,A005] [--skip A006] [-o FILE]` lints a workbook (rules A001 to A011). It exits 0, 1 (a finding at `--fail-on`, default error), 2 (unreadable workbook or bad option) or 3 (a rule crashed; [Exit codes](#exit-codes) lists the other commands). `py-tbparse docs WORKBOOK [-o page.md] [--graph]` (also `dictionary`) writes a Markdown data dictionary. Both only read the workbook; nothing was opened in Tableau. See [audit.md](audit.md).

`py-tbparse prune WORKBOOK [--write -o OUT] [--sheets] [--no-calculations] [--no-parameters] [--overwrite] [--format table|json]` removes the unused calculations and parameters the audit finds (worksheets on no dashboard only with `--sheets`), if nothing that stays refers to them. A dry run unless `--write -o OUT`, which writes a new file and never the input. It exits 0, or 2 for any error. See [prune.md](prune.md).

`py-tbparse slice WORKBOOK --dashboards A,B [--write -o OUT] [--strict] [--no-prune] [--overwrite] [--format table|json]` keeps the named dashboards and the worksheets they show, drops everything else (other dashboards and worksheets, their windows, then the calculations, parameters and datasources only they used) and reports the actions it had to drop (`--strict` refuses instead). A dry run unless `--write -o OUT`. An unknown dashboard name fails and lists the valid ones. See [slice.md](slice.md).

## Libraries

`py-tbparse library` has three subcommands: `export`, `show` and `import`. They move calculated fields and parameters between workbooks; [libraries.md](libraries.md) explains the clash handling and what is not covered. The output was never opened in Tableau: check a copy first.

```bash
py-tbparse library export sales.twb -o kpis.library.json --folder KPIs   # also --field NAME (repeatable), --datasource, --no-dependencies, --no-parameters, --name, --description, --overwrite
py-tbparse library show kpis.library.json --markdown                     # without --markdown: a table and the formulas with captions
py-tbparse library import other.twb kpis.library.json                    # the plan only
py-tbparse library import other.twb kpis.library.json --mapping map.csv --on-clash skip --write -o out.twb
```

- `import` writes nothing without `--write`. The output defaults to `<name>_library.<ext>` beside the workbook, keeps the workbook's extension, and never replaces the input (`--overwrite` replaces an existing output only).
- `--on-clash` is `fail` (default), `rename` or `skip`. The default was `rename` before; it is `fail` now so the command line and the Libraries view agree, so an old script that relied on renaming needs `--on-clash rename`. The Python functions still default to `rename` and warn when `on_clash` is not passed; their default becomes `fail` in 0.6.0 ([libraries.md](libraries.md)). `--mapping` is a CSV with `field` and `mapped_to`.
- Exit codes of `import`: 0, 1 (an error, including `--on-clash fail` meeting a clash), 2 (some entry could not be imported; the others are written). All commands: [Exit codes](#exit-codes).

## Sheet copy

`py-tbparse sheet copy SRC --sheets A,B --to TARGET [--sheet NAME] [--on-clash fail|rename|skip] [--strict] [--write [-o OUT]] [--overwrite] [--format text|json]` copies worksheets into a new copy of TARGET. A dry run unless `--write`; the output defaults to `<TARGET>_sheetcopy.<ext>` and is never an input. `--on-clash` defaults to `fail` and covers calculations, parameters and sheet names. Exit codes: 0, 1 (an error, a clash under `fail`, `--strict` with something to drop, nothing copyable), 2 (some sheet was refused; the others are written). See [sheet-copy.md](sheet-copy.md). Never opened in Tableau.

`py-tbparse dashboard copy SRC --dashboards A,B --to TARGET [--dashboard NAME] [--on-clash fail|rename|skip] [--strict] [--write [-o OUT]] [--overwrite] [--format text|json]` copies dashboards, with every sheet on them, into a new copy of TARGET (the rules of sheet copy, plus the dashboard's own datasources and dependencies, a new window and the actions internal to the copied set; other actions are dropped and listed). A dry run unless `--write`; the output defaults to `<TARGET>_dashcopy.<ext>` and is never an input. `--on-clash` defaults to `fail`; there is no overwrite policy. Exit codes: 0, 1 (an error, a clash under `fail`, `--strict` with something to drop, nothing copyable), 2 (some dashboard was refused; the others are written). See [dashboard-copy.md](dashboard-copy.md). Never opened in Tableau.

## Colour palettes

`py-tbparse style` has four subcommands: `show`, `export`, `import` and `check`. They move named colour palettes between workbooks, `Preferences.tps` files and `*.style.json` files; [styles.md](styles.md) explains the clash handling. Palettes become selectable in the colour picker; nothing is recoloured. The output was never opened in Tableau: check a copy first.

```bash
py-tbparse style show brand.twb Preferences.tps                  # also --format csv|json
py-tbparse style export brand.twb -o acme.style.json             # or acme.tps; also --palette NAME (repeatable), --on-clash, --name, --overwrite
py-tbparse style import acme.style.json Preferences.tps          # the plan only
py-tbparse style import acme.style.json Preferences.tps --on-clash replace --write
py-tbparse style check Preferences_palettes.tps
```

- `import` writes nothing without `--write`. It always writes a new file (default `<name>_palettes.<ext>` beside the target) and never replaces the input or an existing `Preferences.tps`; there is no in-place option.
- `--on-clash` is `fail` (default), `skip`, `rename` or `replace`.
- Exit codes: 0, 1 (an error, a clash under `--on-clash fail`, or problems found by `check`), 2 (some palette was invalid; the others are written). All commands: [Exit codes](#exit-codes).

## The GUI command

```bash
py-tbparse-gui workbook.twb                       # opens your browser with it loaded
py-tbparse-gui --no-browser --port 8765           # --host defaults to 127.0.0.1; --port to a free one
py-tbparse-gui --server-mode --allowed-host tbparse.example.com --trust-proxy   # behind a TLS proxy
```

`--max-sessions` (default 20) and `--session-ttl` (seconds, default 3600) belong to server mode, and each server option has a `PY_TBPARSE_*` environment variable. See [gui.md](gui.md) and [deployment.md](deployment.md).

## Dashboard scaffolds

`py-tbparse scaffold` has three subcommands: `make`, `show` and `apply`. They save the layout of one dashboard as a `*.scaffold.json` file and make a new dashboard from it in a copy of a workbook; [scaffolds.md](scaffolds.md) explains what is kept, what is dropped and listed, and the checks. The output was never opened in Tableau: check a copy first.

```bash
py-tbparse scaffold make sales.twb -d Overview -o overview.scaffold.json    # also --name, --description, --overwrite
py-tbparse scaffold show overview.scaffold.json                             # also --format csv|json
py-tbparse scaffold apply other.twb overview.scaffold.json --name Regional --sheets "Sales,Profit"   # the plan only
py-tbparse scaffold apply other.twb overview.scaffold.json --name Regional --sheet Sales --sheet Profit --write -o out.twb
```

- The source needs a single tiled root; floating layouts and storyboards are refused.
- `apply` writes nothing without `--write`. It always adds a new dashboard, writes a new file (default `<name>_scaffold.<ext>` beside the workbook) and never replaces the input. Every slot needs a sheet unless `--allow-empty` is given.
