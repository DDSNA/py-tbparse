"""scripts/layout_census.py on small hand-made workbooks (exact numbers), and its limits (WP0 of #84)."""

import importlib.util
import sys
import zipfile
from pathlib import Path

import pytest
from lxml import etree

sys.path.insert(0, str(Path(__file__).parent))

from cards_fixtures import cards_workbook

_spec = importlib.util.spec_from_file_location("layout_census", Path(__file__).parent.parent / "scripts" / "layout_census.py")
lc = importlib.util.module_from_spec(_spec)
sys.modules["layout_census"] = lc
_spec.loader.exec_module(lc)

OVERLAP = """<?xml version='1.0' encoding='utf-8' ?>
<workbook><dashboards><dashboard name='D'>
  <size minwidth='1000' minheight='800' maxwidth='1000' maxheight='800'/>
  <zones>
    <zone id='1' type-v2='layout-basic' x='0' y='0' w='100000' h='100000'>
      <zone id='2' name='A' x='0' y='0' w='40000' h='40000'/>
      <zone id='3' name='B' x='20000' y='20000' w='40000' h='40000'/>
      <zone id='4' type-v2='text' is-floating='true' x='5000' y='5000' w='5000' h='5000'/>
      <zone id='5' type-v2='layout-basic' x='0' y='60000' w='100000' h='40000'>
        <zone id='6' name='E' x='0' y='60000' w='50000' h='40000'/>
        <zone id='7' name='F' x='40000' y='60000' w='50000' h='40000'/>
      </zone>
      <zone id='8' type-v2='layout-flow' x='60000' y='0' w='40000' h='20000'>
        <zone id='9' name='G' x='60000' y='0' w='50000' h='20000'/>
      </zone>
    </zone>
  </zones>
</dashboard></dashboards></workbook>
"""


def dashboards(xml: str) -> dict:
    root = etree.fromstring(xml.encode())
    return {db.get("name"): lc.analyse_dashboard(db) for db in root.xpath("//dashboard")}


def test_the_cards_fixture_has_no_overlap_and_the_numbers_are_exact():
    d = dashboards(cards_workbook(many_zones=60))
    mixed = d["Mixed 'one'"]          # the phone layout's zone is not counted
    assert (mixed["zones"], mixed["containers"], mixed["leaves"], mixed["placed"]) == (8, 1, 7, 7)
    assert mixed["max_depth"] == 2 and (mixed["max_x"], mixed["max_y"]) == (100000, 100000)
    assert not mixed.get("overlap_pairs") and not mixed.get("leaves_under_name_width")
    assert mixed["_fixed"] == (1200, 800)
    empty = d["No positions"]
    assert (empty["zones"], empty["containers"], empty["leaves"], empty["placed"]) == (1, 1, 0, 0)
    many = d["Many zones"]
    assert (many["leaves"], many["placed"], many["leaves_under_name_width"]) == (60, 60, 60)
    assert not many.get("overlap_pairs") and not many.get("leaves_under_5px")
    assert (many["max_x"], many["max_y"]) == (91590, 26590)


def test_overlap_floating_nesting_and_odd_sizes_are_counted_exactly():
    d = dashboards(OVERLAP)["D"]
    assert (d["zones"], d["containers"], d["leaves"], d["placed"]) == (9, 3, 6, 6)
    assert d["overlap_pairs"] == 3
    assert (d["overlap_floating_attr"], d["overlap_basic_container"], d["overlap_neither"]) == (1, 1, 1)
    assert (d.get("overlap_identical", 0), d["overlap_nested"], d["overlap_partial"]) == (0, 1, 2)
    assert d["overlap_with_text_or_image"] == 1
    assert (d["floating_attr"], d["in_basic"], d["max_depth"]) == (1, 2, 3)
    assert d["extent_past_grid"] == 1 and d["outside_parent"] == 1 and d["max_x"] == 110000
    assert d["leaves_under_name_width"] == 1 and not d.get("leaves_under_5px")


