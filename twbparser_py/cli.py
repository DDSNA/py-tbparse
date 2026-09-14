"""Command-line interface: `twbparser WORKBOOK [TABLE] [options]`.

Two reserved subcommands, dispatched on the first argument before the
normal single-workbook parser runs: `twbparser diff A.twb B.twb [TABLE]`
and `twbparser batch DIR [TABLE]`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from ._tables import TABLE_NAMES, TABLE_SPECS
from .batch import scan_folder
from .diff import diff_workbooks
from .parser import TwbParser


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


def _write(text: str, output: str | None) -> None:
    if output:
        Path(output).write_text(text)
    else:
        print(text)


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="twbparser",
        description="Parse a Tableau .twb/.twbx workbook and print one of its tables. "
        "See also: 'twbparser diff A.twb B.twb [TABLE]' and 'twbparser batch DIR [TABLE]'.",
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
        prog="twbparser diff",
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
        prog="twbparser batch",
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
