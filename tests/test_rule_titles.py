"""Every rule has a short title of its own: a complete phrase, not the docstring cut mid-sentence."""

import py_tbparse.template_check  # noqa: F401  (importing registers the rules)
import py_tbparse.template_drift  # noqa: F401
import py_tbparse.workbook_audit  # noqa: F401
from py_tbparse.findings import _RULES, rules
from py_tbparse.validators import VALIDATE_RULES

DANGLING = {"a", "an", "the", "that", "this", "of", "to", "in", "on", "or", "and", "with", "than", "from", "for",
            "by", "at", "as", "is", "are", "not", "no", "its", "their", "which", "when", "if", "one", "another"}


def _all_titles():
    out = [(r.id, r.title, r.explicit_title) for r in _RULES.values()]
    out += [(r["id"], r["title"], True) for r in VALIDATE_RULES]
    return out


def test_every_rule_series_is_present():
    ids = {i for i, _, _ in _all_titles()}
    assert {f"A{n:03d}" for n in range(1, 12)} <= ids
    assert {f"T{n:03d}" for n in range(1, 11)} <= ids
    assert {f"D{n:03d}" for n in range(1, 12)} <= ids
    assert {"V001", "V002"} <= ids


def test_every_rule_has_an_explicit_short_title_that_is_a_complete_phrase():
    bad = []
    for rid, title, explicit in _all_titles():
        words = title.rstrip(".").split()
        if (not explicit or not title or len(title) > 60 or title != title.strip() or title.endswith((".", ",", ";", ":", "("))
                or title.count("`") % 2 or title.count("(") != title.count(")")
                or words[-1].lower() in DANGLING or len(words) < 2 and rid != "D011"):
            bad.append((rid, title))
    assert bad == []


def test_titles_are_unique_within_a_scope():
    for scope in ("workbook", "template", "drift"):
        titles = [r.title for r in rules(scope)]
        assert len(titles) == len(set(titles)), scope


def test_the_rule_lists_use_the_titles():
    from py_tbparse.workbook_audit import rules_help

    text = rules_help()
    assert "Calculated field that no worksheet uses" in text and "not even through another" not in text
