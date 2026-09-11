from twbparser_py import extract_twb_from_twbx, twbx_list


def test_twbx_list_lists_members(zip_twbx_path):
    man = twbx_list(zip_twbx_path)
    assert not man.empty
    assert set(["name", "size_bytes", "modified", "type"]) <= set(man.columns)
    assert (man["type"] == "workbook").sum() == 1


def test_extract_twb_from_twbx_picks_largest_twb(zip_twbx_path):
    info = extract_twb_from_twbx(zip_twbx_path, extract_all=False)
    assert info["twb_path"].endswith(".twb")
    import os

    assert os.path.exists(info["twb_path"])
    assert not info["manifest"].empty
