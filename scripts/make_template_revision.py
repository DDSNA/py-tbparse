#!/usr/bin/env python3
"""Make a second revision of a template from a workbook, for `template update` (the CLI's `template make` has no
`revision_of` option, so this is the command line for the Python API).

    python scripts/make_template_revision.py WORKBOOK OLD_TEMPLATE NEW_TEMPLATE

NEW_TEMPLATE is made from WORKBOOK with the same template id as OLD_TEMPLATE and the next revision number. It is
never written over an existing file. scripts/make_tableau_check_pack.py uses it for file 56 and lists the call in
commands.txt, so every line of that file can be run on a fresh checkout.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from py_tbparse import make_template  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Make a new revision of a template (same id, revision + 1).")
    ap.add_argument("workbook")
    ap.add_argument("old_template")
    ap.add_argument("new_template")
    args = ap.parse_args(argv)
    out = make_template(args.workbook, output_path=args.new_template, revision_of=args.old_template)
    print(f"wrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
