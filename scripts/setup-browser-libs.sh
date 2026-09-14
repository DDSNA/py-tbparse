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

# A handful of these packages picked up a "t64" suffix in the 64-bit-time_t
# transition (Debian 13/trixie, Ubuntu 24.04+); older releases (Debian 12,
# Ubuntu 22.04) still use the unsuffixed name. Probe apt's cache for each
# and pick whichever name it actually knows, instead of hardcoding one.
resolve_name() {
  local candidate
  for candidate in "$@"; do
    if apt-cache show "$candidate" >/dev/null 2>&1; then
      echo "$candidate"
      return 0
    fi
  done
  # None matched -- fall back to the first candidate so the apt-get call
  # below reports a real, specific error instead of this script inventing
  # one from a probe that itself might be unreliable.
  echo "$1"
}

PACKAGES=(
  libnss3 libnspr4 libgbm1
  "$(resolve_name libasound2t64 libasound2)"
  "$(resolve_name libatk1.0-0t64 libatk1.0-0)"
  "$(resolve_name libatk-bridge2.0-0t64 libatk-bridge2.0-0)"
  "$(resolve_name libatspi2.0-0t64 libatspi2.0-0)"
  libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2
)

echo "==> Resolving dependency closure for: ${PACKAGES[*]}"
mkdir -p "$DEB_DIR" "$EXTRACT_DIR"

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

# --print-uris resolves transitive deps and skips anything already
# installed. Keep stderr instead of discarding it: a resolution failure
# (e.g. a package name that doesn't exist on this distro) should surface
# here, not as an opaque failure two steps later.
if ! apt-get install --print-uris -y "${PACKAGES[@]}" > "$WORKDIR/uris.txt" 2> "$WORKDIR/apt-stderr.txt"; then
  echo "==> apt-get could not resolve the package list:" >&2
  cat "$WORKDIR/apt-stderr.txt" >&2
  exit 1
fi

# Matching lines look like:
#   'URL' cache-filename size-in-bytes HashName:hexdigest [HashName:hexdigest ...]
# Extract (url, hash) pairs. `|| true` because grep exits 1 on zero
# matches -- which is this script's own documented success case (the
# libraries are already installed system-wide) and must not trip `set -e`
# via pipefail.
MATCH_LINES="$WORKDIR/matches.txt"
grep "^'" "$WORKDIR/uris.txt" > "$MATCH_LINES" || true

count="$(wc -l < "$MATCH_LINES" | tr -d ' ')"
if [ "$count" -eq 0 ]; then
  echo "==> Nothing to download; the libraries are already present system-wide."
  exit 0
fi

echo "==> Downloading and verifying $count package(s) into $DEB_DIR"
while IFS= read -r line; do
  url="$(grep -oP "^'\K[^']+" <<<"$line")"
  # Prefer SHA256 if apt's config offers it; MD5Sum is the only hash this
  # environment's apt actually emits, so it's the realistic fallback --
  # either way this is integrity verification (did we get the bytes apt
  # resolved), not a substitute for fetching over a trusted transport.
  hash_field="$(grep -oP 'SHA256:\S+' <<<"$line" || grep -oP 'MD5Sum:\S+' <<<"$line" || true)"
  algo="${hash_field%%:*}"
  digest="${hash_field#*:}"
  fname="$(basename "$url")"
  dest="$DEB_DIR/$fname"

  if [ ! -f "$dest" ]; then
    wget -q -O "$dest" "$url"
  fi

  if [ -z "$algo" ]; then
    echo "    warning: no checksum offered for $fname -- skipping verification" >&2
    continue
  fi

  actual=""
  case "$algo" in
    SHA256) actual="$(sha256sum "$dest" | cut -d' ' -f1)" ;;
    MD5Sum) actual="$(md5sum "$dest" | cut -d' ' -f1)" ;;
    *) echo "    warning: unrecognized hash type '$algo' for $fname -- skipping verification" >&2 ;;
  esac

  if [ -n "$actual" ] && [ "$actual" != "$digest" ]; then
    echo "==> checksum mismatch for $fname (expected $algo:$digest, got $actual)" >&2
    rm -f "$dest"
    exit 1
  fi
done < "$MATCH_LINES"

echo "==> Extracting into $EXTRACT_DIR"
for deb in "$DEB_DIR"/*.deb; do
  dpkg-deb -x "$deb" "$EXTRACT_DIR"
done

LIBDIR="$EXTRACT_DIR/usr/lib/x86_64-linux-gnu"
echo "==> Done. Libraries in: $LIBDIR"
echo "    The browser tests find this automatically; run them with:"
echo "      pytest tests/test_gui_browser.py"
