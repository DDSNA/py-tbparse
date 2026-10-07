"""Sanitize (share-safe export): what it removes, what it reports, and that it never touches the input."""

import csv
import io
import shutil
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from py_tbparse import TwbParser
from py_tbparse.cli import main
from py_tbparse.sanitize import CATEGORIES, SanitizeError, format_report, sanitize
from py_tbparse.verify import validate_workbook

PUBLIC = Path(__file__).parent / "fixtures" / "public"

SERVER, DB, SCHEMA, USER, SECRET = "db-prod.acme-corp.example", "AcmeSales", "acme_dw", "alice.smith", "hunter2-pass"
FOLDER = "C:\\Users\\alice.smith\\Documents\\Tableau"

TWB = f"""<?xml version='1.0' encoding='utf-8' ?>
<!-- built by alice.smith on ACME-LAPTOP -->
<workbook version='18.1' xmlns:user='http://www.tableausoftware.com/xml/user'
          _.fcp.WorkbookFingerprinting.true...author-id='author-1234'>
  <repository-location id='Sales' path='/t/acme/workbooks' revision='1.0' site='acme'/>
  <datasources>
    <datasource caption='Sales ({SERVER})' name='federated.0abc' inline='true'>
      <repository-location id='SalesDS' path='/t/acme/datasources'/>
      <connection class='federated'>
        <named-connections>
          <named-connection caption='{SERVER}' name='postgres.1xyz'>
            <connection authentication='username-password' class='postgres' dbname='{DB}' port='5432'
                        server='{SERVER}' username='{USER}' password='{SECRET}' schema='{SCHEMA}'
                        one-time-sql='SET ROLE acme_reader'>
              <initial-sql>SELECT 'acme secret'</initial-sql>
            </connection>
          </named-connection>
          <named-connection caption='data.csv' name='textscan.2'>
            <connection class='textscan' directory='{FOLDER}' filename='{FOLDER}\\data.csv' password='' server=''/>
          </named-connection>
        </named-connections>
        <relation connection='postgres.1xyz' name='Custom SQL Query' type='text'>SELECT * FROM acme_dw.customers WHERE ssn IS NOT NULL</relation>
        <relation connection='postgres.1xyz' name='orders' table='[{SCHEMA}].[orders]' type='table'/>
        <metadata-records>
          <metadata-record class='column'>
            <remote-name>Amount</remote-name><remote-type>5</remote-type><local-name>[Amount]</local-name>
            <parent-name>[Custom SQL Query]</parent-name><remote-alias>Amount</remote-alias><ordinal>0</ordinal>
            <local-type>real</local-type><aggregation>Sum</aggregation>
          </metadata-record>
          <metadata-record class='column'>
            <remote-name>Region</remote-name><remote-type>129</remote-type><local-name>[Region]</local-name>
            <parent-name>[Custom SQL Query]</parent-name><remote-alias>Region</remote-alias><ordinal>1</ordinal>
            <local-type>string</local-type><aggregation>Count</aggregation>
          </metadata-record>
        </metadata-records>
      </connection>
      <column datatype='real' name='[Amount]' role='measure' type='quantitative'>
        <desc><formatted-text><run>Ask alice.smith about this</run></formatted-text></desc>
      </column>
      <column datatype='string' name='[Region]' role='dimension' type='nominal'/>
      <column datatype='string' name='[Mine]' role='dimension' type='nominal'>
        <calculation class='tableau' formula='IF USERNAME() = "alice.smith" THEN "x" END'/>
      </column>
      <extract count='-1' enabled='true'><connection class='hyper' dbname='{FOLDER}\\Extract.hyper'/></extract>
      <user-filter column='[Region]' name='By user'><groupfilter function='member' user='alice.smith'/></user-filter>
    </datasource>
  </datasources>
  <worksheets>
    <worksheet name='Sheet 1'>
      <table><view><datasources><datasource caption='Sales ({SERVER})' name='federated.0abc'/></datasources></view></table>
      <annotations><annotation><formatted-text><run>note from alice.smith</run></formatted-text></annotation></annotations>
    </worksheet>
  </worksheets>
  <thumbnails><thumbnail height='192' name='Sheet 1' width='192'>iVBORw0KGgoAAAANSUhEUg==</thumbnail></thumbnails>
</workbook>
"""

