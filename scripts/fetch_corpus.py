#!/usr/bin/env python3
"""Download the example-workbook corpus listed in tests/corpus/manifest.csv.

The 200 workbooks (about 26 MB) are not stored in git. Each row of the manifest
pins a file to the blob of a public GitHub repository, so this script fetches
exactly those bytes and checks every one against the recorded SHA-256.

    python scripts/fetch_corpus.py            # download what is missing
    python scripts/fetch_corpus.py --force    # re-download everything

Uses the `gh` CLI if it is installed and logged in (no rate limit trouble),
otherwise plain HTTPS to api.github.com (60 requests an hour without a token;
set GITHUB_TOKEN for more).
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

CORPUS = Path(__file__).resolve().parent.parent / "tests" / "corpus"


def _blob(repo: str, sha: str) -> bytes:
    if shutil.which("gh"):
        p = subprocess.run(["gh", "api", f"repos/{repo}/git/blobs/{sha}"], capture_output=True, text=True)
        if p.returncode == 0:
            return base64.b64decode(json.loads(p.stdout)["content"])
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/git/blobs/{sha}",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "py-tbparse-fetch-corpus",
                 **({"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}"} if os.environ.get("GITHUB_TOKEN") else {})},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return base64.b64decode(json.load(r)["content"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="download files that are already present")
    args = ap.parse_args()
    out = CORPUS / "files"
    out.mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader(open(CORPUS / "manifest.csv", encoding="utf-8")))
    got = bad = 0
    for i, row in enumerate(rows, 1):
        dest = out / row["file"]
        if dest.exists() and not args.force and hashlib.sha256(dest.read_bytes()).hexdigest() == row["sha256"]:
            continue
        try:
            data = _blob(row["repo"], row["sha"])
        except Exception as e:  # network, rate limit, repo or file removed
            print(f"[{i}/{len(rows)}] {row['file']}: {e}", file=sys.stderr)
            bad += 1
            continue
        if hashlib.sha256(data).hexdigest() != row["sha256"]:
            print(f"[{i}/{len(rows)}] {row['file']}: checksum differs from the manifest, skipped", file=sys.stderr)
            bad += 1
            continue
        dest.write_bytes(data)
        got += 1
    print(f"{got} downloaded, {len(rows) - got - bad} already present, {bad} failed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
