"""`docs` / `dictionary`: the workbook data dictionary (`docgen.workbook_markdown`)."""

import os
from pathlib import Path

import pytest

from py_tbparse import TwbParser, make_template, template_markdown, load_template, workbook_markdown
from py_tbparse.cli import main
from test_audit import workbook

PUBLIC = Path(__file__).parent / "fixtures" / "public"
SNAPSHOTS = Path(__file__).parent / "fixtures" / "snapshots"


def table_problems(md: str) -> list[str]:
    """Rows of a GitHub table whose count of unescaped pipes differs from the header's."""
    problems, width = [], None
    for n, line in enumerate(md.split("\n"), 1):
        if not line.startswith("|"):
            width = None
            continue
        count, i = 0, 0
        while i < len(line):
            if line[i] == "\\":
                i += 2
                continue
            count += line[i] == "|"
            i += 1
        if width is None:
            width = count
        elif count != width:
            problems.append(f"line {n}: {count} pipes, the table has {width}")
    return problems


def test_snapshot_of_one_fixture():
    page = workbook_markdown(TwbParser(str(PUBLIC / "filtering.twb")))
    snap = SNAPSHOTS / "filtering.dictionary.md"
    if os.environ.get("UPDATE_SNAPSHOTS"):
        snap.parent.mkdir(exist_ok=True)
        snap.write_text(page, encoding="utf-8")
    assert page == snap.read_text(encoding="utf-8"), "run with UPDATE_SNAPSHOTS=1 if the change is wanted"


@pytest.mark.parametrize("path", sorted(PUBLIC.glob("*.tw*")), ids=lambda p: p.name)
def test_every_public_fixture_renders_valid_tables(path):
    page = workbook_markdown(TwbParser(str(path)), graph=True)
    assert page.startswith("# Data dictionary: ") and page.endswith("\n") and not page.endswith("\n\n")
    assert table_problems(page) == []
    assert page == workbook_markdown(TwbParser(str(path)), graph=True)         # deterministic


def test_sections_and_where_used(tmp_path):
    path = workbook(tmp_path, calcs=[("[Calculation_1]", "Margin", "[Sales] - [Profit]")],
                    sheets={"Sheet 1": ["[Calculation_1]"], "Loose": ["[Sales]"]}, hidden=["Loose"],
                    params=[("[Parameter 1]", "Top N")])
    page = workbook_markdown(TwbParser(path))
    for heading in ("# Data dictionary: wb", "## Datasources", "### Datasource: Orders", "#### Fields (", "## Parameters",
                    "## Worksheets (where fields are used)", "## Dashboards"):
        assert heading in page
    assert "| `[Calculation_1]`" not in page and "| `Calculation_1` | Margin |" in page
    assert "Sheets: Sheet 1 / Dashboards: Dash" in page                       # the calculation is used by Sheet 1
    assert "| Loose | yes |  | Sales |" in page                                # hidden, on no dashboard
    assert "| Sheet 1 |  | Dash | Margin |" in page
    assert "| Dash | Sheet 1 |" in page
    assert "| Top N | integer | `10` | range | min 1; max 50 | (nothing) |" in page
    assert table_problems(page) == []


def test_long_formula_is_cut_in_the_table_and_complete_in_a_block(tmp_path):
    long = "IF [Sales] > 0 THEN " + " + ".join(f"[Profit] * {i}" for i in range(60)) + " END"
    path = workbook(tmp_path, calcs=[("[Calculation_1]", "Long | one", long)])
    page = workbook_markdown(TwbParser(path))
    assert f"truncated, {len(long)} characters" in page
    assert "<details>" in page and "</details>" in page
    block = page[page.index("<details>"):page.index("</details>")]
    assert long in block and "```" in block
    row = next(line for line in page.split("\n") if line.startswith("| `Calculation_1`"))
    assert long not in row and "Long \\| one" in row
    assert table_problems(page) == []


def test_pipes_newlines_non_latin_and_markup_are_safe(tmp_path):
    path = workbook(tmp_path, calcs=[("[Calculation_1]", "销售额 <b>x</b> # y", "IF [Sales] > 0 THEN 'a|b'\nELSE 'c' END")])
    page = workbook_markdown(TwbParser(path))
    assert "销售额" in page and "<b>" not in page and "&lt;b&gt;" in page
    assert "a\\|b" in page
    row = next(line for line in page.split("\n") if line.startswith("| `Calculation_1`"))
    assert "\n" not in row and table_problems(page) == []


def test_secrets_and_local_paths_are_not_printed(tmp_path):
    conn = ("<connection class='sqlserver' server='db.example.com' dbname='Sales' username='alice' password='s3cret-pw' "
            "directory='C:\\Users\\alice\\Documents' filename='C:\\Users\\alice\\Documents\\data.csv'>"
            "<relation name='Custom SQL Query' type='text'>SELECT * FROM t WHERE token=abc123secret</relation></connection>")
    path = workbook(tmp_path, conn=conn, name="C-Users-alice.twb")
    page = workbook_markdown(TwbParser(path), graph=True)
    for secret in ("alice", "s3cret-pw", "abc123secret", "Documents", "SELECT"):
        assert secret not in page.replace("C-Users-alice", ""), secret
    assert "db.example.com" in page and "data.csv" in page and "custom SQL" in page


def test_twbx_shows_the_archive_name_only(tmp_path):
    page = workbook_markdown(TwbParser(str(PUBLIC / "Cache.twbx")))
    assert "| File | `Cache.twbx` |" in page and "/" not in page.split("\n")[4]


def test_shares_connection_wording_with_the_template_page(tmp_path):
    src = tmp_path / "filtering.twb"
    src.write_bytes((PUBLIC / "filtering.twb").read_bytes())
    template = load_template(make_template(str(src)))
    conn = "class=sqlserver; server=b5dpm3ihhu.database.windows.net; dbname=EmptyDB; authentication=sqlserver"
    assert conn in workbook_markdown(TwbParser(str(src)))
    assert conn in template_markdown(template)


def test_graph_block_is_optional():
    parser = TwbParser(str(PUBLIC / "datasource_test.twb"))
    assert "## Relationship graph" not in workbook_markdown(parser)
    assert "```dot\ndigraph" in workbook_markdown(parser, graph=True)


def test_cli_docs_and_dictionary(tmp_path, capsys):
    path = workbook(tmp_path)
    assert main(["docs", path]) == 0
    printed = capsys.readouterr().out
    assert printed.startswith("# Data dictionary: wb")
    out = tmp_path / "dict.md"
    assert main(["dictionary", path, "-o", str(out), "--graph"]) == 0
    assert out.read_text(encoding="utf-8").startswith("# Data dictionary: wb") and "## Relationship graph" in out.read_text(encoding="utf-8")
    assert printed.rstrip("\n") == workbook_markdown(TwbParser(path)).rstrip("\n")


def test_cli_docs_errors(tmp_path, capsys):
    path = workbook(tmp_path)
    assert main(["docs", path, "-o", path]) == 2
    assert Path(path).read_text(encoding="utf-8").startswith("<?xml")
    assert main(["docs", str(tmp_path / "missing.twb")]) == 2
    assert "error:" in capsys.readouterr().err
