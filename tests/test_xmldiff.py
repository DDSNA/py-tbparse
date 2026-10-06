import io
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from py_tbparse import TwbParser, normalised_diff
from py_tbparse.cli import main
from py_tbparse.rename import build_renamed_workbook
from py_tbparse.xmldiff import canonical_lines, diff_line_count

FIXTURES = Path(__file__).parent / "fixtures"
CORPUS_FILES = sorted((Path(__file__).parent / "corpus" / "files").glob("*.twb"))

A = "<?xml version='1.0'?>\n<workbook version='18.1' a='1'>\n  <x  b='2' a='1'/>\n  <f>[A] + 1</f>\n</workbook>\n"


def test_attribute_order_quotes_whitespace_and_empty_elements_are_not_differences():
    b = ('<?xml version="1.0" encoding="utf-8"?><workbook a="1" version="18.1"><x a="1" b="2"></x>'
         "\n\n\n<f>[A] + 1</f></workbook>")
    assert normalised_diff(A, b) == ""
    assert canonical_lines(A) == canonical_lines(b)


def test_real_change_is_the_only_thing_shown():
    b = A.replace("[A] + 1", "[A] + 2").replace("b='2' a='1'", "a='1' b='2'")
    out = normalised_diff(A, b, name_a="before", name_b="after")
    lines = out.splitlines()
    assert lines[:2] == ["--- before", "+++ after"]
    assert [x for x in lines if x[:1] in "+-" and x[:3] not in ("+++", "---")] == [
        "-  <f>[A] + 1</f>", "+  <f>[A] + 2</f>"]
    assert diff_line_count(A, b) == 2


def test_attribute_value_change_and_text_whitespace_are_real():
    assert normalised_diff(A, A.replace("a='1'/>", "a='9'/>")) != ""
    assert normalised_diff(A, A.replace("[A] + 1", "[A]  + 1")) != ""


def test_escapes_are_canonical():
    one = "<r><x t='a&amp;b &lt; &quot;q&quot;'>1 &gt; 0 &amp; 2</x></r>"
    two = '<r><x t="a&amp;b &lt; &quot;q&quot;">1 &gt; 0 &amp; 2</x></r>'
    assert normalised_diff(one, two) == ""
    assert canonical_lines(one)[1] == '  <x t="a&amp;b &lt; &quot;q&quot;">1 &gt; 0 &amp; 2</x>'


def test_namespaces_and_xml_base():
    one = "<w xmlns:user='urn:u' xml:base='http://h' user:k='1' z='2'><c/></w>"
    two = '<w z="2" user:k="1" xml:base="http://h" xmlns:user="urn:u"><c></c></w>'
    assert normalised_diff(one, two) == ""
    assert canonical_lines(one)[0] == '<w xmlns:user="urn:u" z="2" xml:base="http://h" user:k="1">'


def test_comment_before_the_root_is_compared():
    assert normalised_diff("<!-- build 1 --><w/>", "<!-- build 2 --><w/>") != ""
    assert normalised_diff("<!-- build 1 -->\n<w/>", "<!-- build 1 --><w/>") == ""


def test_twb_and_twbx_paths(tmp_path, wenjie_path, zip_twbx_path):
    assert normalised_diff(wenjie_path, wenjie_path) == ""
    assert normalised_diff(zip_twbx_path, zip_twbx_path) == ""
    a = tmp_path / "a.twb"
    a.write_text(A, encoding="utf-8")
    out = normalised_diff(a, wenjie_path)
    assert out.startswith("--- a.twb\n+++ test_for_wenjie.twb\n")


def test_twbx_compares_the_workbook_member_only(tmp_path):
    def pack(path, twb, other):
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("w.twb", twb)
            z.writestr("Data/x.csv", other)
        return path
    a = pack(tmp_path / "a.twbx", A, "1")
    b = pack(tmp_path / "b.twbx", A.replace("[A] + 1", "[A] + 3"), "2")
    c = pack(tmp_path / "c.twbx", A, "different data")
    assert normalised_diff(a, c) == ""
    assert diff_line_count(a, b) == 2


def test_missing_file_and_bad_xml_raise(tmp_path):
    with pytest.raises(FileNotFoundError):
        normalised_diff(tmp_path / "nope.twb", A)
    with pytest.raises(Exception):
        normalised_diff("<a><b></a>", A)


def test_no_entity_expansion(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("TOPSECRET", encoding="utf-8")
    xml = f'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY e SYSTEM "{secret.as_uri()}">]><r>&e;</r>'
    assert "TOPSECRET" not in "".join(canonical_lines(xml))


def test_save_with_no_edits_is_not_a_difference(tmp_path, wenjie_path, zip_twbx_path):
    for src, ext in ((wenjie_path, "twb"), (zip_twbx_path, "twbx")):
        saved = tmp_path / f"saved.{ext}"
        saved.write_bytes(build_renamed_workbook(TwbParser(src), pd.DataFrame()))
        assert normalised_diff(src, saved) == ""


@pytest.mark.skipif(not CORPUS_FILES, reason="corpus not fetched: python scripts/fetch_corpus.py")
def test_corpus_save_with_no_edits_has_no_normalised_difference():
    for path in CORPUS_FILES:
        saved = build_renamed_workbook(TwbParser(str(path)), pd.DataFrame())
        assert diff_line_count(path, saved) == 0, path.name


def test_cli_exit_codes(tmp_path, capsys, wenjie_path):
    a = tmp_path / "a.twb"
    b = tmp_path / "b.twb"
    a.write_text(A, encoding="utf-8")
    b.write_text(A.replace("'18.1'", '"18.1"'), encoding="utf-8")
    assert main(["diff-xml", str(a), str(b)]) == 0
    assert capsys.readouterr().out == ""
    b.write_text(A.replace("[A] + 1", "[A] + 2"), encoding="utf-8")
    assert main(["diff-xml", str(a), str(b)]) == 1
    out = capsys.readouterr().out
    assert "-  <f>[A] + 1</f>" in out and "+  <f>[A] + 2</f>" in out
    assert main(["diff-xml", str(a), str(tmp_path / "missing.twb")]) == 2
    assert "error:" in capsys.readouterr().err


def test_cli_output_file_and_refusal(tmp_path, capsys):
    a = tmp_path / "a.twb"
    b = tmp_path / "b.twb"
    a.write_text(A, encoding="utf-8")
    b.write_text(A.replace("[A] + 1", "[A] + 2"), encoding="utf-8")
    out = tmp_path / "d.diff"
    assert main(["diff-xml", str(a), str(b), "-o", str(out), "-U", "0"]) == 1
    assert "+  <f>[A] + 2</f>" in out.read_text(encoding="utf-8")
    assert capsys.readouterr().out == ""
    assert main(["diff-xml", str(a), str(b), "-o", str(a)]) == 2
    assert a.read_text(encoding="utf-8") == A


def test_cli_help_mentions_exit_codes(capsys):
    with pytest.raises(SystemExit):
        main(["diff-xml", "--help"])
    assert "no differences" in " ".join(capsys.readouterr().out.split())