# the user name also sits in a calculation's text, which is reported, not rewritten (see the leftovers test)
ORIGINALS = [SERVER, DB, SCHEMA, SECRET, "ACME-LAPTOP", "acme secret", "customers", "author-1234",
             "ssn", "acme_reader", "Extract.hyper", "iVBORw0KGgo"]


@pytest.fixture
def twb(tmp_path):
    path = tmp_path / "in.twb"
    path.write_text(TWB, encoding="utf-8")
    return path


@pytest.fixture
def twbx(tmp_path):
    path = tmp_path / "in.twbx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("in.twb", TWB)
        z.writestr("Data/data.csv", "a,b\n1,2\n")
        z.writestr("Data/Extracts/e.hyper", b"HYPER" * 10)
        z.writestr("Thumbnails/Sheet 1.png", b"\x89PNG-thumb")
        z.writestr("Image/logo.png", b"\x89PNG-logo")
    return path


def members(path):
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n) for n in z.namelist()}


def test_twb_loses_every_identifying_string(twb, tmp_path):
    out, report = tmp_path / "out.twb", {}
    assert sanitize(str(twb), str(out), report=report) == str(out)
    text = out.read_text(encoding="utf-8")
    for original in ORIGINALS:
        assert original not in text, original
    assert "customers" not in text and "ssn" not in text and "built by" not in text
    assert 'table="[schema].[orders]"' in text
    assert "Custom SQL Query" in text and "SELECT 1" in text


def test_counts_per_category(twb, tmp_path):
    report = {}
    sanitize(str(twb), str(tmp_path / "out.twb"), report=report)
    removed = report["removed"]
    assert set(removed) == set(CATEGORIES)
    assert removed["usernames"] == 1 and removed["passwords"] == 1
    assert removed["servers"] == 2    # server and port
    assert removed["databases"] == 1 and removed["schemas"] == 2   # the attribute and the table's qualifier
    assert removed["paths"] == 2      # the folder and the folder in the file name
    assert removed["custom_sql"] == 3  # the query, the initial SQL and the one-time SQL
    assert removed["extracts"] == 1
    assert removed["comments"] == 3   # XML comment, field description, annotation
    assert removed["user_filters"] == 1
    assert removed["user_specific"] == 1  # the author id (the filter's user went with the filter)
    assert removed["repository"] == 2 and removed["thumbnails"] == 1
    assert removed["captions"] >= 2
    assert report["custom_sql"] == ["Custom SQL Query (53 characters)"]
    assert "customers" not in str(report)


def test_leftovers_name_what_it_could_not_judge(twb, tmp_path):
    report = {}
    sanitize(str(twb), str(tmp_path / "out.twb"), report=report)
    kinds = {(i["kind"], i["where"]) for i in report["leftovers"]}
    assert any(k == "user function in a calculation" for k, _ in kinds)
    assert any(k == "table names" for k, _ in kinds)
    assert ("removed value still present", "calculation @formula") in kinds   # the user name inside a formula
    assert any(k == "kept as written" for k, _ in kinds)
    assert SCHEMA not in str(report["leftovers"])


def test_output_parses_and_the_input_is_untouched(twb, tmp_path):
    before = twb.read_bytes()
    out = tmp_path / "out.twb"
    sanitize(str(twb), str(out))
    assert twb.read_bytes() == before
    parsed = TwbParser(str(out))
    assert not parsed.calculated_fields.empty and "Custom SQL Query" in set(parsed.relations["name"])


def test_idempotent(twb, tmp_path):
    once, twice = tmp_path / "once.twb", tmp_path / "twice.twb"
    sanitize(str(twb), str(once))
    report = {}
    sanitize(str(once), str(twice), report=report)
    assert once.read_bytes() == twice.read_bytes()
    assert sum(report["removed"].values()) == 0


