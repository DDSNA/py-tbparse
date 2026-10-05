"""scripts/git-hooks/pre-push fed the lines git sends it on stdin (no git repo, no network)."""

import shutil
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent.parent / "scripts" / "git-hooks" / "pre-push"
SHA = "a" * 40
OLD = "b" * 40
ZERO = "0" * 40

pytestmark = pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX sh")


def run(*lines):
    return subprocess.run(
        ["sh", str(HOOK), "origin", "https://example.invalid/r.git"],
        input="".join(line + "\n" for line in lines), capture_output=True, text=True,
    )


def test_feature_branch_is_allowed():
    assert run(f"refs/heads/x {SHA} refs/heads/x {ZERO}").returncode == 0


def test_no_input_is_allowed():
    assert run().returncode == 0


@pytest.mark.parametrize("branch", ["main", "master"])
def test_push_to_main_or_master_is_refused(branch):
    p = run(f"refs/heads/x {SHA} refs/heads/{branch} {OLD}")
    assert p.returncode == 1 and f"refs/heads/{branch}" in p.stderr


def test_force_push_to_main_is_refused():
    # a rewritten history looks the same to the hook: different shas, remote ref main
    assert run(f"refs/heads/main {SHA} refs/heads/main {OLD}").returncode == 1


def test_deleting_main_is_refused():
    assert run(f"(delete) {ZERO} refs/heads/main {OLD}").returncode == 1


def test_main_among_other_refs_is_refused():
    p = run(f"refs/heads/x {SHA} refs/heads/x {ZERO}", f"refs/heads/y {SHA} refs/heads/main {OLD}")
    assert p.returncode == 1


def test_branches_that_only_contain_main_in_the_name_are_allowed():
    for ref in ("refs/heads/main-fix", "refs/heads/feature/main", "refs/tags/main", "refs/heads/mainline"):
        assert run(f"refs/heads/x {SHA} {ref} {ZERO}").returncode == 0, ref
