"""The Audit view's endpoints: GET /audit (one page of findings, counts, filters), /audit/export and /dictionary."""

from __future__ import annotations

import csv
import http.client
import io
import json
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_audit import workbook  # noqa: E402

from py_tbparse import webgui  # noqa: E402


@pytest.fixture
def server():
    webgui._STATE.update(parser=None, path=None, uploaded=False, report=None, audit=None)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webgui.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv.server_address
    finally:
        srv.shutdown()
        thread.join(timeout=2)


def _req(addr, path, method="GET", body=None):
    conn = http.client.HTTPConnection(*addr, timeout=10)
    conn.request(method, path, body=body, headers={"Content-Type": "application/json"} if body else {})
    r = conn.getresponse()
    data = r.read().decode("utf-8")
    headers = dict(r.getheaders())
    conn.close()
    return r.status, data, headers


def _get(addr, path):
    status, data, _ = _req(addr, path)
    return status, json.loads(data)


def _load(addr, path):
    assert _req(addr, "/load", "POST", json.dumps({"path": path}))[0] == 200


@pytest.fixture
def book(tmp_path):
    # A003 error (missing field), A001 info (unused calculation), A008 info (absolute path)
    return workbook(tmp_path, calcs=[("[Calculation_1]", "Broken", "[Sales] + [Gone]")],
                    conn="<connection class='excel-direct' filename='C:\\Users\\alice\\Desktop\\sales.xlsx'/>")


def test_audit_needs_a_workbook(server):
    status, body = _get(server, "/audit")
    assert status == 400 and "No workbook" in body["error"]
    assert _req(server, "/audit/export")[0] == 400
    assert _req(server, "/dictionary")[0] == 400


def test_audit_counts_summary_and_exit_code(server, book):
    _load(server, book)
    status, body = _get(server, "/audit")
    assert status == 200
    assert body["counts"]["error"] == 1 and body["total"] == len(body["findings"]) == body["matching"]
    assert body["summary"].startswith("1 error")
    assert body["exit_code"] == 1 and body["crashed"] == [] and body["skipped"] == []
    assert {r["id"] for r in body["rules"]} == {f"A{n:03d}" for n in range(1, 12)}
    assert all(set(f) == {"rule", "severity", "object", "detail", "fix"} for f in body["findings"])
    assert "alice" not in json.dumps(body)       # the folder of a local file is never sent


def test_skipping_a_rule_removes_its_findings_and_can_clear_the_exit_code(server, book):
    _load(server, book)
    _, body = _get(server, "/audit?skip=a008")
    assert body["skipped"] == ["A008"] and "A008" not in {f["rule"] for f in body["findings"]}
    assert next(r for r in body["rules"] if r["id"] == "A008")["skipped"] is True
    _, body = _get(server, "/audit?skip=A003")
    assert body["counts"]["error"] == 0 and body["exit_code"] == 0


def test_filters_by_severity_rule_and_text_do_not_change_the_counts(server, book):
    _load(server, book)
    _, everything = _get(server, "/audit")
    _, errors = _get(server, "/audit?severity=error")
    assert {f["severity"] for f in errors["findings"]} == {"error"}
    assert errors["matching"] == 1 and errors["total"] == everything["total"] and errors["counts"] == everything["counts"]
    _, one = _get(server, "/audit?rule=A008")
    assert {f["rule"] for f in one["findings"]} == {"A008"}
    _, text = _get(server, "/audit?q=gone")
    assert [f["rule"] for f in text["findings"]] == ["A003"]
    _, none = _get(server, "/audit?severity=warning&rule=A008")
    assert none["findings"] == [] and none["matching"] == 0


