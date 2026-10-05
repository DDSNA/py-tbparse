"""The shared findings engine (py_tbparse/findings.py): registry, ordering, filters, formats."""

import json

import pandas as pd
import pytest

from py_tbparse import findings as F
from py_tbparse.findings import FINDING_COLUMNS, Subject, finding, format_findings, rule, run_rules


@pytest.fixture
def demo_rules():
    """A private scope, so the tests never depend on (or disturb) the real rules."""
    saved = dict(F._RULES)

    @rule("X002", "demo", severity="warning", fix="do the thing")
    def two(subject):
        yield finding("b-object", "second warning")
        yield finding("a-object", "first warning")

    @rule("X001", "demo", severity="error")
    def one(subject):
        yield finding("z", "an error", fix="fix z")

    @rule("X003", "demo", severity="info")
    def three(subject):
        return []

    @rule("Y001", "other", severity="info")
    def other(subject):
        yield finding("o", "other scope")

    yield
    F._RULES.clear()
    F._RULES.update(saved)


def test_columns_and_severity_order():
    assert FINDING_COLUMNS == ["rule", "severity", "object", "detail", "fix"]
    assert F.SEVERITY == {"error": 0, "warning": 1, "info": 2}


def test_run_rules_sorts_by_rule_severity_object(demo_rules):
    df = run_rules(Subject(), "demo")
    assert list(df.columns) == FINDING_COLUMNS
    assert list(df["rule"]) == ["X001", "X002", "X002"]
    assert list(df["object"]) == ["z", "a-object", "b-object"]
    assert df.iloc[1]["fix"] == "do the thing"      # the rule's default fix text
    assert df.iloc[0]["fix"] == "fix z"             # a finding's own fix wins
    assert list(df.index) == [0, 1, 2]


def test_scope_selects_rules(demo_rules):
    assert list(run_rules(Subject(), "other")["rule"]) == ["Y001"]


def test_only_and_skip(demo_rules):
    assert set(run_rules(Subject(), "demo", only=["X002"])["rule"]) == {"X002"}
    assert set(run_rules(Subject(), "demo", skip=["x002"])["rule"]) == {"X001"}   # case-insensitive
    assert run_rules(Subject(), "demo", only=["X003"]).empty


def test_empty_result_keeps_columns(demo_rules):
    df = run_rules(Subject(), "demo", only=["X003"])
    assert list(df.columns) == FINDING_COLUMNS and len(df) == 0


def test_unknown_rule_id_is_an_error_naming_the_known_ones(demo_rules):
    with pytest.raises(ValueError, match="X999.*X001, X002, X003"):
        run_rules(Subject(), "demo", only=["X999"])
    with pytest.raises(ValueError, match="X999"):
        run_rules(Subject(), "demo", skip=["X999"])
    with pytest.raises(ValueError, match="Y001"):       # a rule of another scope is not known here
        run_rules(Subject(), "demo", only=["Y001"])


def test_unknown_scope_is_an_error(demo_rules):
    with pytest.raises(ValueError, match="nope"):
        run_rules(Subject(), "nope")


def test_duplicate_rule_id_is_refused(demo_rules):
    with pytest.raises(ValueError, match="X001"):
        @rule("X001", "demo", severity="info")
        def again(subject):
            return []


def test_bad_severity_is_refused(demo_rules):
    with pytest.raises(ValueError, match="severity"):
        @rule("X009", "demo", severity="fatal")
        def bad(subject):
            return []
    with pytest.raises(ValueError, match="severity"):
        finding("o", "d", severity="fatal")


def test_a_crashing_rule_becomes_an_error_finding_not_an_exception(demo_rules):
    @rule("X004", "demo", severity="info")
    def boom(subject):
        yield finding("fine", "before")
        raise RuntimeError("kaput")

    df = run_rules(Subject(), "demo", only=["X004"])
    assert list(df["detail"])[1] == "before"          # what it found before crashing is kept
    row = df.iloc[0]
    assert row["severity"] == "error" and "RuntimeError" in row["detail"] and "kaput" in row["detail"]


def test_a_finding_can_override_severity(demo_rules):
    @rule("X005", "demo", severity="info")
    def mixed(subject):
        yield finding("a", "bumped", severity="error")
        yield finding("b", "default")

    df = run_rules(Subject(), "demo", only=["X005"])
    assert list(df["severity"]) == ["error", "info"]


def test_rule_ids_listing(demo_rules):
    ids = F.rule_ids("demo")
    assert ids == ["X001", "X002", "X003"]


def test_exceeds():
    df = pd.DataFrame([{"rule": "A", "severity": "warning", "object": "", "detail": "", "fix": ""}],
                      columns=FINDING_COLUMNS)
    assert F.exceeds(df, "warning") and F.exceeds(df, "info")
    assert not F.exceeds(df, "error")
    assert not F.exceeds(df, "never")
    assert not F.exceeds(df.iloc[0:0], "info")
    with pytest.raises(ValueError):
        F.exceeds(df, "bad")


