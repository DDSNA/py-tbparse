import os
import zipfile

from lxml import etree

from py_tbparse import extract_twb_from_twbx, twbx_list
from py_tbparse._xml import twbx_extract_files


def test_twbx_list_lists_members(zip_twbx_path):
    man = twbx_list(zip_twbx_path)
    assert not man.empty
    assert set(["name", "size_bytes", "modified", "type"]) <= set(man.columns)
    assert (man["type"] == "workbook").sum() == 1


def test_extract_twb_from_twbx_picks_largest_twb(zip_twbx_path):
    info = extract_twb_from_twbx(zip_twbx_path, extract_all=False)
    assert info["twb_path"].endswith(".twb")
    assert os.path.exists(info["twb_path"])
    assert not info["manifest"].empty


def test_extract_twb_from_twbx_path_matches_traversal_sanitized_member(tmp_path):
    # zipfile.extract() strips '..'/absolute segments out of a member name
    # before writing, so os.path.join(extract_dir, name) can point
    # somewhere the file was never actually written -- extract_twb_from_twbx
    # must report wherever zipfile really put it, not a recomputed guess.
    twbx = tmp_path / "traversal.twbx"
    with zipfile.ZipFile(twbx, "w") as zf:
        zf.writestr("../../evil.twb", "<workbook/>")

    extract_dir = tmp_path / "out"
    info = extract_twb_from_twbx(str(twbx), extract_dir=str(extract_dir), extract_all=False)

    assert os.path.exists(info["twb_path"]), (
        f"reported twb_path does not exist: {info['twb_path']}"
    )
    # The sanitized destination must stay inside extract_dir.
    assert os.path.commonpath([os.path.abspath(info["twb_path"]), str(extract_dir)]) == str(
        extract_dir
    )


def test_twbx_extract_files_path_matches_traversal_sanitized_member(tmp_path):
    twbx = tmp_path / "traversal.twbx"
    with zipfile.ZipFile(twbx, "w") as zf:
        zf.writestr("../../sneaky.csv", "a,b\n1,2\n")

    exdir = tmp_path / "out"
    result = twbx_extract_files(str(twbx), exdir=str(exdir))

    assert len(result) == 1
    out_path = result.iloc[0]["out_path"]
    assert os.path.exists(out_path), f"reported out_path does not exist: {out_path}"
    assert os.path.commonpath([os.path.abspath(out_path), str(exdir)]) == str(exdir)


# --- one hardened parser (#122) ----------------------------------------------

import re
from pathlib import Path

from py_tbparse import TwbParser

_SECRET = "TOP-SECRET-FILE-CONTENT"


def _entity_twb(secret_path: Path) -> str:
    return (
        '<?xml version="1.0"?>\n'
        f'<!DOCTYPE workbook [<!ENTITY x SYSTEM "{secret_path.as_uri()}">]>\n'
        '<workbook><datasources><datasource name="d"><note>&x;</note></datasource></datasources></workbook>'
    )


def test_a_file_entity_is_not_resolved_in_a_twb(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text(_SECRET)
    twb = tmp_path / "evil.twb"
    twb.write_text(_entity_twb(secret))
    p = TwbParser(str(twb))
    assert _SECRET not in etree.tostring(p.xml_doc, encoding="unicode")


def test_a_file_entity_is_not_resolved_in_a_twbx(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text(_SECRET)
    twbx = tmp_path / "evil.twbx"
    with zipfile.ZipFile(twbx, "w") as zf:
        zf.writestr("w.twb", _entity_twb(secret))
    p = TwbParser(str(twbx))
    assert _SECRET not in etree.tostring(p.xml_doc, encoding="unicode")


def test_the_shared_parser_does_not_resolve_or_fetch(tmp_path):
    from py_tbparse._xml import parse_bytes, xml_parser

    assert xml_parser() is not xml_parser()
    secret = tmp_path / "secret.txt"
    secret.write_text(_SECRET)
    root = parse_bytes(f'<!DOCTYPE a [<!ENTITY x SYSTEM "{secret.as_uri()}">]><a>&x;</a>'.encode())
    assert _SECRET not in etree.tostring(root, encoding="unicode")


def test_no_bare_etree_parse_outside_xml_py():
    """Every parse goes through py_tbparse/_xml.py (parse_file, parse_bytes, xml_parser)."""
    bare = re.compile(r"\betree\.(parse|fromstring|XML)\(|\betree\.XMLParser\(|\biterparse\(")
    offenders = []
    for f in sorted(Path(__file__).parent.parent.joinpath("py_tbparse").glob("*.py")):
        if f.name == "_xml.py":
            continue
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if bare.search(line):
                offenders.append(f"{f.name}:{n}: {line.strip()}")
    assert not offenders, "use py_tbparse._xml.parse_file/parse_bytes instead:\n" + "\n".join(offenders)
