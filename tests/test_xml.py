import os
import zipfile

from twbparser_py import extract_twb_from_twbx, twbx_list
from twbparser_py._xml import twbx_extract_files


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
