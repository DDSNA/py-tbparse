"""Command-line interface: `py-tbparse WORKBOOK [TABLE] [options]`.

Three reserved subcommands, dispatched on the first argument before the
normal single-workbook parser runs: `py-tbparse diff A.twb B.twb [TABLE]`,
`py-tbparse batch DIR [TABLE]` and `py-tbparse rename WORKBOOK [-r OLD.twb]`.
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

import pandas as pd
from lxml import etree

from ._tables import TABLE_NAMES, TABLE_SPECS
from .batch import scan_folder
from .diff import diff_workbooks
from .parser import TwbParser
from .templates import (
    apply_template,
    broken_sheets,
    check_data,
    explain,
    load_mapping,
    load_template,
    make_template,
    resolve_apply,
)
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

    sh = sub.add_parser("show", help="list the fields and parameters a template needs")
    sh.add_argument("template")
    sh.add_argument("--format", "-f", choices=["table", "csv", "json"], default="table")

    ap_ = sub.add_parser(
        "apply", help="map a template's fields to new data; with --write, make the workbook",
        description="Without --write this only prints the suggested mapping and what would break.",
    )
    ap_.add_argument("template")
    ap_.add_argument("--data", "-d", help="the new data: a .csv, or a .twb/.twbx/.tds connected to it "
                                          "(leave out when --answers or --profile name the data)")
    ap_.add_argument("--answers", "-a", metavar="PATH",
                     help="an answers file (*.answers.json) or a workbook made by 'template apply': "
                          "its saved mapping and parameters are the starting point")
    ap_.add_argument("--profile", help="a named set of parameters and data inside the answers file")
    ap_.add_argument("--explain", action="store_true",
                     help="also list everything this changes besides the connection (to stderr)")
    ap_.add_argument("--check", action="store_true",
                     help="also check the new data: missing dimensions, empty columns, repeated keys (to stderr)")
    ap_.add_argument("--deep", action="store_true", help="with --check, read the whole CSV, not its first 2000 rows")
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


def _run_template(argv: list[str]) -> int:
    ap = build_template_arg_parser()
    args = ap.parse_args(argv)
    try:
        if args.action == "make":
            out = make_template(args.workbook, output_path=args.output, name=args.name,
                                description=args.description, keep_data=args.keep_data)
            t = load_template(out)
            req = int(t.fields()["required"].sum())
            print(f"wrote {out} ({req} required field(s), {len(t.parameters())} parameter(s))", file=sys.stderr)
            return 0

        t = load_template(args.template)
        if args.action == "show":
            if t.manifest.get("description"):
                print(t.manifest["description"], file=sys.stderr)
            _write(_df_text(t.fields(), args.format), None)
            if args.format == "table" and len(t.parameters()):
                print("\nParameters:")
                _write(_df_text(t.parameters(), args.format), None)
            return 0

        params = {}
        for item in args.param:
            if "=" not in item:
                ap.error(f"--param expects NAME=VALUE, got {item!r}")
            k, v = item.split("=", 1)
            params[k.strip()] = v
        plan = resolve_apply(t, args.data, mapping=load_mapping(args.mapping) if args.mapping else None,
                             params=params, datasource=args.datasource, data_datasource=args.data_datasource,
                             answers=args.answers, profile=args.profile, fuzzy_cutoff=args.cutoff)
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
            if not broken.empty:
                print("required fields are unmapped; edit the mapping (--mapping-out / --mapping) "
                      "or pass --allow-missing", file=sys.stderr)
            return 0
        report: dict = {}
        out = apply_template(t, data, mapping=mapping, params=plan.params, output_path=args.write or None,
                             datasource=datasource, allow_missing=args.allow_missing, report=report,
                             answers=args.answers, profile=args.profile)
        print(f"wrote {out} ({report['mapped']} field(s) mapped, {report['missing']} missing, "
              f"{report['parameters']} parameter(s) set)", file=sys.stderr)
        return 0
    except (FileNotFoundError, FileExistsError, ValueError, OSError, zipfile.BadZipFile,
            json.JSONDecodeError, etree.XMLSyntaxError, pd.errors.ParserError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def _is_reserved_subcommand(argv: list[str], name: str) -> bool:
    """True if `argv` invokes the `name` subcommand -- but don't let that
    shadow an actual workbook that happens to be named exactly "diff" or
    "batch" (no extension) sitting in the current directory."""
    return argv[:1] == [name] and not Path(name).exists()


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
