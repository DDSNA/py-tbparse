import json
import re
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from twbparser_py import webgui


def _page_script(base) -> str:
    """The <script> body of the served page, as the browser receives it."""
    with urllib.request.urlopen(base + "/") as r:
        page = r.read().decode()
    match = re.search(r"<script>(.*?)</script>", page, re.S)
    assert match, "served page has no <script> block"
    return match.group(1)


@pytest.fixture
def server():
    webgui._STATE["parser"] = None
    webgui._STATE["path"] = None
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webgui.Handler)
    host, port = srv.server_address
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://{host}:{port}"
    finally:
        srv.shutdown()
        thread.join(timeout=2)


def _get(base, path):
    try:
        with urllib.request.urlopen(base + path) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _post(base, path, payload):
    req = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_index_serves_html(server):
    with urllib.request.urlopen(server + "/") as r:
        assert r.status == 200
        body = r.read().decode()
    assert "<title>twbparser</title>" in body


def test_tables_endpoint(server):
    status, data = _get(server, "/tables")
    assert status == 200
    assert "datasources" in data["tables"]


def test_table_before_load_errors(server):
    status, data = _get(server, "/table?name=fields")
    assert status == 400
    assert "error" in data


def test_load_and_fetch_table(server, wenjie_path):
    status, data = _post(server, "/load", {"path": wenjie_path})
    assert status == 200
    assert data["ok"] is True

    status, data = _get(server, "/table?name=datasources")
    assert status == 200
    assert data["rows"] == 2
    assert "<table" in data["html"]


def test_load_missing_file(server):
    status, data = _post(server, "/load", {"path": "nope.twb"})
    assert status == 400
    assert "error" in data


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="'<' and '>' are illegal in Windows filenames, so this trigger "
    "path can't exist there in the first place",
)
def test_preload_path_cannot_break_out_of_script_tag(server, wenjie_path, tmp_path):
    # _STATE['path'] (whatever string was POSTed to /load) gets spliced
    # into the served page's <script> block via json.dumps(). json.dumps
    # doesn't escape '/', so a path containing the literal text
    # "</script>" would close the script tag early in the browser's HTML
    # parser -- before any JS runs -- letting arbitrary markup/script
    # from that path follow it on the page.
    #
    # A literal "/" can't appear inside one filename component (it's the
    # OS path separator), but the dangerous 9-char sequence "</script>"
    # can still appear in the *stringified path* by spanning a directory
    # boundary: a dir literally named "<" containing a dir literally
    # named "script>" -- both perfectly legal Linux filenames on their
    # own -- concatenate to ".../</script>/..." once joined with "/".
    evil_dir = tmp_path / "<" / "script>"
    evil_dir.mkdir(parents=True)
    evil_workbook = evil_dir / "wb.twb"
    evil_workbook.write_bytes(Path(wenjie_path).read_bytes())
    assert "</script>" in str(evil_workbook), "test setup didn't reproduce the trigger sequence"

    status, data = _post(server, "/load", {"path": str(evil_workbook)})
    assert status == 200
    assert data["ok"] is True

    with urllib.request.urlopen(server + "/") as r:
        page = r.read().decode()

    # The page must contain exactly one <script> element: if the path's
    # embedded "</script>" broke out of the intended script block, the
    # HTML parser would see (and this would count) a second one.
    assert page.count("<script>") == 1
    assert page.count("</script>") == 1
    # But the path itself (escaped) must still be present and round-trip
    # correctly -- \/ is a legal JSON escape, so json.loads decodes it
    # back to "/" on its own, no manual unescaping needed.
    js = re.search(r"<script>(.*?)</script>", page, re.S).group(1)
    literal = re.search(r"PRELOAD_PATH = (\".*?\");", js).group(1)
    assert json.loads(literal) == str(evil_workbook)


def test_unknown_table_404(server, wenjie_path):
    _post(server, "/load", {"path": wenjie_path})
    status, data = _get(server, "/table?name=bogus")
    assert status == 404


def test_export_csv(server, wenjie_path):
    _post(server, "/load", {"path": wenjie_path})
    with urllib.request.urlopen(server + "/export?name=fields") as r:
        assert r.status == 200
        assert r.headers.get("Content-Type", "").startswith("text/csv")
        body = r.read().decode()
    assert body.splitlines()[0].startswith("datasource,")


def test_dashboards_endpoint_empty_before_load(server):
    status, data = _get(server, "/dashboards")
    assert status == 200
    assert data["dashboards"] == []


def test_page_js_has_no_string_literal_split_across_lines(server):
    # Regression: _PAGE is a non-raw Python string, so writing '\n' inside
    # the embedded JS made *Python* emit a real newline, splitting a JS
    # string literal across two physical lines. That's a SyntaxError, and
    # it kills the whole <script> -- no listeners bind, the table dropdown
    # stays empty and the Load button does nothing. A JS string literal
    # can't span a physical line, so an odd number of unescaped quotes on
    # any line means an unterminated literal.
    js = _page_script(server)
    offenders = []
    for lineno, line in enumerate(js.splitlines(), 1):
        for quote in ("'", '"'):
            if len(re.findall(r"(?<!\\)" + quote, line)) % 2:
                offenders.append((lineno, quote, line.strip()[:60]))
    assert not offenders, f"unterminated JS string literal(s): {offenders}"


def test_page_js_escapes_newline_for_javascript(server):
    # The JS must receive a two-character \n escape, not a literal newline.
    js = _page_script(server)
    assert r"split('\n')" in js


def test_page_js_brackets_are_balanced(server):
    js = _page_script(server)
    # Strip string literals first so braces/parens inside them don't count.
    stripped = re.sub(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"", "''", js)
    for opener, closer in (("{", "}"), ("(", ")"), ("[", "]")):
        assert stripped.count(opener) == stripped.count(closer), (
            f"unbalanced {opener}{closer} in page JS"
        )


def test_page_js_binds_expected_handlers(server):
    # Cheap guard that the interactive wiring is present at all.
    js = _page_script(server)
    for fragment in (
        "$('loadBtn').addEventListener",
        "$('tableSel').addEventListener",
        "function populateTables()",
        "populateTables();",
    ):
        assert fragment in js, f"missing JS wiring: {fragment}"


def test_graph_before_load_errors(server):
    status, data = _get(server, "/graph")
    assert status == 400
    assert "error" in data


def test_graph_endpoint(server, wenjie_path):
    _post(server, "/load", {"path": wenjie_path})
    status, data = _get(server, "/graph")
    assert status == 200
    assert data["dot"].startswith("digraph \"twb\" {")
    assert "Sheet1" in data["dot"]


def test_graph_download(server, wenjie_path):
    _post(server, "/load", {"path": wenjie_path})
    with urllib.request.urlopen(server + "/graph?download=1") as r:
        assert r.status == 200
        assert r.headers.get("Content-Type", "").startswith("text/vnd.graphviz")
        body = r.read().decode()
    assert body.startswith("digraph \"twb\" {")
