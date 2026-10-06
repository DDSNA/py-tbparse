"""Command-line interface: `py-tbparse WORKBOOK [TABLE] [options]`.

Three reserved subcommands, dispatched on the first argument before the
normal single-workbook parser runs: `py-tbparse diff A.twb B.twb [TABLE]`,
`py-tbparse batch DIR [TABLE]` and `py-tbparse rename WORKBOOK [-r OLD.twb]`, plus the two-level
`py-tbparse template ...`, `py-tbparse library ...` (calculated fields and parameters),
`py-tbparse style ...` (colour palettes), and the workbook `py-tbparse audit WORKBOOK` (findings) and
`py-tbparse docs WORKBOOK` (a Markdown data dictionary; `dictionary` is the same command).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import warnings
import zipfile
from pathlib import Path

import pandas as pd
from lxml import etree

from ._tables import TABLE_NAMES, TABLE_SPECS
from .batch import scan_folder
from .diff import diff_workbooks
from .library import (
    CLASH_POLICIES,
    export_library,
    import_library,
    library_table,
    load_library,
    plan_import,
    save_library,
)
from .parser import TwbParser
from . import style as _style
from .templates import (
    apply_template,
    broken_sheets,
    check_data,
    explain,
    load_answers,
    load_mapping,
    load_template,
    make_template,
    resolve_apply,
)
from .template_batch import DEFAULT_PATTERNS as DEFAULT_BATCH_PATTERNS, apply_template_folder
from .template_update import template_update_report, update_from_answers
from .workbook_audit import audit, rules_help as audit_rules_help
from .docgen import template_markdown, workbook_markdown
from .findings import exceeds, format_findings, summary as findings_summary
from .template_check import check_template, rules_help
from .templates import TemplateError, _token_values
from .rename import (
    STYLES,
    apply_field_renames,
    compare_field_schemas,
    KINDS,
    load_rename_mapping,
    suggest_field_renames,
    suggest_renames,
)


def _df_text(df: pd.DataFrame, fmt: str) -> str:
    if fmt == "csv":
        return df.to_csv(index=False)
    if fmt == "json":
        return df.to_json(orient="records", indent=2)
    if df.empty:
        return "(empty)"
    with pd.option_context(
        "display.max_rows", None, "display.max_columns", None, "display.width", 200
    ):
        return df.to_string(index=False)


def _write(text: str, output: str | None, stream=None) -> None:
    if output:
        Path(output).write_text(text, encoding="utf-8")
    else:
        print(text, file=stream)


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="py-tbparse",
        description="Parse a Tableau .twb/.twbx workbook and print one of its tables. "
        "See also: 'py-tbparse diff A.twb B.twb [TABLE]' and 'py-tbparse batch DIR [TABLE]'.",
    )
    ap.add_argument("workbook", help="path to a .twb or .twbx file")
    ap.add_argument(
        "table",
        nargs="?",
        default="overview",
        choices=[*TABLE_NAMES, "validate", "tables", "graph"],
        help="which table to print (default: overview); 'tables' lists options; "
        "'validate' checks relationships; 'graph' prints a Graphviz DOT digraph "
        "of joins/relationships",
    )
    ap.add_argument(
        "--format", "-f", choices=["table", "csv", "json"], default="table",
        help="output format (default: table)",
    )
    ap.add_argument("--output", "-o", help="write to this file instead of stdout")
    ap.add_argument(
        "--dashboard", help="restrict 'dashboard-sheets' to one dashboard by name"
    )
    ap.add_argument(
        "--include-parameters", action="store_true",
        help="include the 'Parameters' datasource in 'calculated-fields'",
    )
    ap.add_argument(
        "--include-inferred", action="store_true",
        help="for 'graph': also include dashed edges from inferred_relationships",
    )
    return ap


def build_diff_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="py-tbparse diff",
        description="Diff one table between two workbooks (row-level added/removed).",
    )
    ap.add_argument("workbook_a", help="the 'before' .twb/.twbx file")
    ap.add_argument("workbook_b", help="the 'after' .twb/.twbx file")
    ap.add_argument("table", nargs="?", default="datasources", choices=TABLE_NAMES)
    ap.add_argument("--format", "-f", choices=["table", "csv", "json"], default="table")
    ap.add_argument("--output", "-o", help="write to this file instead of stdout")
    ap.add_argument("--dashboard", help="restrict 'dashboard-sheets' to one dashboard by name")
    ap.add_argument(
        "--include-parameters", action="store_true",
        help="include the 'Parameters' datasource in 'calculated-fields'",
    )
    return ap


def _run_diff(argv: list[str]) -> int:
    args = build_diff_arg_parser().parse_args(argv)
    try:
        a = TwbParser(args.workbook_a)
        b = TwbParser(args.workbook_b)
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    df = diff_workbooks(
        a, b, table=args.table, dashboard=args.dashboard, include_parameters=args.include_parameters
    )
    _write(_df_text(df, args.format), args.output)
    return 0


def build_batch_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="py-tbparse batch",
        description="Run one table across every .twb/.twbx file in a directory.",
    )
    ap.add_argument("directory", help="folder to scan for .twb/.twbx files")
    ap.add_argument("table", nargs="?", default="overview", choices=TABLE_NAMES)
    ap.add_argument("--format", "-f", choices=["table", "csv", "json"], default="table")
    ap.add_argument("--output", "-o", help="write to this file instead of stdout")
    ap.add_argument("--dashboard", help="restrict 'dashboard-sheets' to one dashboard by name")
    ap.add_argument(
        "--include-parameters", action="store_true",
        help="include the 'Parameters' datasource in 'calculated-fields'",
    )
    return ap


def _run_batch(argv: list[str]) -> int:
    args = build_batch_arg_parser().parse_args(argv)
    if not Path(args.directory).is_dir():
        print(f"error: not a directory: {args.directory}", file=sys.stderr)
        return 1

    df = scan_folder(
        args.directory,
        table=args.table,
        dashboard=args.dashboard,
        include_parameters=args.include_parameters,
    )
    _write(_df_text(df, args.format), args.output)
    return 0


def build_rename_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="py-tbparse rename",
        description="Suggest clean field names, e.g. after switching to a new datasource. "
        "Read-only: prints a mapping, never edits the workbook.",
    )
    ap.add_argument("workbook", help="the .twb/.twbx file with the ugly names")
    ap.add_argument(
        "--reference", "-r",
        help="a workbook from before the switch; matching fields take its names",
    )
    ap.add_argument("--style", choices=STYLES, default="title", help="naming style (default: title)")
    ap.add_argument(
        "--cutoff", type=float, default=0.85,
        help="0..1 similarity needed to match a reference name approximately (default: 0.85)",
    )
    ap.add_argument(
        "--kinds", metavar="KIND[,KIND...]",
        help="rename more than fields: any of " + ", ".join(KINDS) + ", or 'all' (default: field)",
    )
    ap.add_argument("--all", action="store_true", help="shorthand for --kinds all")
    ap.add_argument("--only-changed", action="store_true", help="hide fields that need no rename")
    ap.add_argument("--datasource", help="only this datasource (its internal name), e.g. the newly added one")
    ap.add_argument(
        "--write-workbook", nargs="?", const="", metavar="PATH",
        help="also save a copy of the workbook with the renames applied "
        "(default PATH: <name>_renamed.<ext> beside the original; never overwrites)",
    )
    ap.add_argument(
        "--apply", metavar="MAPPING.csv",
        help="skip the suggestions and apply this edited mapping (the CSV from `-f csv`, with the "
        "`suggested` column changed by hand) to a copy of the workbook; "
        "PATH from --write-workbook is optional",
    )
    ap.add_argument(
        "--missing", action="store_true",
        help="instead of renames, list fields with no counterpart between --reference and the workbook "
        "(what stays broken after Replace Data Source)",
    )
    ap.add_argument("--format", "-f", choices=["table", "csv", "json"], default="table")
    ap.add_argument("--output", "-o", help="write to this file instead of stdout")
    return ap


def _run_rename(argv: list[str]) -> int:
    ap = build_rename_arg_parser()
    args = ap.parse_args(argv)
    if args.missing and not args.reference:
        ap.error("--missing needs --reference")
    if args.missing and args.apply:
        ap.error("--missing and --apply cannot be combined")
    try:
        wb = TwbParser(args.workbook)
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if args.apply:
        try:
            mapping = load_rename_mapping(args.apply)
            out = apply_field_renames(wb, renames=mapping, output_path=args.write_workbook or None)
        except (FileNotFoundError, FileExistsError, ValueError, OSError, pd.errors.ParserError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(f"wrote {out} ({int(mapping['changed'].sum())} renames from {args.apply})", file=sys.stderr)
        return 0
    try:
        ref = TwbParser(args.reference) if args.reference else None
    except Exception as e:  # unreadable / malformed reference workbook
        print(f"error: cannot read reference workbook: {e}", file=sys.stderr)
        return 1

    if args.missing:
        try:
            gaps = compare_field_schemas(
                wb, ref, datasource=args.datasource, style=args.style, fuzzy_cutoff=args.cutoff
            )
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        _write(_df_text(gaps, args.format), args.output)
        return 0

    kwargs = dict(reference=ref, style=args.style, fuzzy_cutoff=args.cutoff, datasource=args.datasource)
    kinds = None
    if args.all or args.kinds:
        kinds = KINDS if args.all or args.kinds.strip() == "all" else tuple(
            k.strip() for k in args.kinds.split(",") if k.strip()
        )
    try:
        everything = suggest_renames(wb, kinds=kinds, **kwargs) if kinds else suggest_field_renames(wb, **kwargs)
    except ValueError as e:  # e.g. --cutoff outside 0..1
        print(f"error: {e}", file=sys.stderr)
        return 1
    df = everything[everything["changed"]].reset_index(drop=True) if args.only_changed else everything
    _write(_df_text(df, args.format), args.output)
    if args.write_workbook is not None:
        try:
            out = apply_field_renames(
                wb, renames=everything, output_path=args.write_workbook or None
            )
        except (FileExistsError, ValueError, OSError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(f"wrote {out}", file=sys.stderr)
    return 0


def build_template_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="py-tbparse template",
        description="Make a reusable template from a workbook, or apply one to new data.",
    )
    sub = ap.add_subparsers(dest="action", required=True)

    mk = sub.add_parser("make", help="save WORKBOOK as a template (.twbx with a template.json manifest)")
    mk.add_argument("workbook")
    mk.add_argument("--output", "-o", help="template file (default: <name>.template.twbx beside the workbook)")
    mk.add_argument("--name", help="template name (default: the workbook's)")
    mk.add_argument("--description", help="what the template is for")
    mk.add_argument("--keep-data", action="store_true", help="keep extracts and packaged data as sample data")
    mk.add_argument("--token", "-t", action="append", default=[], metavar="NAME=DEFAULT",
                    help="a default for a {{token}} the workbook uses (repeatable); a token with none must be "
                         "given when the template is applied")

    sh = sub.add_parser("show", help="list the fields and parameters a template needs")
    sh.add_argument("template")
    sh.add_argument("--format", "-f", choices=["table", "csv", "json"], default=None,
                    help="table (default), csv or json; not with --markdown")
    sh.add_argument("--markdown", action="store_true",
                    help="print a documentation page instead (fields, parameters, connections without secrets, "
                         "sheets, dashboards)")
    sh.add_argument("--output", "-o", help="with --markdown: write the page to this file instead of printing it")

    ck = sub.add_parser(
        "check", help="lint a template: leftovers, empty parameters, dangling references",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Look for what a template author probably did not mean. Findings go to stdout, a count to "
                    "stderr; the exit code is 1 when a finding is at or above --fail-on, 2 when the template "
                    "cannot be read or an option is wrong, 3 when a rule crashed (whatever --fail-on says; the "
                    "traceback goes to stderr). Rule ids are stable: use them in CI configs.",
        epilog="rules:\n" + rules_help(),
    )
    ck.add_argument("template")
    ck.add_argument("--format", "-f", choices=["table", "csv", "json"], default="table")
    ck.add_argument("--fail-on", choices=["error", "warning", "info", "never"], default="error",
                    help="exit 1 when a finding has this severity or worse (default: error)")
    ck.add_argument("--only", help="comma-separated rule ids to run, e.g. T001,T003")
    ck.add_argument("--skip", help="comma-separated rule ids not to run")

    sub.add_parser("targets", help="list the database connection classes a target file can use, and how well each is known")

    tm = sub.add_parser(
        "target-make", help="write (and check) a target file: a table in a database, to apply a template to",
        description="A target file describes where the data lives and what its columns are; nothing is read from "
                    "the database and no username or password is ever stored (Tableau asks for them when the "
                    "workbook opens). The columns come from --schema-file (a CREATE TABLE statement or a JSON "
                    "column list) or repeated --column NAME:TYPE.",
    )
    tm.add_argument("--class", dest="conn_class", required=True, metavar="CLASS", help="see 'template targets'")
    tm.add_argument("--server", required=True)
    tm.add_argument("--dbname", required=True, help="the database (MySQL: the schema too)")
    tm.add_argument("--table", help="the table (default: its name in the CREATE TABLE)")
    tm.add_argument("--schema", help="the schema of the table (not for MySQL)")
    tm.add_argument("--port", help="the port (not for SQL Server; default: the class's)")
    tm.add_argument("--warehouse", help="Snowflake only")
    tm.add_argument("--authentication", help="only values Tableau was seen to write for the class")
    tm.add_argument("--schema-file", metavar="PATH", help="a .sql file with one CREATE TABLE, or a .json column list")
    tm.add_argument("--column", "-c", action="append", default=[], metavar="NAME:TYPE", help="a column (repeatable)")
    tm.add_argument("--output", "-o", required=True, metavar="PATH", help="the target file (name it *.target.json)")
    tm.add_argument("--overwrite", action="store_true")
    tm.add_argument("--experimental", action="store_true", help="allow a connection class that was never checked against a workbook Tableau wrote (see 'template targets')")

    up = sub.add_parser(
        "update", help="bring a workbook made by 'template apply' up to date with a newer template revision",
        description="Without --write this only prints what the new revision changes for the workbook's saved "
                    "answers (mapping, parameters) and writes nothing.",
    )
    up.add_argument("template", help="the new revision (make it with 'template make' and the same id: see revision_of)")
    up.add_argument("workbook", help="a workbook made by 'template apply', or an answers file")
    up.add_argument("--old", metavar="TEMPLATE", help="the revision the workbook was made from "
                                                      "(needed only if its answers do not keep that)")
    up.add_argument("--data", "-d", help="use this data file instead of the one the answers name")
    up.add_argument("--sheet", help="the worksheet of an Excel --data file, by name or by index from 0")
    up.add_argument("--datasource", help="which template datasource to update (when it has several)")
    up.add_argument("--mapping", "-m", help="use this edited mapping CSV instead of the saved one")
    up.add_argument("--allow-missing", action="store_true",
                    help="write even if required fields have no column (their sheets will break)")
    up.add_argument("--experimental", action="store_true",
                    help="allow a connection class that was never checked against a workbook Tableau wrote (see 'template targets')")
    up.add_argument("--token", "-t", action="append", default=[], metavar="NAME=VALUE", help="fill a template {{token}} (repeatable), e.g. --token customer=ACME")
    up.add_argument("--write", "-w", nargs="?", const="", metavar="PATH",
                    help="make the workbook (default PATH: <workbook>_r<revision>.twbx; never overwrites)")
    up.add_argument("--format", "-f", choices=["table", "csv", "json"], default="table")

    fo = sub.add_parser(
        "apply-folder", help="make one workbook per data file in a folder, with a summary.csv of what happened",
        description="Each .csv/.tsv/.xlsx/.xlsm in DIR (and each *.target.json, a database table: see "
                    "'template target-make') is matched on its own. A file whose required fields do not "
                    "all find a column is skipped and reported (see --min-mapped). Exit status 1 if any file was "
                    "not written.",
    )
    fo.add_argument("template")
    fo.add_argument("directory", help="the folder of data files")
    fo.add_argument("--output-dir", "-o", metavar="DIR", help="where the workbooks and summary.csv go (default: DIR/out)")
    fo.add_argument("--inputs", "-i", metavar="CSV", help="a sidecar CSV: a 'file' column, an optional 'sheet' column, "
                                                          "and one column per parameter caption, one row per file")
    fo.add_argument("--pattern", action="append", default=[], metavar="GLOB",
                    help="which files to take (repeatable; default: *.csv *.tsv *.xlsx *.xlsm *.target.json)")
    fo.add_argument("--answers", "-a", metavar="PATH", help="saved answers: their mapping is the prior for every file")
    fo.add_argument("--profile", help="a named set of parameters inside the answers file")
    fo.add_argument("--mapping", "-m", help="apply this one edited mapping CSV to every file")
    fo.add_argument("--param", "-p", action="append", default=[], metavar="NAME=VALUE",
                    help="set a parameter for every file (repeatable); the sidecar can override it per file")
    fo.add_argument("--sheet", help="the worksheet for every Excel file (the sidecar can override it per file)")
    fo.add_argument("--datasource", help="which template datasource to fill (when it has several)")
    fo.add_argument("--min-mapped", type=float, metavar="SHARE",
                    help="write a file when at least this share (0..1) of the required fields map, and report the "
                         "sheets that break; default: all required fields must map")
    fo.add_argument("--on-error", choices=["skip", "stop"], default="skip", help="what to do with a file that fails")
    fo.add_argument("--workers", type=int, default=1, help="processes to use (default 1; at most the CPU count)")
    fo.add_argument("--overwrite", action="store_true", help="replace outputs and summary.csv that already exist")
    fo.add_argument("--experimental", action="store_true",
                    help="allow a connection class that was never checked against a workbook Tableau wrote (see 'template targets')")
    fo.add_argument("--token", "-t", action="append", default=[], metavar="NAME=VALUE",
                    help="fill a {{token}} for every file (repeatable); the sidecar can override it per file")
    fo.add_argument("--format", "-f", choices=["table", "csv", "json"], default="table")

    ap_ = sub.add_parser(
        "apply", help="map a template's fields to new data; with --write, make the workbook",
        description="Without --write this only prints the suggested mapping and what would break.",
    )
    ap_.add_argument("template")
    ap_.add_argument("--data", "-d", help="the new data: a .csv, an .xlsx/.xlsm (see --sheet; needs "
                                          "py-tbparse[excel]), a *.target.json that describes a database table "
                                          "('template target-make'), or a .twb/.twbx/.tds connected to it "
                                          "(leave out when --answers or --profile name the data)")
    ap_.add_argument("--experimental", action="store_true",
                     help="allow a connection class that was never checked against a workbook Tableau wrote (see 'template targets')")
    ap_.add_argument("--sheet", help="the worksheet of an Excel --data file, by name or by index from 0 "
                                     "(needed when several are visible)")
    ap_.add_argument("--answers", "-a", metavar="PATH",
                     help="an answers file (*.answers.json) or a workbook made by 'template apply': "
                          "its saved mapping and parameters are the starting point")
    ap_.add_argument("--profile", help="a named set of parameters and data inside the answers file")
    ap_.add_argument("--explain", action="store_true",
                     help="also list what this changes besides the connection: new field types, dropped "
                          "fields and what they break (to stderr)")
    ap_.add_argument("--check", action="store_true",
                     help="also check the new data: missing dimensions, empty columns, repeated keys (to stderr)")
    ap_.add_argument("--deep", action="store_true", help="with --check, read the whole CSV, not its first 2000 rows")
    ap_.add_argument("--token", "-t", action="append", default=[], metavar="NAME=VALUE", help="fill a template {{token}} (repeatable), e.g. --token customer=ACME")
    ap_.add_argument("--datasource", help="which template datasource to fill (when it has several)")
    ap_.add_argument("--data-datasource", help="which datasource of a --data workbook to use")
    ap_.add_argument("--mapping", "-m", help="use this edited mapping CSV instead of the suggestion")
    ap_.add_argument("--mapping-out", help="save the mapping as CSV, to edit and pass back with --mapping")
    ap_.add_argument("--param", "-p", action="append", default=[], metavar="NAME=VALUE",
                     help="set a parameter (repeatable), e.g. -p 'Top N=10'")
    ap_.add_argument("--cutoff", type=float, default=0.85, help="0..1 similarity for approximate matches")
    ap_.add_argument("--allow-missing", action="store_true",
                     help="write even if required fields have no column (their sheets will break)")
    ap_.add_argument(
        "--write", "-w", nargs="?", const="", metavar="PATH",
        help="make the workbook (default PATH: <template>_<data>.twbx beside the template; never overwrites)",
    )
    ap_.add_argument("--format", "-f", choices=["table", "csv", "json"], default="table")
    return ap


def _token_args(ap, items: list[str]) -> dict[str, str]:
    values = {}
    for item in items:
        if "=" not in item:
            ap.error(f"--token expects NAME=VALUE, got {item!r}")
        name, value = item.split("=", 1)
        values[name.strip()] = value
    return values


def _param_args(ap, items: list[str]) -> dict[str, str]:
    params = {}
    for item in items:
        if "=" not in item:
            ap.error(f"--param expects NAME=VALUE, got {item!r}")
        k, v = item.split("=", 1)
        params[k.strip()] = v
    return params


def _run_apply_folder(ap, args) -> int:
    table = apply_template_folder(
        args.template, args.directory, output_dir=args.output_dir, patterns=args.pattern or DEFAULT_BATCH_PATTERNS,
        mapping=args.mapping, params=_param_args(ap, args.param), answers=args.answers, profile=args.profile,
        sheet=_sheet_arg(args.sheet), inputs=args.inputs, datasource=args.datasource, min_mapped=args.min_mapped,
        on_error=args.on_error, overwrite=args.overwrite, workers=args.workers, experimental=args.experimental, tokens=_token_args(ap, args.token))
    _write(_df_text(table, args.format), None)
    counts = table["status"].value_counts().to_dict()
    where = args.output_dir or str(Path(args.directory) / "out")
    print(f"{counts.get('ok', 0)} written, {counts.get('skipped', 0)} skipped, {counts.get('error', 0)} failed; "
          f"summary in {Path(where) / 'summary.csv'}", file=sys.stderr)
    return 0 if (table["status"] == "ok").all() else 1


def _run_targets() -> int:
    from .connections import CLASSES
    rows = [{"class": c.name, "evidence": c.evidence, "schema": c.schema, "needs": " ".join(("server", "dbname", "table") + c.needs),
             "port": c.default_port or "-", "authentication": ", ".join(c.authentication) or "-"}
            for c in CLASSES.values()]
    _write(_df_text(pd.DataFrame(rows).sort_values("class"), "table"), None)
    print("evidence 'corpus': the connection is copied from workbooks Tableau wrote. Types that no corpus workbook "
          "shows for a class are copied from a sibling class and reported as unverified. No target file has been "
          "opened in Tableau yet.", file=sys.stderr)
    return 0


def _run_target_make(ap, args) -> int:
    from .connections import TARGET_FORMAT, check_target
    from .schema import read_schema
    out = Path(args.output)
    if out.exists() and not args.overwrite:
        raise FileExistsError(f"refusing to overwrite {out} (pass --overwrite)")
    if bool(args.schema_file) == bool(args.column):
        ap.error("give the columns with --schema-file or with --column NAME:TYPE, not both or neither")
    body = {"format": TARGET_FORMAT, "version": 1, "class": args.conn_class, "server": args.server, "dbname": args.dbname}
    table = args.table
    if args.schema_file:
        schema_path = Path(args.schema_file)
        found = read_schema(str(schema_path))
        table = table or found.table
        shown = os.path.relpath(schema_path, out.resolve().parent)
        body["schema_file"] = Path(shown).as_posix()
    else:
        columns = []
        for item in args.column:
            if ":" not in item:
                ap.error(f"--column expects NAME:TYPE, got {item!r}")
            name, sql_type = item.rsplit(":", 1)
            columns.append({"name": name.strip(), "type": sql_type.strip()})
        body["columns"] = columns
    if not table:
        ap.error("--table is needed (the schema file names none)")
    body["table"] = table
    for key in ("schema", "port", "warehouse", "authentication"):
        if getattr(args, key):
            body[key] = getattr(args, key)
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(body, indent=2, ensure_ascii=False) + "\n"
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        target = check_target(json.loads(text), out, experimental=args.experimental)   # nothing is written if it fails
    tmp = out.with_name(f".{out.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, out)                   # an existing good file is replaced only by a complete, checked one
    finally:
        tmp.unlink(missing_ok=True)
    for w in caught:
        print(f"note: {w.message}", file=sys.stderr)
    if target["unverified_types"]:
        print(f"note: not seen in Tableau's own output for class {target['class']}: {', '.join(target['unverified_types'])}",
              file=sys.stderr)
    print(f"wrote {out} ({len(target['columns'])} column(s)); not opened in Tableau", file=sys.stderr)
    return 0


def _sheet_arg(value):
    """`--sheet 2` is an index, `--sheet Orders` a name (a sheet really named `2` can be reached by index)."""
    return int(value) if value is not None and value.lstrip("-").isdigit() else value


def _run_template_update(ap, args) -> int:
    t = load_template(args.template)
    report: dict = {}
    if args.write is None:
        table = template_update_report(t, args.workbook, old=args.old, data=args.data)
        if t.manifest_sha256 == (load_answers(args.workbook).get("template") or {}).get("manifest_sha256"):
            print("this workbook was made from exactly this template: nothing to update", file=sys.stderr)
            return 0
        print(f"template revision {t.revision}: {len(table)} change(s)" if len(table) else "no changes that touch the answers",
              file=sys.stderr)
        _write(_df_text(table, args.format), None)
        if (table["impact"] == "needs-mapping").any():
            print("new required fields need a column: edit a mapping (template apply --mapping-out) and pass --mapping, "
                  "or use --allow-missing", file=sys.stderr)
        if (table["impact"] == "needs-value").any():
            print("new tokens need a value: pass --token NAME=VALUE (or give the token a default in the template)",
                  file=sys.stderr)
        return 0
    try:
        out = update_from_answers(
            t, args.workbook, output_path=args.write or None, report=report, allow_missing=args.allow_missing,
            mapping=load_mapping(args.mapping) if args.mapping else None, old=args.old, data=args.data,
            datasource=args.datasource, sheet=_sheet_arg(args.sheet), experimental=args.experimental, tokens=_token_args(ap, args.token))
    except TemplateError:
        if report.get("changes") is not None and len(report["changes"]):
            _write(_df_text(report["changes"], args.format), None, stream=sys.stderr)
        raise
    if out is None:
        print("this workbook was made from exactly this template: nothing to update", file=sys.stderr)
        return 0
    if not report["id_checked"]:
        print("note: the template or the answers have no template id, so they could not be matched", file=sys.stderr)
    for label, key in (("columns added", "columns_added"), ("columns gone", "columns_removed"),
                       ("saved parameter values dropped", "dropped_parameters"),
                       ("saved token values dropped", "dropped_tokens"),
                       ("saved columns that no longer fit", "conflicts")):
        if report.get(key):
            print(f"note: {label}: {', '.join(report[key])}", file=sys.stderr)
    print(f"wrote {out} (template revision {t.revision}, {len(report['changes'])} change(s))", file=sys.stderr)
    return 0


def _ids(text: str | None, option: str = "--only") -> list[str] | None:
    """Rule ids from a comma-separated option. Nothing given (`None` or `""`) is None; a text that holds no id
    (`" "`, `","`) is an error, so a CI variable that expands to blanks cannot switch the check off."""
    if not text:
        return None
    ids = [i.strip() for i in text.split(",") if i.strip()]
    if not ids:
        raise ValueError(f"{option}: no rule ids in {text!r}")
    return ids


def _run_template_check(args) -> int:
    try:
        found = check_template(args.template, only=_ids(args.only, "--only"), skip=_ids(args.skip, "--skip") or ())
    except (FileNotFoundError, ValueError, OSError, zipfile.BadZipFile, json.JSONDecodeError, etree.XMLSyntaxError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    _write(format_findings(found, args.format), None)
    print(findings_summary(found), file=sys.stderr)
    crashed = found.attrs.get("crashed") or []
    if crashed:
        for rule_id in crashed:
            print(f"rule {rule_id} crashed (a bug in py-tbparse, not a finding about the template):\n"
                  + found.attrs["tracebacks"][rule_id], file=sys.stderr)
        return 3
    return 1 if exceeds(found, args.fail_on) else 0


def _run_template(argv: list[str]) -> int:
    ap = build_template_arg_parser()
    args = ap.parse_args(argv)
    if args.action == "show" and args.output and not args.markdown:
        ap.error("--output needs --markdown")
    if args.action == "show":
        if args.markdown and args.format:
            ap.error("--format has no effect with --markdown")
        args.format = args.format or "table"
    if args.action == "check":
        return _run_template_check(args)
    try:
        if args.action == "make":
            out = make_template(args.workbook, output_path=args.output, name=args.name,
                                description=args.description, keep_data=args.keep_data,
                                tokens=_token_args(ap, args.token) or None)
            t = load_template(out)
            req = int(t.fields()["required"].sum())
            tokens = t.manifest.get("tokens")
            print(f"wrote {out} ({req} required field(s), {len(t.parameters())} parameter(s)"
                  + (f", {len(tokens)} token(s): {', '.join(x['name'] for x in tokens)}" if tokens else "") + ")",
                  file=sys.stderr)
            return 0

        if args.action == "targets":
            return _run_targets()
        if args.action == "target-make":
            return _run_target_make(ap, args)
        if args.action == "update":
            return _run_template_update(ap, args)
        if args.action == "apply-folder":
            return _run_apply_folder(ap, args)

        t = load_template(args.template)
        if args.action == "show" and args.markdown:
            page = template_markdown(t)
            if args.output and Path(args.output).resolve() == Path(args.template).resolve():
                raise ValueError(f"--output {args.output} is the template itself; it would be overwritten")
            if args.output:
                Path(args.output).write_text(page, encoding="utf-8")
                print(f"wrote {args.output}", file=sys.stderr)
            else:
                sys.stdout.write(page)
            return 0
        if args.action == "show":
            if t.manifest.get("description"):
                print(t.manifest["description"], file=sys.stderr)
            _write(_df_text(t.fields(), args.format), None)
            if args.format == "table" and len(t.parameters()):
                print("\nParameters:")
                _write(_df_text(t.parameters(), args.format), None)
            if args.format == "table" and len(t.tokens()):
                print("\nTokens ({{name}}; give them with --token NAME=VALUE):")
                _write(_df_text(t.tokens(), args.format), None)
            return 0

        params = {}
        for item in args.param:
            if "=" not in item:
                ap.error(f"--param expects NAME=VALUE, got {item!r}")
            k, v = item.split("=", 1)
            params[k.strip()] = v
        plan = resolve_apply(t, args.data, mapping=load_mapping(args.mapping) if args.mapping else None,
                             params=params, datasource=args.datasource, data_datasource=args.data_datasource,
                             answers=args.answers, profile=args.profile, fuzzy_cutoff=args.cutoff,
                             sheet=_sheet_arg(args.sheet), experimental=args.experimental, tokens=_token_args(ap, args.token))
        data, mapping = plan.data, plan.mapping
        datasource = plan.entry["name"]
        _write(_df_text(mapping, args.format), None)
        if args.mapping_out:
            _write(mapping.to_csv(index=False), args.mapping_out)
        if plan.changed:
            print("note: the data's columns differ from the answers' last run", file=sys.stderr)
        for field in plan.stale:
            print(f"note: saved mapping for {field} no longer fits the data", file=sys.stderr)
        broken = broken_sheets(t, mapping, datasource=datasource)
        for r in broken.to_dict("records"):
            name = r["caption"] or r["field"].strip("[]")
            more = "".join(f"; {label}: {r[key]}" for key, label in
                           (("dashboards", "dashboards"), ("calculations", "calculations"), ("filters", "filtered by")) if r[key])
            print(f"missing: {name} (breaks: {r['sheets'] or 'no sheet'}{more})", file=sys.stderr)
        if args.explain:
            print("\nWhat applying changes:", file=sys.stderr)
            _write(_df_text(explain(t, data, mapping, datasource=datasource), args.format), None, stream=sys.stderr)
        if args.check:
            found = check_data(t, data, mapping, datasource=datasource, deep=args.deep)
            print("\nData checks:" + ("" if len(found) else " nothing found"), file=sys.stderr)
            if len(found):
                _write(_df_text(found, args.format), None, stream=sys.stderr)
        if args.write is None:
            try:
                _token_values(t, plan.tokens)    # what a write would refuse about the tokens, said before it is tried
            except TemplateError as e:
                print(f"note: --write would stop: {e}", file=sys.stderr)
            if not broken.empty:
                print("required fields are unmapped; edit the mapping (--mapping-out / --mapping) "
                      "or pass --allow-missing", file=sys.stderr)
            return 0
        report: dict = {}
        out = apply_template(t, data, mapping=mapping, params=plan.params, output_path=args.write or None,
                             datasource=datasource, allow_missing=args.allow_missing, report=report,
                             answers=args.answers, profile=args.profile, tokens=plan.tokens)
        print(f"wrote {out} ({report['mapped']} field(s) mapped, {report['missing']} missing, "
              f"{report['parameters']} parameter(s) set)", file=sys.stderr)
        return 0
    except (FileNotFoundError, FileExistsError, ValueError, OSError, zipfile.BadZipFile,
            json.JSONDecodeError, etree.XMLSyntaxError, pd.errors.ParserError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def build_library_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="py-tbparse library",
        description="Take calculated fields and parameters out of one workbook (a *.library.json file) and add "
                    "them to another. The output follows what Tableau writes but was never opened in Tableau.",
    )
    sub = ap.add_subparsers(dest="action", required=True)

    ex = sub.add_parser("export", help="save the calculated fields and parameters of WORKBOOK as a library")
    ex.add_argument("workbook")
    ex.add_argument("--output", "-o", required=True, help="library file, e.g. sales.library.json")
    ex.add_argument("--overwrite", action="store_true", help="replace the library file if it exists")
    ex.add_argument("--datasource", help="internal name or caption (needed when several have a connection)")
    ex.add_argument("--folder", help="only the calculations and parameters in this folder")
    ex.add_argument("--field", action="append", default=[], metavar="NAME",
                    help="only this calculation or parameter, by name or caption (repeatable)")
    ex.add_argument("--no-dependencies", action="store_true",
                    help="do not add the calculations and parameters a chosen one uses (they become required)")
    ex.add_argument("--no-parameters", action="store_true", help="leave out parameters nobody picked")
    ex.add_argument("--name", help="library name (default: the workbook's)")
    ex.add_argument("--description", help="what the library is for")

    sh = sub.add_parser("show", help="list what a library holds and needs")
    sh.add_argument("library")
    sh.add_argument("--markdown", action="store_true", help="print a Markdown page")

    im = sub.add_parser(
        "import", help="add a library to WORKBOOK: print the plan; with --write, make the workbook",
        description="Without --write nothing is written: the plan says what would be added, skipped or "
                    "renamed. With --write a copy of the workbook is written (never over the original). "
                    "Exit codes: 1 error, 2 when an entry could not be imported.",
    )
    im.add_argument("workbook")
    im.add_argument("library")
    im.add_argument("--datasource", help="target datasource (internal name or caption)")
    im.add_argument("--mapping", help="CSV with `field` and `mapped_to` (a column name) to say which field a required one is")
    im.add_argument("--on-clash", choices=CLASH_POLICIES, default="rename",
                    help="a name already in use: rename the new caption (default), skip it, or fail")
    im.add_argument("--output", "-o", help="output workbook (default: <name>_library.<ext> beside the workbook)")
    im.add_argument("--overwrite", action="store_true", help="replace the output file if it exists (never the input)")
    im.add_argument("--write", action="store_true", help="write the workbook")
    im.add_argument("--format", choices=("table", "csv", "json"), default="table", help="plan format (default: table)")
    return ap


def _library_markdown(lib: dict) -> str:
    lines = [f"# {lib['name']}", ""]
    if lib.get("description"):
        lines += [lib["description"], ""]
    src = lib.get("source", {})
    lines += [f"From {src.get('workbook')}, datasource {src.get('datasource_caption') or src.get('datasource')}.", ""]
    lines += ["## Calculations and parameters", ""]
    for e in lib["entries"]:
        lines += [f"### {e.get('caption') or e['name']} ({e['kind']}, {e.get('datatype')})", "",
                  "```", e.get("formula_display") or e.get("formula") or "", "```", ""]
    lines += ["## Needs", "", "| kind | name | used by |", "| --- | --- | --- |"]
    by_uid = {e["uid"]: e for e in lib["entries"]}
    for r in lib["required"]:
        users = ", ".join((by_uid[u].get("caption") or by_uid[u]["name"]) for u in r.get("used_by", []) if u in by_uid)
        lines.append(f"| {r['kind']} | {r.get('caption') or r['name']} | {users} |")
    return "\n".join(lines) + "\n"


def _run_library(argv: list[str]) -> int:
    ap = build_library_arg_parser()
    args = ap.parse_args(argv)
    try:
        if args.action == "export":
            report: dict = {}
            lib = export_library(TwbParser(args.workbook), datasource=args.datasource, select=args.field or None,
                                 folder=args.folder, with_dependencies=not args.no_dependencies,
                                 include_parameters=not args.no_parameters, name=args.name,
                                 description=args.description, report=report)
            out = save_library(lib, args.output, overwrite=args.overwrite)
            print(f"wrote {out} ({report['exported']} entries, {report['required']} required)", file=sys.stderr)
            if report["unsupported"]:
                print(f"not exported (they refer to another datasource): {', '.join(report['unsupported_names'])}",
                      file=sys.stderr)
            return 0
        if args.action == "show":
            lib = load_library(args.library)
            if args.markdown:
                sys.stdout.write(_library_markdown(lib))
                return 0
            if lib.get("description"):
                print(lib["description"], file=sys.stderr)
            print(_df_text(library_table(lib), "table"))
            for e in lib["entries"]:
                print(f"\n{e.get('caption') or e['name']} ({e['kind']}):\n{e.get('formula_display') or e.get('formula')}")
            return 0
        parser = TwbParser(args.workbook)
        library = load_library(args.library)
        plan = plan_import(parser, library, datasource=args.datasource, mapping=args.mapping or None,
                           on_clash=args.on_clash)
        print(_df_text(plan, args.format))
        if not args.write:
            rows = plan[plan["uid"] != ""]
            bad = rows["action"].str.startswith("fail").sum()
            print(f"plan only, nothing written; add --write to make the workbook"
                  + (f" ({bad} entries cannot be imported; edit a mapping, see --mapping)" if bad else ""), file=sys.stderr)
            return 0
        report = {}
        out = import_library(parser, library, datasource=args.datasource, mapping=args.mapping or None,
                             on_clash=args.on_clash, output_path=args.output, overwrite=args.overwrite, report=report)
        print(f"wrote {out}", file=sys.stderr)
        print(f"added {report['added']}, already there {report['skipped_identical']}, renamed {report['renamed']}, "
              f"skipped {report['skipped']}, failed {report['failed']}, skipped as dependents {report['skipped_dependents']}",
              file=sys.stderr)
        if report["failed"] or report["skipped_dependents"]:
            names = report["failed_names"] + report["skipped_dependents_names"]
            print(f"not imported: {', '.join(names)}", file=sys.stderr)
            return 2
        return 0
    except (FileNotFoundError, FileExistsError, ValueError, OSError, zipfile.BadZipFile, etree.XMLSyntaxError,
            json.JSONDecodeError, pd.errors.ParserError) as e:   # LibraryError is a ValueError
        print(f"error: {e}", file=sys.stderr)
        return 1


def build_style_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="py-tbparse style",
        description="Colour palettes: list the named custom palettes of workbooks, Preferences.tps files and "
                    "*.style.json files, export them, and add them to a new Preferences.tps or a copy of a "
                    "workbook. Palettes become selectable in the colour picker; nothing is recoloured. The "
                    "output was never opened in Tableau.",
    )
    sub = ap.add_subparsers(dest="action", required=True)
    clash = dict(choices=_style.CLASH_POLICIES, default="fail",
                 help="a palette name already used with other colours: fail (default), skip, rename or replace")

    sh = sub.add_parser("show", help="list the palettes in each SRC")
    sh.add_argument("source", nargs="+", metavar="SRC", help=".twb, .twbx, .tps or .style.json")
    sh.add_argument("--format", choices=("table", "csv", "json"), default="table", help="output format (default: table)")

    ex = sub.add_parser("export", help="save the palettes of the SRC files as a Preferences.tps or a style file")
    ex.add_argument("source", nargs="+", metavar="SRC")
    ex.add_argument("--output", "-o", required=True, help="OUT.tps or OUT.style.json (a new file)")
    ex.add_argument("--palette", action="append", default=[], metavar="NAME", help="only this palette (repeatable)")
    ex.add_argument("--on-clash", **clash)
    ex.add_argument("--name", help="name stored in a style file")
    ex.add_argument("--overwrite", action="store_true", help="replace the output if it exists (never an input or a Preferences.tps)")

    im = sub.add_parser(
        "import", help="add the palettes of LIB to TARGET: print the plan; with --write, write a new file",
        description="Without --write nothing is written. With --write a new file is written next to TARGET "
                    "(or at --output): never over the input and never over an existing Preferences.tps. "
                    "Exit codes: 1 error or a name clash under --on-clash fail, 2 when a palette was invalid "
                    "but the rest were written.",
    )
    im.add_argument("library", metavar="LIB", help=".twb, .twbx, .tps or .style.json to take palettes from")
    im.add_argument("target", metavar="TARGET", help=".tps, .twb or .twbx to add them to (it is not modified)")
    im.add_argument("--palette", action="append", default=[], metavar="NAME", help="only this palette (repeatable)")
    im.add_argument("--on-clash", **clash)
    im.add_argument("--output", "-o", help="new file (default: <name>_palettes.<ext> beside TARGET)")
    im.add_argument("--overwrite", action="store_true", help="replace an earlier output (never the input or a Preferences.tps)")
    im.add_argument("--write", action="store_true", help="write the file")
    im.add_argument("--format", choices=("table", "csv", "json"), default="table", help="plan format (default: table)")

    ck = sub.add_parser("check", help="look for problems in a .tps or .style.json file (exit 1 if any)")
    ck.add_argument("file")
    return ap


def _run_style(argv: list[str]) -> int:
    ap = build_style_arg_parser()
    args = ap.parse_args(argv)
    try:
        if args.action == "show":
            print(_df_text(_style.palettes_table(args.source), args.format))
            return 0
        if args.action == "check":
            problems = _style.check_style_file(args.file)
            for line in problems:
                print(line)
            hard = [p for p in problems if not p.startswith("warning:")]
            print(f"{args.file}: {len(hard)} problem(s)" if hard else f"{args.file}: no problems found", file=sys.stderr)
            return 1 if hard else 0
        report: dict = {}
        if args.action == "export":
            out = _style.export_palettes(args.source, args.output, select=args.palette or None,
                                         on_clash=args.on_clash, name=args.name, overwrite=args.overwrite, report=report)
            print(f"wrote {out}", file=sys.stderr)
        else:
            plan = _style.plan_palette_import(args.target, args.library, on_clash=args.on_clash,
                                              select=args.palette or None)
            if not args.write:
                print(_df_text(plan, args.format))
                clashes = int((plan["action"] == "fail").sum())
                if clashes:
                    print(f"{clashes} palette name(s) clash with other colours; --on-clash replace, rename or skip "
                          "decides what happens (the default, fail, writes nothing)", file=sys.stderr)
                    return 1
                print("plan only, nothing written; add --write to write a new file", file=sys.stderr)
                return 0
            out = _style.import_palettes(args.target, args.library, output_path=args.output, on_clash=args.on_clash,
                                         select=args.palette or None, overwrite=args.overwrite, report=report)
            print(f"wrote {out}", file=sys.stderr)
            print("palettes are now in the colour picker; existing marks keep their colours", file=sys.stderr)
            if out.lower().endswith(".tps"):
                print("copy it over My Tableau Repository/Preferences.tps (keep a backup) and restart Tableau "
                      "Desktop; py-tbparse never writes that file itself", file=sys.stderr)
        c = report["counts"]
        print(f"added {c['added']}, already there {c['skipped_identical']}, renamed {c['renamed']}, "
              f"replaced {c['replaced']}, skipped {c['skipped']}, invalid {c['invalid']}", file=sys.stderr)
        print("not opened in Tableau: check a copy first", file=sys.stderr)
        for w in report["warnings"]:
            print(f"warning: {w}", file=sys.stderr)
        if report["invalid"]:
            print(f"not written (invalid): {', '.join(report['invalid'])}", file=sys.stderr)
            return 2
        return 0
    except (FileNotFoundError, FileExistsError, ValueError, OSError, zipfile.BadZipFile, etree.XMLSyntaxError,
            json.JSONDecodeError) as e:   # StyleError is a ValueError
        print(f"error: {e}", file=sys.stderr)
        return 1


def _is_reserved_subcommand(argv: list[str], name: str) -> bool:
    """True if `argv` invokes the `name` subcommand -- but don't let that
    shadow an actual workbook that happens to be named exactly "diff" or
    "batch" (no extension) sitting in the current directory. A folder of that
    name (`docs/` in a project root) is not a workbook and does not count."""
    return argv[:1] == [name] and not Path(name).is_file()


_WORKBOOK_ERRORS = (FileNotFoundError, ValueError, OSError, zipfile.BadZipFile, etree.XMLSyntaxError)


def _run_audit(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="py-tbparse audit",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Look for what a workbook author probably did not mean: unused calculations and parameters, "
                    "duplicate or circular calculations, custom SQL, extract leftovers. Findings go to stdout, a "
                    "count to stderr; the exit code is 1 when a finding is at or above --fail-on, 2 when the "
                    "workbook cannot be read or an option is wrong, 3 when a rule crashed (whatever --fail-on "
                    "says; the traceback goes to stderr). Rule ids are stable: use them in CI configs. Nothing "
                    "is written or changed, and nothing is opened in Tableau.",
        epilog="rules:\n" + audit_rules_help(),
    )
    ap.add_argument("workbook")
    ap.add_argument("--format", "-f", choices=["table", "csv", "json"], default="table")
    ap.add_argument("--fail-on", choices=["error", "warning", "info", "never"], default="error",
                    help="exit 1 when a finding has this severity or worse (default: error)")
    ap.add_argument("--only", help="comma-separated rule ids to run, e.g. A001,A003")
    ap.add_argument("--skip", help="comma-separated rule ids not to run")
    ap.add_argument("--output", "-o", help="write the findings to this file instead of printing them")
    args = ap.parse_args(argv)
    try:
        found = audit(args.workbook, only=_ids(args.only, "--only"), skip=_ids(args.skip, "--skip") or ())
    except _WORKBOOK_ERRORS as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    _write(format_findings(found, args.format), args.output)
    print(findings_summary(found), file=sys.stderr)
    crashed = found.attrs.get("crashed") or []
    if crashed:
        for rule_id in crashed:
            print(f"rule {rule_id} crashed (a bug in py-tbparse, not a finding about the workbook):\n"
                  + found.attrs["tracebacks"][rule_id], file=sys.stderr)
        return 3
    return 1 if exceeds(found, args.fail_on) else 0


def _run_docs(argv: list[str], prog: str = "py-tbparse docs") -> int:
    ap = argparse.ArgumentParser(
        prog=prog,
        description="Write a Markdown data dictionary of a workbook: overview, datasources with their connections "
                    "(no user names or passwords, files by name only), fields with formulas and what uses them, "
                    "parameters, worksheets and dashboards. The same workbook always gives the same text. "
                    "Formulas and captions are printed as the workbook has them. Nothing is opened in Tableau.",
    )
    ap.add_argument("workbook")
    ap.add_argument("--output", "-o", help="write the page to this file instead of printing it")
    ap.add_argument("--graph", action="store_true", help="add the relationship graph as a DOT block")
    args = ap.parse_args(argv)
    try:
        page = workbook_markdown(TwbParser(args.workbook), graph=args.graph)
    except _WORKBOOK_ERRORS as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if args.output and Path(args.output).resolve() == Path(args.workbook).resolve():
        print("error: --output is the workbook itself; refusing to overwrite it", file=sys.stderr)
        return 2
    sys.stdout.write(page) if not args.output else Path(args.output).write_text(page, encoding="utf-8")
    if args.output:
        print(f"wrote {args.output}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    raw_argv = sys.argv[1:] if argv is None else list(argv)
    if _is_reserved_subcommand(raw_argv, "diff"):
        return _run_diff(raw_argv[1:])
    if _is_reserved_subcommand(raw_argv, "batch"):
        return _run_batch(raw_argv[1:])
    if _is_reserved_subcommand(raw_argv, "rename"):
        return _run_rename(raw_argv[1:])
    if _is_reserved_subcommand(raw_argv, "template"):
        return _run_template(raw_argv[1:])
    if _is_reserved_subcommand(raw_argv, "library"):
        return _run_library(raw_argv[1:])
    if _is_reserved_subcommand(raw_argv, "audit"):
        return _run_audit(raw_argv[1:])
    if _is_reserved_subcommand(raw_argv, "docs"):
        return _run_docs(raw_argv[1:])
    if _is_reserved_subcommand(raw_argv, "dictionary"):
        return _run_docs(raw_argv[1:], prog="py-tbparse dictionary")
    if _is_reserved_subcommand(raw_argv, "style"):
        return _run_style(raw_argv[1:])

    args = build_arg_parser().parse_args(argv)

    if args.table == "tables":
        for name in TABLE_NAMES:
            print(name)
        return 0

    try:
        parser = TwbParser(args.workbook)
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if args.table == "graph":
        dot = parser.get_relationship_graph_dot(include_inferred=args.include_inferred)
        _write(dot, args.output)
        return 0

    if args.table == "validate":
        result = parser.validate()
        if args.format == "json":
            payload = {
                "ok": result["ok"],
                "issues": {
                    name: df.to_dict(orient="records")
                    for name, df in result["issues"].items()
                },
            }
            _write(json.dumps(payload, indent=2, default=str), args.output)
        else:
            lines = [f"ok: {result['ok']}"]
            for name, df in result["issues"].items():
                lines.append(f"\n{name}:")
                lines.append(df.to_string(index=False))
            _write("\n".join(lines), args.output)
        return 0 if result["ok"] else 2

    getter = TABLE_SPECS[args.table]
    df = getter(
        parser,
        dashboard=args.dashboard,
        include_parameters=args.include_parameters,
    )
    _write(_df_text(df, args.format), args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
