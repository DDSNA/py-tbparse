"""The small Markdown renderer (py_tbparse/docgen.py) and `template show --markdown`."""

import json
import re
import shutil
from pathlib import Path

import pytest

from py_tbparse import docgen
from py_tbparse.cli import main
from py_tbparse.docgen import Code, code_block, escape_cell, heading, inline_code, md_table, render, template_markdown
from py_tbparse.templates import MANIFEST_NAME, load_template, make_template

PUBLIC = Path(__file__).parent / "fixtures" / "public"


def cells(line):
    """Split a table row on its unescaped pipes."""
    return re.split(r"(?<!\\)\|", line.strip())[1:-1]


# --- the renderer ------------------------------------------------------------

def test_escape_cell():
    assert escape_cell("a|b") == "a\\|b"
    assert escape_cell("line1\nline2\r\nline3") == "line1<br>line2<br>line3"
    assert escape_cell("<script>") == "&lt;script&gt;"
    assert escape_cell("a*b_c") == "a\\*b\\_c"
    assert escape_cell("back\\slash") == "back\\\\slash"
    assert escape_cell(None) == "" and escape_cell(3) == "3" and escape_cell(True) == "yes"
    assert escape_cell("Привет 日本語") == "Привет 日本語"


def test_inline_code():
    assert inline_code("x") == "`x`"
    assert inline_code("a`b") == "``a`b``"
    assert inline_code("`edge`") == "`` `edge` ``"
    assert inline_code("a|b") == "`a\\|b`"
    assert inline_code("two\nlines") == "`two lines`"


def test_heading_and_code_block():
    assert heading(2, "Fields") == "## Fields"
    with pytest.raises(ValueError):
        heading(0, "x")
    assert code_block("a = 1", "python") == "```python\na = 1\n```"
    assert code_block("has ``` inside").startswith("````\n")        # a longer fence than any run inside


def test_md_table_is_aligned_in_columns_and_escaped():
    text = md_table(["Name", "Note"], [["a|b", "x\ny"], [Code("c`d"), None]])
    lines = text.splitlines()
    assert lines[0] == "| Name | Note |"
    assert lines[1] == "| --- | --- |"
    assert all(len(cells(l)) == 2 for l in lines)
    assert "a\\|b" in lines[2] and "x<br>y" in lines[2]
    assert "``c`d``" in lines[3]


def test_md_table_empty_has_a_header_only():
    assert md_table(["A"], []).splitlines() == ["| A |", "| --- |"]


def test_render_joins_blocks_with_a_blank_line_and_ends_with_one_newline():
    assert render("# T", "", "para", None, "x") == "# T\n\npara\n\nx\n"


# --- template show --markdown -----------------------------------------------

@pytest.fixture
def cache_template(tmp_path):
    shutil.copy(PUBLIC / "Cache.twbx", tmp_path / "Cache.twbx")
    return make_template(str(tmp_path / "Cache.twbx"), name="Quota | model", description="Sales quota.\nSecond line.")


def test_template_markdown_content(cache_template):
    t = load_template(cache_template)
    md = template_markdown(t)
    assert md.startswith("# Quota \\| model\n")
    assert "Sales quota." in md and "Second line." in md
    assert t.id in md and "revision" in md.lower()
    for section in ("## Fields", "## Parameters", "## Connections", "## Worksheets", "## Dashboards"):
        assert section in md, section
    for p in t.parameters().itertuples():
        assert p.parameter in md
    assert "Base Salary" in md and "50000" in md
    assert md.endswith("\n") and not md.endswith("\n\n")


def test_template_markdown_is_deterministic(cache_template):
    t = load_template(cache_template)
    assert template_markdown(t) == template_markdown(load_template(cache_template))


def test_template_markdown_tables_are_well_formed(cache_template):
    md = template_markdown(load_template(cache_template))
    block = []
    for line in md.splitlines() + [""]:
        if line.startswith("|"):
            block.append(line)
            continue
        if block:
            counts = {len(cells(l)) for l in block}
            assert len(counts) == 1, block
            block = []


def test_template_markdown_shows_required_and_optional_fields(tmp_path):
    shutil.copy(PUBLIC / "filtering.twb", tmp_path / "filtering.twb")
    t = load_template(make_template(str(tmp_path / "filtering.twb")))
    md = template_markdown(t)
    assert "Required fields" in md and "Optional fields" in md
    req = [f for f in t.manifest["datasources"][0]["fields"] if f["required"]]
    assert req and all(f["name"].strip("[]") in md for f in req)
    sheet = req[0]["used_by"][0]
    assert sheet in md


def test_template_markdown_never_prints_credentials(tmp_path):
    path = make_template(str(shutil.copy(PUBLIC / "filtering.twb", tmp_path / "f.twb")))
    t = load_template(path)
    t.manifest["datasources"][0]["connections"][0].update(username="alice", password="hunter2")
    md = template_markdown(t)
    assert "alice" not in md and "hunter2" not in md
    assert "b5dpm3ihhu.database.windows.net" in md       # where the data came from is not a secret


