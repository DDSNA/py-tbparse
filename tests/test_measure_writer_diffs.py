import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import measure_writer_diffs as m  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "library" / "source.twb"


def test_script_measures_a_fixture_and_prints_only_aggregates(tmp_path, capsys):
    out = tmp_path / "out.json"
    code = m.main(["--files", str(FIXTURE), "--writers", "roundtrip,rename,style-import,library-import",
                   "--workdir", str(tmp_path), "--json", str(out)])
    assert code == 0
    shown = capsys.readouterr().out
    assert FIXTURE.name not in shown and "Revenue" not in shown
    data = json.loads(out.read_text())["fixtures"]
    assert data["files"] == 1
    writers = data["writers"]
    assert writers["roundtrip"]["ran"] == 1
    assert writers["roundtrip"]["norm_lines"]["max"] == 0           # formatting only, no content change
    assert writers["roundtrip"]["raw_lines"]["max"] > 0             # but a plain diff shows churn
    assert writers["rename"]["norm_lines"]["max"] > 0               # a real edit is counted
    assert writers["style-import"]["ran"] == 1 and writers["library-import"]["ran"] == 1
    assert not list(tmp_path.glob("w-*"))                           # scratch folders are removed


def test_unknown_writer_is_refused(capsys):
    with pytest.raises(SystemExit):
        m.main(["--files", str(FIXTURE), "--writers", "nope"])


def test_stop_file_stops_before_any_file(tmp_path, monkeypatch, capsys):
    stop = tmp_path / "stop"
    stop.write_text("")
    monkeypatch.setattr(m, "STOP_FILE", stop)
    assert m.main(["--files", str(FIXTURE), "--workdir", str(tmp_path)]) == 3


def test_raw_diff_and_percentile():
    assert m.raw_diff(b"a\nb\n", b"a\nc\n") == (2, 4)
    assert m.raw_diff(b"a\n", b"a\n") == (0, 0)
    assert m.percentile([1, 2, 3, 4, 5], 0.9) == pytest.approx(4.6)