def test_idempotent_with_placeholders(twb, tmp_path):
    once, twice = tmp_path / "once.twb", tmp_path / "twice.twb"
    sanitize(str(twb), str(once), placeholders=True)
    text = once.read_text(encoding="utf-8")
    assert 'server="server.example.com"' in text and 'dbname="database"' in text and 'username="user"' in text
    report = {}
    sanitize(str(once), str(twice), placeholders=True, report=report)
    assert once.read_bytes() == twice.read_bytes() and sum(report["removed"].values()) == 0


def test_refuses_to_write_over_the_input(twb, tmp_path):
    before = twb.read_bytes()
    with pytest.raises(FileExistsError, match="input"):
        sanitize(str(twb), str(twb), overwrite=True)
    link = tmp_path / "link.twb"
    link.symlink_to(twb)
    with pytest.raises(FileExistsError, match="input"):
        sanitize(str(twb), str(link), overwrite=True)
    assert twb.read_bytes() == before


def test_refuses_existing_output_unless_asked(twb, tmp_path):
    out = tmp_path / "out.twb"
    out.write_text("keep me")
    with pytest.raises(FileExistsError):
        sanitize(str(twb), str(out))
    assert out.read_text() == "keep me"
    sanitize(str(twb), str(out), overwrite=True)
    assert out.read_text(encoding="utf-8").startswith("<?xml")


def test_output_format_must_match(twb, twbx, tmp_path):
    with pytest.raises(SanitizeError, match=r"\.twb file"):
        sanitize(str(twb), str(tmp_path / "o.twbx"))
    with pytest.raises(SanitizeError, match=r"\.twbx file"):
        sanitize(str(twbx), str(tmp_path / "o.twb"))
    with pytest.raises(SanitizeError, match="output is a"):
        sanitize(str(twb), str(tmp_path / "o.xml"))


def test_keep_leaves_a_category_alone(twb, tmp_path):
    out, report = tmp_path / "out.twb", {}
    sanitize(str(twb), str(out), keep=["comments", "custom_sql"], report=report)
    text = out.read_text(encoding="utf-8")
    assert "note from alice.smith" in text and "customers" in text
    assert report["removed"]["comments"] == 0 and report["removed"]["custom_sql"] == 0
    assert SERVER not in text
    with pytest.raises(SanitizeError, match="unknown category"):
        sanitize(str(twb), str(tmp_path / "o2.twb"), keep=["nope"])


def test_twbx_members(twbx, tmp_path):
    out, report = tmp_path / "out.twbx", {}
    sanitize(str(twbx), str(out), report=report)
    got = members(out)
    assert sorted(got) == ["Image/logo.png", "in.twb"]
    assert report["removed"]["extracts"] == 2          # the element and the .hyper
    assert report["removed"]["packaged_data"] == 1 and report["removed"]["thumbnails"] == 2
    assert any(i["kind"] == "packaged file" and ".png" in i["where"] for i in report["leftovers"])
    for name, data in got.items():
        for original in (SERVER, DB, SECRET, "HYPER", "acme secret", "thumb"):
            assert original.encode() not in data, (name, original)
    assert not TwbParser(str(out)).calculated_fields.empty


def test_twbx_idempotent_and_input_untouched(twbx, tmp_path):
    before = twbx.read_bytes()
    once, twice = tmp_path / "once.twbx", tmp_path / "twice.twbx"
    sanitize(str(twbx), str(once))
    sanitize(str(once), str(twice))
    assert members(once) == members(twice)
    assert twbx.read_bytes() == before