def test_template_markdown_lists_tokens_when_the_manifest_has_them(cache_template):
    t = load_template(cache_template)
    assert "## Tokens" not in template_markdown(t)       # none declared: no section
    t.manifest["tokens"] = [{"name": "customer", "default": "Your company",
                             "where": [{"kind": "title", "object": "Sales"}]}]
    md = template_markdown(t)
    assert "## Tokens" in md and "customer" in md and "Your company" in md and "title" in md


def test_template_markdown_non_latin_and_pipes(tmp_path):
    shutil.copy(PUBLIC / "Cache.twbx", tmp_path / "Cache.twbx")
    t = load_template(make_template(str(tmp_path / "Cache.twbx"), name="Продажи | 売上"))
    md = template_markdown(t)
    assert md.startswith("# Продажи \\| 売上")


def test_dashboard_sheets_listed_for_named_zones(tmp_path):
    # filtering.twb's zones are `<zone name='Sheet 1'>`, with no @worksheet (issue #29)
    t = load_template(make_template(str(shutil.copy(PUBLIC / "filtering.twb", tmp_path / "f.twb"))))
    md = template_markdown(t)
    row = next(l for l in md.splitlines() if l.startswith("| setTest"))
    assert cells(row)[1].strip() == "Sheet 1; Sheet 2"


def test_connections_use_an_allowlist(tmp_path):
    t = load_template(make_template(str(shutil.copy(PUBLIC / "filtering.twb", tmp_path / "f.twb"))))
    t.manifest["datasources"][0]["connections"] = [{
        "class": "sqlserver", "server": "https://u:pw@host.example/", "dbname": "sales",
        "token": "TOK-123", "oauth-access-token": "OAUTH-456", "Password": "hunter2", "secret": "S3CR3T",
        "filename": "C:\\Users\\alice\\data.csv", "directory": "/home/alice/data"}]
    md = template_markdown(t)
    for secret in ("TOK-123", "OAUTH-456", "hunter2", "S3CR3T", "u:pw", "alice", "C:\\"):
        assert secret not in md, secret
    assert "class=sqlserver" in md and "dbname=sales" in md and "host.example" in md and "filename=data.csv" in md
    t.manifest["datasources"][0]["connections"] = [{"class": "sqlserver", "server": "u:pw@host", "dbname": "x;password=zz"}]
    md = template_markdown(t)
    assert "pw" not in md.replace("password", "") and "zz" not in md


@pytest.mark.parametrize("text", [
    "```\nnot closed", "~~~\nnot closed", "# Heading", "- item", "+ item", "1. item", "---", "===",
    "[x](http://a.example)", "![i](http://a.example/p.png)", "&lt;b&gt;", "`code`", "> quote",
])
def test_escape_cell_adversarial(text):
    out = escape_cell(text)
    for line in out.split("<br>"):
        assert not re.match(r"\s*(```|~~~|#|[-+*>]\s|\d+[.)]\s|-{3}|={3})", line), (text, out)
    assert not re.search(r"(?<!\\)\[", out) and not re.search(r"(?<!\\)`", out)     # no link or code span can open
    assert "&lt;" not in out.replace("&amp;lt;", "")            # an entity stays literal text


def test_escape_cell_line_start_markers():
    assert escape_cell("1. item") == "1\\. item" and escape_cell("2) item") == "2\\) item"
    assert escape_cell("# H") == "\\# H" and escape_cell("a\n- b") == "a<br>\\- b"
    assert escape_cell("R&D 2024-25 (v1)") == "R&amp;D 2024-25 (v1)"


def test_free_text_cannot_open_a_fence_or_a_heading(tmp_path):
    t = load_template(make_template(str(shutil.copy(PUBLIC / "Cache.twbx", tmp_path / "c.twbx")), name="Q"))
    t.manifest["description"] = "intro\n```\n# Heading\n- item\n[x](http://evil.example)"
    md = template_markdown(t)
    for line in md.splitlines():
        assert not line.startswith(("```", "# Heading", "- item")), line
    assert "](http" not in md.replace("\\](http", "")


def test_long_descriptions_and_allowed_values_are_capped(tmp_path):
    t = load_template(make_template(str(shutil.copy(PUBLIC / "Cache.twbx", tmp_path / "c.twbx")), name="Q"))
    p = t.manifest["parameters"][0]
    p["description"] = "d" * 5000
    p["allowed"] = ["v" * 5000, "short"]
    md = template_markdown(t)
    assert "d" * 400 not in md and "v" * 400 not in md and "short" in md
    assert "truncated" in md


def test_cli_show_markdown(cache_template, tmp_path, capsys):
    assert main(["template", "show", cache_template, "--markdown"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("# Quota") and "## Fields" in out
    target = tmp_path / "page.md"
    assert main(["template", "show", cache_template, "--markdown", "-o", str(target)]) == 0
    assert target.read_text(encoding="utf-8") == out
    capsys.readouterr()


def test_cli_show_without_markdown_is_unchanged(cache_template, capsys):
    assert main(["template", "show", cache_template]) == 0
    out = capsys.readouterr().out
    assert "datasource" in out and "# Quota" not in out


def test_cli_show_output_without_markdown_is_refused(cache_template, tmp_path, capsys):
    with pytest.raises(SystemExit):
        main(["template", "show", cache_template, "-o", str(tmp_path / "x.md")])
    capsys.readouterr()
