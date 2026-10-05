# Command line

Part of [py-tbparse](https://github.com/DDSNA/py-tbparse).

```bash
py-tbparse workbook.twb                        # overview
py-tbparse workbook.twb tables                 # list the tables
py-tbparse workbook.twb calculated-fields
py-tbparse workbook.twb fields --format csv -o fields.csv
py-tbparse workbook.twbx dashboard-sheets --dashboard "Sales Overview"
py-tbparse workbook.twb validate               # exit code 2 if it finds a problem
py-tbparse workbook.twb graph > model.dot      # --include-inferred adds the guessed links
py-tbparse diff old.twb new.twb datasources
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

`--format` takes `table` (default), `csv` or `json`. `graph` always prints Graphviz text. `rename` takes `--reference`, `--datasource`, `--write-workbook [PATH]`, `--style`, `--cutoff`, `--only-changed`, `--all`, `--kinds`, `--apply MAPPING.csv`, `--missing`, `--format` and `--output`. `diff` and `batch` accept the same table names except `graph`, `validate` and `tables`.

## Templates

`py-tbparse template` has eight subcommands: `make`, `show`, `check`, `targets`, `target-make`, `update`, `apply-folder` and `apply`. What a template is, mapping, answers, tokens, databases and the check rules are explained in [templates.md](templates.md). `py-tbparse template SUBCOMMAND --help` lists every option.

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
```

Notes from `--help`:

- `template apply` writes nothing without `--write`. `--explain`, `--check` and `--deep` add reports about what the apply changes and about the new data. `--datasource` and `--data-datasource` pick one datasource when there are several, `--cutoff` sets how close a name must be, `--allow-missing` writes even when a required field has no column, `--format` takes `table`, `csv` or `json`.
- `--experimental` (on `apply`, `update`, `apply-folder` and `target-make`) allows a connection class that was never checked against a workbook Tableau wrote; see `template targets`.
- `template update` takes `--old` (the revision the workbook was made from, when its answers do not keep it), `--data`, `--sheet`, `--mapping`, `--allow-missing` and `--token`.
- `template apply-folder` also takes `--pattern`, `--answers`, `--profile`, `--mapping`, `-p`, `--sheet`, `--on-error {skip,stop}`, `--workers` and `--overwrite`. Without `-o` the workbooks and `summary.csv` go to `DIR/out`. It exits 1 if any file was not written.
- `template check` exits 0 (nothing at `--fail-on`), 1 (a finding at `--fail-on`), 2 (the template cannot be read or an option is wrong) or 3 (a rule crashed).
- `.xlsx` and `.xlsm` input needs `pip install "py-tbparse[excel]"`.

## Libraries

`py-tbparse library` has three subcommands: `export`, `show` and `import`. They move calculated fields and parameters between workbooks; [libraries.md](libraries.md) explains the clash handling and what is not covered. The output was never opened in Tableau: check a copy first.

```bash
py-tbparse library export sales.twb -o kpis.library.json --folder KPIs   # also --field NAME (repeatable), --datasource, --no-dependencies, --no-parameters, --name, --description, --overwrite
py-tbparse library show kpis.library.json --markdown                     # without --markdown: a table and the formulas with captions
py-tbparse library import other.twb kpis.library.json                    # the plan only
py-tbparse library import other.twb kpis.library.json --mapping map.csv --on-clash skip --write -o out.twb
```

- `import` writes nothing without `--write`. The output defaults to `<name>_library.<ext>` beside the workbook, keeps the workbook's extension, and never replaces the input (`--overwrite` replaces an existing output only).
- `--on-clash` is `rename` (default), `skip` or `fail`. `--mapping` is a CSV with `field` and `mapped_to`.
- Exit codes of `import`: 0, 1 (an error, including `--on-clash fail` meeting a clash), 2 (some entry could not be imported; the others are written).

## The GUI command

```bash
py-tbparse-gui workbook.twb                       # opens your browser with it loaded
py-tbparse-gui --no-browser --port 8765           # --host defaults to 127.0.0.1; --port to a free one
py-tbparse-gui --server-mode --allowed-host tbparse.example.com --trust-proxy   # behind a TLS proxy
```

`--max-sessions` (default 20) and `--session-ttl` (seconds, default 3600) belong to server mode, and each server option has a `PY_TBPARSE_*` environment variable. See [gui.md](gui.md) and [deployment.md](deployment.md).
