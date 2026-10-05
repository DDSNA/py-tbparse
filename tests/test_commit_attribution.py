"""scripts/check_commit_attribution.py against a throwaway git repo (no network)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_commit_attribution.py"
OWNER = ("DDSNA", "79444147+DDSNA@users.noreply.github.com")


def git(repo, *args, env=None):
    e = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull, **(env or {})}
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True, env=e).stdout.strip()


def commit(repo, msg, author=OWNER, committer=OWNER):
    (repo / "f.txt").write_text(msg + os.urandom(4).hex())
    git(repo, "add", "f.txt")
    env = {
        "GIT_AUTHOR_NAME": author[0], "GIT_AUTHOR_EMAIL": author[1],
        "GIT_COMMITTER_NAME": committer[0], "GIT_COMMITTER_EMAIL": committer[1],
    }
    git(repo, "commit", "-q", "-m", msg, env=env)


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    commit(tmp_path, "base", author=("Dan", "dan@example.com"), committer=("Dan", "dan@example.com"))
    return tmp_path


def run(repo):
    p = subprocess.run([sys.executable, str(SCRIPT), "main..HEAD"], cwd=repo, capture_output=True, text=True)
    return p.returncode, p.stdout


def branch(repo):
    git(repo, "checkout", "-q", "-b", "pr")


def test_good_commits_pass_and_the_base_is_not_checked(repo):
    branch(repo)
    commit(repo, "one\n\nA body with Claude Code mentioned in prose is fine.")
    commit(repo, "two")
    code, out = run(repo)
    assert code == 0, out
    assert "2 commit(s) checked" in out


def test_web_ui_committer_is_accepted_for_the_owner(repo):
    branch(repo)
    commit(repo, "web", committer=("GitHub", "noreply@github.com"))
    assert run(repo)[0] == 0


@pytest.mark.parametrize("msg", [
    "x\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
    "x\n\nco-authored-by: Claude Sonnet 5.5 <noreply@anthropic.com>",
    "x\n\nCo-authored-by: Someone <a@anthropic.com>",
    "x\n\n\U0001F916 Generated with [Claude Code](https://claude.com/claude-code)",
    "x\n\nGenerated with some tool",
])
def test_ai_trailers_fail(repo, msg):
    branch(repo)
    commit(repo, msg)
    code, out = run(repo)
    assert code == 1 and "FAIL" in out, out


def test_a_human_co_author_is_not_flagged(repo):
    branch(repo)
    commit(repo, "x\n\nCo-Authored-By: Pat <pat@example.com>")
    assert run(repo)[0] == 0


def test_wrong_author_fails(repo):
    branch(repo)
    commit(repo, "x", author=("Dan", "dan@example.com"))
    code, out = run(repo)
    assert code == 1 and "author is Dan" in out


def test_wrong_committer_fails(repo):
    branch(repo)
    commit(repo, "x", committer=("Claude", "noreply@anthropic.com"))
    code, out = run(repo)
    assert code == 1 and "committer is Claude" in out


def test_web_committer_does_not_excuse_a_wrong_author(repo):
    branch(repo)
    commit(repo, "x", author=("Claude", "noreply@anthropic.com"), committer=("GitHub", "noreply@github.com"))
    code, out = run(repo)
    assert code == 1 and "author is Claude" in out and "committer is GitHub" in out


def test_one_bad_commit_among_good_ones_fails(repo):
    branch(repo)
    commit(repo, "good")
    commit(repo, "bad\n\nCo-Authored-By: Claude <noreply@anthropic.com>")
    commit(repo, "good again")
    code, out = run(repo)
    assert code == 1 and out.count("FAIL") == 1 and "3 commit(s) checked" in out


def test_bad_range_is_a_usage_error(repo):
    p = subprocess.run([sys.executable, str(SCRIPT), "nope..HEAD"], cwd=repo, capture_output=True, text=True)
    assert p.returncode == 2