def test_counts_line():
    df = pd.DataFrame([{"rule": "A", "severity": s, "object": "", "detail": "", "fix": ""}
                       for s in ("error", "warning", "warning", "info")], columns=FINDING_COLUMNS)
    assert F.summary(df) == "1 error, 2 warnings, 1 info"
    assert F.summary(df.iloc[0:0]) == "no findings"


def test_formats():
    df = pd.DataFrame([{"rule": "T001", "severity": "error", "object": "ds, one", "detail": 'say "hi"\nnow',
                        "fix": "fix it"}], columns=FINDING_COLUMNS)
    assert "T001" in format_findings(df, "table") and "ds, one" in format_findings(df, "table")
    assert format_findings(df.iloc[0:0], "table") == "(no findings)"
    csv_text = format_findings(df, "csv")
    assert csv_text.splitlines()[0] == ",".join(FINDING_COLUMNS)
    back = pd.read_csv(__import__("io").StringIO(csv_text))
    assert back.iloc[0]["detail"] == 'say "hi"\nnow'
    assert json.loads(format_findings(df, "json"))[0]["rule"] == "T001"
    assert json.loads(format_findings(df.iloc[0:0], "json")) == []
    with pytest.raises(ValueError, match="junit.*table, csv, json|table, csv, json.*junit"):
        format_findings(df, "junit")


def test_formats_are_a_registry_a_later_format_slots_into():
    assert list(F.FORMATS) == ["table", "csv", "json"]
    F.FORMATS["x-test"] = lambda df: "custom"
    try:
        assert format_findings(pd.DataFrame(columns=FINDING_COLUMNS), "x-test") == "custom"
    finally:
        del F.FORMATS["x-test"]


# --- crashes, selection (issue #28) -------------------------------------------

def _boom_rule(rule_id="X004", message="kaput"):
    @rule(rule_id, "demo", severity="info")
    def boom(subject):
        raise RuntimeError(message)


def test_a_crash_is_marked_on_the_frame_and_keeps_its_traceback(demo_rules):
    _boom_rule()
    df = run_rules(Subject(), "demo", only=["X004", "X001"])
    assert df.attrs["crashed"] == ["X004"]
    assert "RuntimeError" in df.attrs["tracebacks"]["X004"] and "Traceback" in df.attrs["tracebacks"]["X004"]
    assert run_rules(Subject(), "demo", only=["X001"]).attrs.get("crashed") == []


def test_a_crash_message_carries_no_local_path(demo_rules, tmp_path):
    home = str(__import__("pathlib").Path.home())
    _boom_rule(message=f"cannot open {home}/secret/x.csv and {tmp_path}/t.twbx")
    df = run_rules(Subject(path=str(tmp_path / "t.twbx")), "demo", only=["X004"])
    detail = df.iloc[0]["detail"]
    assert home not in detail and str(tmp_path) not in detail and "<path>" in detail


def test_only_and_skip_take_one_id_as_text(demo_rules):
    assert set(run_rules(Subject(), "demo", only="X002")["rule"]) == {"X002"}     # not the characters X, 0, 2
    assert set(run_rules(Subject(), "demo", skip="X002")["rule"]) == {"X001"}


def test_an_empty_only_is_an_error_not_a_silent_no_op(demo_rules):
    with pytest.raises(ValueError, match="only"):
        run_rules(Subject(), "demo", only=[])
    with pytest.raises(ValueError, match="only"):
        run_rules(Subject(), "demo", only=[" ", ""])


def test_only_and_skip_that_cancel_are_an_error(demo_rules):
    with pytest.raises(ValueError, match="no rule to run"):
        run_rules(Subject(), "demo", only=["X001"], skip=["X001"])
    with pytest.raises(ValueError, match="no rule to run"):
        run_rules(Subject(), "demo", skip=["X001", "X002", "X003"])


def test_csv_formula_injection_is_neutralised():
    cells = ["=HYPERLINK(\"http://x\")", "+1", "-1", "@SUM(A1)", "\tx", "plain", "a=b"]
    df = pd.DataFrame([{"rule": "T001", "severity": "info", "object": c, "detail": c, "fix": ""} for c in cells],
                      columns=FINDING_COLUMNS)
    back = pd.read_csv(__import__("io").StringIO(format_findings(df, "csv")), keep_default_na=False)
    assert list(back["object"]) == ["'" + c if c[0] in "=+-@\t" else c for c in cells]
    assert list(df["object"]) == cells                      # the frame itself is untouched
    assert json.loads(format_findings(df, "json"))[0]["object"] == cells[0]


def test_a_formatter_error_is_not_reported_as_an_unknown_format():
    F.FORMATS["x-bad"] = lambda df: {}["nope"]
    try:
        with pytest.raises(KeyError):
            format_findings(pd.DataFrame(columns=FINDING_COLUMNS), "x-bad")
    finally:
        del F.FORMATS["x-bad"]


def test_registering_the_same_rule_again_replaces_it_but_another_function_is_refused(demo_rules):
    def register():
        @rule("X010", "demo", severity="info")
        def reloadable(subject):
            return []
    register()
    register()                                   # what importlib.reload of the defining module does
    assert F.rule_ids("demo").count("X010") == 1
    with pytest.raises(ValueError, match="X010"):
        @rule("X010", "demo", severity="info")
        def impostor(subject):
            return []