def test_the_overlap_threshold_is_a_share_of_the_smaller_zone():
    root = etree.fromstring(OVERLAP.encode())
    db = root.xpath("//dashboard")[0]
    assert lc.analyse_dashboard(db, min_overlap=0.3)["overlap_pairs"] == 1    # only the contained floating zone
    assert lc.analyse_dashboard(db, min_overlap=0.2)["overlap_pairs"] == 2    # A-B is 25 percent, E-F exactly 20 (not more)


def test_missing_and_odd_sizes():
    xml = ("<workbook><dashboards><dashboard name='X'><zones>"
           "<zone id='1' name='a' x='0' y='0' w='0' h='10'/>"
           "<zone id='2' name='b' x='-5' y='0' w='10' h='10'/>"
           "<zone id='3' name='c' w='10' h='10'/>"
           "<zone id='4' name='d' x='200000' y='0' w='10' h='10'/>"
           "</zones></dashboard></dashboards></workbook>")
    d = dashboards(xml)["X"]
    assert (d["missing_pos"], d["nonpositive_size"], d["negative_pos"], d["pos_past_grid"], d["placed"]) == (1, 1, 1, 1, 2)


def test_the_summary_prints_counts_only():
    root = etree.fromstring(OVERLAP.encode())
    text = lc.summarise([lc.analyse_dashboard(root.xpath("//dashboard")[0])],
                        {"read": 1, "too_big": 0, "failed": 0, "no_dashboards": 0, "min_overlap": 0.01})
    assert "| dashboards | 1 |" in text and "| any (total) | 3 | 1 | 100.0% |" in text
    assert "'D'" not in text and "Sheet" not in text


def _files(tmp_path, n=3):
    paths = []
    for i in range(n):
        p = tmp_path / f"w{i}.twb"
        p.write_text(OVERLAP, encoding="utf-8")
        paths.append(p)
    return paths


def test_the_cap_the_stop_file_and_the_size_limit(tmp_path):
    files = _files(tmp_path)
    dashes, meta = lc.run(files, cap=2, delay=0)
    assert len(dashes) == 2 and meta["read"] == 2 and "cap" in meta["stopped"]
    stop = tmp_path / "stop"
    stop.write_text("x")
    dashes, meta = lc.run(files, stop_file=stop, delay=0)
    assert dashes == [] and meta["stopped"] == "stop file"
    dashes, meta = lc.run(files, max_mb=0, delay=0)
    assert dashes == [] and meta["too_big"] == 3


def test_a_twbx_is_read_and_a_broken_file_is_counted_not_fatal(tmp_path):
    box = tmp_path / "w.twbx"
    with zipfile.ZipFile(box, "w") as z:
        z.writestr("inner.twb", OVERLAP)
    bad = tmp_path / "bad.twb"
    bad.write_bytes(b"\x00\x01 not xml")
    dashes, meta = lc.run([box, bad], delay=0)
    assert len(dashes) == 1 and meta["read"] + meta["failed"] == 2


CORPUS = Path(__file__).parent / "corpus" / "files"
FILES = sorted(CORPUS.glob("*.tw*")) if CORPUS.is_dir() else []


@pytest.mark.skipif(not FILES, reason="corpus not fetched: python scripts/fetch_corpus.py")
def test_corpus_totals_as_the_census_found_them():
    dashes, meta = lc.run(FILES, delay=0)
    assert (meta["read"], meta["failed"], meta["too_big"], len(dashes)) == (200, 0, 0, 135)
    assert sum(d.get("leaves", 0) for d in dashes) == 821
    assert max(d.get("leaves", 0) for d in dashes) == 40
    assert sum(d.get("overlap_pairs", 0) for d in dashes) == 255
    assert sum(d.get("floating_attr", 0) for d in dashes) == 0
