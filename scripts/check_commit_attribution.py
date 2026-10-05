#!/usr/bin/env python3
"""Fail if a commit in a range names an AI tool or is not by DDSNA.

    python scripts/check_commit_attribution.py BASE..HEAD

Checks every commit in the range (the commits of a pull request, not the squash
commit on main, which GitHub authors as "Dan"):

- author and committer must be DDSNA <79444147+DDSNA@users.noreply.github.com>.
  A committer of GitHub <noreply@github.com> is also accepted when the author is
  DDSNA, because that is what a commit made in the web UI looks like.
- no `Co-Authored-By` line that names Claude or Anthropic;
- no "Generated with" line.

Exit status 0 when all commits pass, 1 when any fails, 2 on a usage or git error.
"""

from __future__ import annotations

import re
import subprocess
import sys

OWNER = ("DDSNA", "79444147+DDSNA@users.noreply.github.com")
WEB_COMMITTER = ("GitHub", "noreply@github.com")
CO_AUTHOR = re.compile(r"^\s*co-authored-by:.*(claude|anthropic)", re.I | re.M)
GENERATED = re.compile(r"^\W*generated with\b", re.I | re.M)


def problems(commit: str, an: str, ae: str, cn: str, ce: str, body: str) -> list[str]:
    out = []
    if (an, ae) != OWNER:
        out.append(f"author is {an} <{ae}>, not DDSNA")
    if (cn, ce) not in (OWNER, WEB_COMMITTER) or ((cn, ce) == WEB_COMMITTER and (an, ae) != OWNER):
        out.append(f"committer is {cn} <{ce}>, not DDSNA")
    if CO_AUTHOR.search(body):
        out.append("Co-Authored-By names Claude or Anthropic")
    if GENERATED.search(body):
        out.append('has a "Generated with" line')
    return [f"{commit[:12]}: {p}" for p in out]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    fmt = "%H%x1f%an%x1f%ae%x1f%cn%x1f%ce%x1f%B%x1e"
    p = subprocess.run(["git", "log", f"--format={fmt}", argv[1]], capture_output=True, text=True)
    if p.returncode != 0:
        print(p.stderr.strip(), file=sys.stderr)
        return 2
    bad = []
    n = 0
    for rec in p.stdout.split("\x1e"):
        if not rec.strip():
            continue
        n += 1
        bad += problems(*rec.strip("\n").split("\x1f", 5))
    for line in bad:
        print(f"FAIL {line}")
    print(f"{n} commit(s) checked, {len(bad)} problem(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