def test_rows_are_paged_and_capped(server, book):
    _load(server, book)
    _, everything = _get(server, "/audit")
    n = everything["total"]
    assert n >= 3
    _, first = _get(server, "/audit?limit=2")
    _, second = _get(server, "/audit?limit=2&offset=2")
    assert len(first["findings"]) == 2 and first["matching"] == n
    assert first["findings"] + second["findings"] == everything["findings"][:2 + len(second["findings"])]
    _, huge = _get(server, "/audit?limit=999999")
    assert huge["limit"] == webgui.AUDIT_PAGE_MAX
    _, past = _get(server, "/audit?offset=100000")
    assert past["findings"] == [] and past["matching"] == n


def test_bad_options_are_a_400_with_a_message(server, book):
    _load(server, book)
    for query, word in (("skip=A999", "unknown rule"), ("rule=ZZ", "unknown rule"), ("severity=fatal", "severity"),
                        ("limit=x", "whole numbers")):
        status, body = _get(server, "/audit?" + query)
        assert status == 400 and word in body["error"], query
    status, body = _get(server, "/audit?skip=" + ",".join(f"A{n:03d}" for n in range(1, 12)))
    assert status == 400 and "no rule to run" in body["error"]
    assert _req(server, "/audit/export?format=xml")[0] == 400


def test_export_csv_and_json_hold_every_finding_not_just_a_page(server, book):
    _load(server, book)
    _, everything = _get(server, "/audit")
    status, text, headers = _req(server, "/audit/export?format=csv")
    assert status == 200 and headers["Content-Type"].startswith("text/csv")
    assert headers["Content-Disposition"] == 'attachment; filename="wb-audit.csv"'
    rows = list(csv.DictReader(io.StringIO(text)))
    assert len(rows) == everything["total"] and list(rows[0]) == ["rule", "severity", "object", "detail", "fix"]
    status, text, headers = _req(server, "/audit/export?format=json&skip=A008&severity=info")
    assert headers["Content-Disposition"] == 'attachment; filename="wb-audit.json"'
    data = json.loads(text)
    assert data and {f["severity"] for f in data} == {"info"} and "A008" not in {f["rule"] for f in data}


def test_the_export_is_what_the_cli_writes(server, book):
    from py_tbparse import audit
    from py_tbparse.findings import format_findings
    _load(server, book)
    for fmt in ("csv", "json"):
        _, text, _ = _req(server, f"/audit/export?format={fmt}")
        assert text == format_findings(audit(book), fmt)


def test_the_audit_is_kept_until_the_next_workbook(server, book, tmp_path, monkeypatch):
    _load(server, book)
    calls = []
    real = webgui.run_audit
    monkeypatch.setattr(webgui, "run_audit", lambda *a, **k: calls.append(1) or real(*a, **k))
    _get(server, "/audit")
    _get(server, "/audit?severity=error&offset=0")
    _req(server, "/audit/export?format=csv")
    assert len(calls) == 1
    _get(server, "/audit?skip=A008")
    assert len(calls) == 2
    _load(server, workbook(tmp_path, name="other.twb"))
    _get(server, "/audit?skip=A008")
    assert len(calls) == 3


def test_a_crashing_rule_shows_as_an_error_finding_and_exit_3(server, book, monkeypatch):
    _load(server, book)
    from dataclasses import replace
    from py_tbparse import findings
    monkeypatch.setitem(findings._RULES, "A002", replace(findings._RULES["A002"], func=lambda s: 1 / 0))
    _, body = _get(server, "/audit")
    assert body["crashed"] == ["A002"] and body["exit_code"] == 3
    assert any(f["rule"] == "A002" and "rule failed" in f["detail"] for f in body["findings"])


def test_the_dictionary_is_the_markdown_page(server, book):
    _load(server, book)
    status, text, headers = _req(server, "/dictionary")
    assert status == 200 and headers["Content-Type"].startswith("text/markdown")
    assert headers["Content-Disposition"] == 'attachment; filename="wb-dictionary.md"'
    assert text.startswith("# ") and "Orders" in text


def test_the_page_lists_audit_in_the_sidebar_script():
    assert "audit.js" in webgui._ASSETS and "/static/audit.js" in webgui._read_webui("index.html")
