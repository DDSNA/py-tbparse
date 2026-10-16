"""scripts/make_tableau_check_pack.py: every kind of output in one folder, for the manual Tableau check
(docs/tableau-check.md). Nothing here opens Tableau; it checks that the pack is made and is not worse than its
inputs by the same schema and reference checks the writers' own tests use."""

import csv
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from schema_check import new_schema_errors

from py_tbparse import TwbParser
from py_tbparse.verify import validate_workbook

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "docs" / "demo" / "coffee-shop.twb"
FILTERING = ROOT / "tests" / "fixtures" / "public" / "filtering.twb"
LIB_TARGET = ROOT / "tests" / "fixtures" / "library" / "target.twb"

# made file -> the workbook it was made from
SOURCES = {
    "10-rename.twb": DEMO, "11-prune.twb": DEMO, "12-slice.twb": DEMO, "40-palettes.twb": DEMO,
    "13-sanitize.twb": FILTERING, "20-sheet-copy.twb": FILTERING, "21-dashboard-copy.twb": FILTERING,
    "22-scaffold.twb": FILTERING, "30-library.twb": LIB_TARGET,
}


def _new_findings(original: Path, produced: Path):
    def keys(path):
        df = validate_workbook(str(path))
        return set(zip(df["check"], df["datasource"], df["detail"]))

    return keys(produced) - keys(original)


def test_pack_is_made_listed_and_not_worse_than_its_inputs(tmp_path, capsys):
    pack = runpy.run_path(str(ROOT / "scripts" / "make_tableau_check_pack.py"))
    out = tmp_path / "pack"
    assert pack["main"]([str(out)]) == 0
    assert "0 failed" in capsys.readouterr().out

    for made, source in SOURCES.items():
        path = out / made
        assert path.is_file(), made
        if made != "13-sanitize.twb":
            # sanitize drops <thumbnails> on purpose; the published schema then wants one of its trailing
            # children ("Missing child element(s)" on /workbook). The pack lists it for Tableau to judge.
            assert new_schema_errors(str(source), str(path)) == [], made
        assert _new_findings(source, path) == set(), made
    assert (out / "14-sanitize-fake-data.twbx").is_file()
    assert (out / "41-Preferences_new.tps").read_text(encoding="utf-8").lstrip().startswith("<")
    TwbParser(str(out / "14-sanitize-fake-data.twbx"))

    listed = [row[0] for row in list(csv.reader(open(out / "results.csv", encoding="utf-8")))[1:]]
    assert len(listed) == len(set(listed))
    for name in listed:
        assert (out / name).is_file(), name
    assert {"10-rename.twb", "22-scaffold.twb", "30-library.twb", "41-Preferences_new.tps",
            "templates/2-template-on-csv.twbx", "templates/56-template-update.twbx"} <= set(listed)
    assert not any(name.endswith(".json") for name in listed)
    assert "OUT/10-rename.twb" in (out / "commands.txt").read_text(encoding="utf-8")

    assert pack["main"]([str(out)]) == 2                       # never writes into a folder with files
