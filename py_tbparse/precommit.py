"""Entry point of the pre-commit hooks (`.pre-commit-hooks.yaml`).

pre-commit calls a hook once with many file names (`entry [args] file1 file2 ...`), but `audit`,
`validate` and `template check` take one file each. This runs the command for every file and
returns the worst exit code (0 to 3, the codes of the commands themselves). Which arguments are
files: those ending in `.twb` or `.twbx`; everything else is passed to the
command as an option (`--fail-on warning`).

    python -m py_tbparse.precommit audit --fail-on warning a.twb b.twbx
"""

from __future__ import annotations

import sys

from .cli import main as cli_main

_FILE_SUFFIXES = (".twb", ".twbx")


def _is_file_arg(arg: str) -> bool:
    return arg.lower().endswith(_FILE_SUFFIXES)


def build_argv(command: str, options: list[str], path: str) -> list[str]:
    if command == "audit":
        return ["audit", *options, path]
    if command == "template-check":
        return ["template", "check", *options, path]
    if command == "validate":
        return [path, "validate", *options]
    raise ValueError(f"unknown hook command {command!r}; use audit, validate or template-check")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if not args:
        print("usage: python -m py_tbparse.precommit audit|validate|template-check [options] FILE...", file=sys.stderr)
        return 2
    command, rest = args[0], args[1:]
    options = [a for a in rest if not _is_file_arg(a)]
    files = [a for a in rest if _is_file_arg(a)]
    try:
        build_argv(command, [], "x.twb")
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    worst = 0
    for path in files:
        try:
            rc = cli_main(build_argv(command, options, path))
        except SystemExit as e:        # argparse: a wrong option
            rc = e.code if isinstance(e.code, int) else 2
        worst = max(worst, rc)
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
