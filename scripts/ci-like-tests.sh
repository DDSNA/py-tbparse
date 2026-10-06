#!/usr/bin/env bash
# Run the tests the way CI does: plain `pytest` (not `python -m pytest`, which puts the current
# directory on sys.path and hides import mistakes), with PYTHONPATH set to this checkout so a
# venv whose editable install points at another checkout still imports this one.
#
#   scripts/ci-like-tests.sh                      # whole suite, like CI's `pytest -q`
#   scripts/ci-like-tests.sh tests/test_audit.py  # extra arguments go to pytest
#   PYTEST=.venv/bin/pytest scripts/ci-like-tests.sh   # pick the pytest to use
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
export PYTHONPATH="$root${PYTHONPATH:+:$PYTHONPATH}"
pytest_bin="${PYTEST:-pytest}"
if [ $# -eq 0 ]; then set -- -q; fi
exec "$pytest_bin" "$@"