def test_fake_data_on_a_real_fixture(tmp_path):
    src = tmp_path / "filtering.twb"
    shutil.copy(PUBLIC / "filtering.twb", src)
    out, report = tmp_path / "fake.twbx", {}
    sanitize(str(src), str(out), fake_data=True, seed=7, fake_rows=5, report=report)
    synthetic = [e for e in report["fake_data"] if e["status"] == "synthetic"]
    assert synthetic and "_synthetic.csv" in synthetic[0]["file"]
    got = members(out)
    rows = list(csv.reader(io.StringIO(got[synthetic[0]["file"]].decode("utf-8"))))
    assert len(rows) == 6 and rows[0] and all(len(r) == len(rows[0]) for r in rows)
    # seeded: the same run gives the same file
    again, report2 = tmp_path / "fake2.twbx", {}
    sanitize(str(src), str(again), fake_data=True, seed=7, fake_rows=5, report=report2)
    assert members(again)[synthetic[0]["file"]] == got[synthetic[0]["file"]]
    # the output opens in the parser and does not break more than the input did
    new = {tuple(r) for r in validate_workbook(TwbParser(str(out))).itertuples(index=False)}
    old = {tuple(r) for r in validate_workbook(TwbParser(str(src))).itertuples(index=False)}
    assert len(new) <= len(old) + 2, new - old


def test_fake_data_needs_a_twbx_output(twb, tmp_path):
    with pytest.raises(SanitizeError, match=r"\.twbx"):
        sanitize(str(twb), str(tmp_path / "o.twb"), fake_data=True)


def test_report_text(twb, tmp_path):
    report = {}
    sanitize(str(twb), str(tmp_path / "out.twb"), report=report)
    text = format_report(report)
    assert "removed:" in text and "leftovers it could not judge" in text and "Custom SQL Query" in text
    for original in (SERVER, SECRET, USER):
        assert original not in text, original


def test_cli(twb, tmp_path, capsys):
    out = tmp_path / "out.twb"
    assert main(["sanitize", str(twb), str(out), "--report"]) == 0
    captured = capsys.readouterr()
    assert "removed:" in captured.out and out.exists()
    assert main(["sanitize", str(twb), str(out)]) == 2          # exists
    assert "refusing" in capsys.readouterr().err
    assert main(["sanitize", str(twb), str(twb), "--overwrite"]) == 2
    assert main(["sanitize", str(tmp_path / "missing.twb"), str(tmp_path / "x.twb")]) == 2
    assert main(["sanitize", str(twb), str(tmp_path / "y.twb"), "--keep", "nope"]) == 2
    assert main(["sanitize", str(twb), str(tmp_path / "z.twb"), "--placeholders"]) == 0
    with pytest.raises(SystemExit):
        main(["sanitize", "--help"])
    assert "--report" in capsys.readouterr().out


XML_BASE_TWB = """<?xml version='1.0' encoding='utf-8' ?>
<workbook version='18.1' xml:base='https://tableau.internal-corp.example' xmlns:user='http://www.tableausoftware.com/xml/user'>
  <datasources/>
</workbook>
"""


def test_xml_base_server_is_removed(tmp_path):
    src = tmp_path / "base.twb"
    src.write_text(XML_BASE_TWB, encoding="utf-8")
    out, report = tmp_path / "out.twb", {}
    sanitize(src, out, report=report)
    text = out.read_text(encoding="utf-8")
    assert "internal-corp" not in text
    assert report["removed"]["servers"] == 1
    assert not any("XML/1998" in item["where"] for item in report["leftovers"])
    sanitize(out, tmp_path / "again.twb", report=report)
    assert report["removed"]["servers"] == 0


def test_xml_base_placeholder_and_keep(tmp_path):
    src = tmp_path / "base.twb"
    src.write_text(XML_BASE_TWB, encoding="utf-8")
    sanitize(src, tmp_path / "ph.twb", placeholders=True)
    text = (tmp_path / "ph.twb").read_text(encoding="utf-8")
    assert "internal-corp" not in text and "https://example.invalid" in text
    report = {}
    sanitize(src, tmp_path / "kept.twb", keep=("servers",), report=report)
    assert "internal-corp" in (tmp_path / "kept.twb").read_text(encoding="utf-8")
    where = [item["where"] for item in report["leftovers"] if item["kind"] == "web address"]
    assert where == ["workbook @xml:base"]
