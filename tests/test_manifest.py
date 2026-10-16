"""What MANIFEST.in puts in the sdist (issue #200). Read as text: building an sdist needs setuptools."""

from pathlib import Path

ROOT = Path(__file__).parent.parent
RULES = [line.split() for line in (ROOT / "MANIFEST.in").read_text(encoding="utf-8").splitlines() if line.strip()]


def test_the_design_mockups_stay_out_of_the_sdist():
    assert ["prune", "docs/design"] in RULES
    # prune wins over any include, but it must not be the only thing keeping other docs images in
    assert ["recursive-include", "docs", "*.png"] in RULES


def test_every_fixture_folder_the_tests_read_is_in_the_sdist():
    """A fixtures sub-folder without a rule would leave the tests unable to run from the sdist."""
    included = {r[1] for r in RULES if r[0] == "recursive-include" and r[2:] == ["*"]}
    folders = {f"tests/fixtures/{p.name}" for p in (ROOT / "tests" / "fixtures").iterdir() if p.is_dir()}
    assert folders <= included, f"no sdist rule for: {sorted(folders - included)}"
