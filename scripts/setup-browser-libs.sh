#!/usr/bin/env bash
# Make headless Chromium runnable without root.
#
# Playwright's browser needs a set of system libraries (libnss3, libgbm,
# libatk, ...). The usual fix is `playwright install-deps`, which apt-installs
# them system-wide and needs root. This script instead downloads the same
# Debian packages and unpacks them into .browser-libs/ inside the repo, so
# nothing outside this directory is touched. tests/test_gui_browser.py picks
# the directory up automatically and points the browser's loader at it.
#
# Usage:  ./scripts/setup-browser-libs.sh
# Undo:   rm -rf .browser-libs
#
# On a machine where the libraries are already installed system-wide (CI, or
# after `playwright install --with-deps`), this script is unnecessary.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LIB_ROOT="$REPO_ROOT/.browser-libs"
DEB_DIR="$LIB_ROOT/debs"
EXTRACT_DIR="$LIB_ROOT/root"

PACKAGES=(
  libnss3 libnspr4 libgbm1 libasound2t64
  libatk1.0-0t64 libatk-bridge2.0-0t64 libatspi2.0-0t64
  libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2
)

echo "==> Resolving dependency closure for: ${PACKAGES[*]}"
mkdir -p "$DEB_DIR" "$EXTRACT_DIR"
URI_LIST="$(mktemp)"
trap 'rm -f "$URI_LIST"' EXIT

# --print-uris resolves transitive deps and skips anything already installed.
apt-get install --print-uris -y "${PACKAGES[@]}" 2>/dev/null \
  | grep -oP "(?<=^')[^']+\.deb" > "$URI_LIST"

count="$(wc -l < "$URI_LIST")"
if [ "$count" -eq 0 ]; then
  echo "==> Nothing to download; the libraries are already present system-wide."
  exit 0
fi

echo "==> Downloading $count package(s) into $DEB_DIR"
(cd "$DEB_DIR" && wget -q -nc -i "$URI_LIST")

echo "==> Extracting into $EXTRACT_DIR"
for deb in "$DEB_DIR"/*.deb; do
  dpkg-deb -x "$deb" "$EXTRACT_DIR"
done

LIBDIR="$EXTRACT_DIR/usr/lib/x86_64-linux-gnu"
echo "==> Done. Libraries in: $LIBDIR"
echo "    The browser tests find this automatically; run them with:"
echo "      pytest tests/test_gui_browser.py"
