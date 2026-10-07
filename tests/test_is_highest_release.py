import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "is_highest_release.py"
sys.path.insert(0, str(SCRIPT.parent))
from is_highest_release import is_highest  # noqa: E402

TAGS = ["v0.5.2", "v0.5.3", "v0.5.4", "v0.5.2.post1", "v0.4.10", "nightly"]


@pytest.mark.parametrize("version, expected", [
    ("0.5.4", True),
    ("0.5.5", True),
    ("0.6.0", True),
    ("0.5.4.post1", True),
    ("0.5.2.post1", False),   # hotfix of an older version
    ("0.5.2.post2", False),
    ("0.5.3", False),
    ("0.4.10", False),        # 0.4.10 is above 0.4.9 numerically, not as text
])
def test_is_highest(version, expected):
    assert is_highest(version, TAGS) is expected


def test_first_release_and_post_ordering():
    assert is_highest("0.1.0", [])
    assert is_highest("0.5.2.post2", ["v0.5.2", "v0.5.2.post1"])
    assert not is_highest("0.5.2", ["v0.5.2.post1"])


def test_rejects_non_version():
    with pytest.raises(ValueError):
        is_highest("main", TAGS)


def test_command_line():
    def run(version):
        return subprocess.run([sys.executable, str(SCRIPT), version], input="\n".join(TAGS),
                              capture_output=True, text=True, check=True).stdout.strip()
    assert run("0.5.4") == "true"
    assert run("0.5.2.post1") == "false"
