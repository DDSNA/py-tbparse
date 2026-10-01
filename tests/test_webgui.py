import http.client
import json
import re
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from py_tbparse import webgui


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
    assert "<title>py-tbparse</title>" in body


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


def test_load_reports_name_and_row_counts(server, wenjie_path):
    status, data = _post(server, "/load", {"path": wenjie_path})
    assert status == 200
    assert data["name"] == "test_for_wenjie.twb"
    assert set(data["counts"]) == set(webgui.TABLE_NAMES)
    assert data["counts"]["datasources"] == 2
    assert data["counts"]["fields"] == 55


def test_table_returns_json_rows_for_client_rendering(server, wenjie_path):
    _post(server, "/load", {"path": wenjie_path})
    status, data = _get(server, "/table?name=relationships")
    assert status == 200
    assert data["columns"][:3] == ["relationship_type", "left_table", "right_table"]
    assert len(data["data"]) == data["rows"] == 1
    row = dict(zip(data["columns"], data["data"][0]))
    # Real JSON types (not stringified) so the page can sort numerically
    # and render booleans as flags.
    assert row["left_is_calc"] is False
    assert row["left_table"] == "Sheet1"


def test_table_json_uses_null_for_missing_values(server, wenjie_path):
    _post(server, "/load", {"path": wenjie_path})
    status, data = _get(server, "/table?name=fields")
    caption = data["columns"].index("caption")
    assert any(r[caption] is None for r in data["data"])


def test_page_includes_app_version(server):
    with urllib.request.urlopen(server + "/") as r:
        body = r.read().decode()
    assert "window.APP_VERSION = " in body


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


def _raw(base, method, path, headers, body=None):
    """Send a request with full control over Host/Origin/Content-Type."""
    parts = urlsplit(base)
    conn = http.client.HTTPConnection(parts.hostname, parts.port, timeout=5)
    try:
        conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        for k, v in headers.items():
            conn.putheader(k, v)
        if body is not None:
            conn.putheader("Content-Length", str(len(body)))
        conn.endheaders(body)
        resp = conn.getresponse()
        return resp.status, resp.read()
    finally:
        conn.close()


@pytest.mark.parametrize(
    "path",
    ["/", "/tables", "/table?name=custom-sql", "/export?name=custom-sql", "/graph", "/dashboards"],
)
def test_get_with_foreign_host_rejected(server, wenjie_path, path):
    # DNS rebinding: attacker.example re-resolves to 127.0.0.1, so the
    # browser treats the GUI as same-origin with the attacker's page and
    # lets it read responses. Only the Host header gives it away.
    _post(server, "/load", {"path": wenjie_path})
    port = urlsplit(server).port
    status, _ = _raw(server, "GET", path, {"Host": f"attacker.example:{port}"})
    assert status == 403


def test_get_with_wrong_port_host_rejected(server):
    status, _ = _raw(server, "GET", "/tables", {"Host": "127.0.0.1:1"})
    assert status == 403


def test_get_without_host_rejected(server):
    status, _ = _raw(server, "GET", "/tables", {})
    assert status == 403


@pytest.mark.parametrize("hostname", ["127.0.0.1", "localhost", "LocalHost"])
def test_get_with_loopback_host_allowed(server, hostname):
    port = urlsplit(server).port
    status, body = _raw(server, "GET", "/tables", {"Host": f"{hostname}:{port}"})
    assert status == 200
    assert "datasources" in json.loads(body)["tables"]


def test_load_with_foreign_host_rejected(server, wenjie_path):
    port = urlsplit(server).port
    status, _ = _raw(
        server,
        "POST",
        "/load",
        {"Host": f"attacker.example:{port}", "Content-Type": "application/json"},
        json.dumps({"path": wenjie_path}).encode(),
    )
    assert status == 403
    assert webgui._STATE["parser"] is None


@pytest.mark.parametrize("ctype", ["text/plain", "text/plain;charset=UTF-8", None])
def test_load_requires_json_content_type(server, wenjie_path, ctype):
    # text/plain (or no type) is a CORS "simple" request: any website can
    # send it cross-origin with no preflight. Requiring application/json
    # forces a preflight, which this server never approves.
    headers = {"Host": urlsplit(server).netloc}
    if ctype:
        headers["Content-Type"] = ctype
    status, _ = _raw(server, "POST", "/load", headers, json.dumps({"path": wenjie_path}).encode())
    assert status == 415
    assert webgui._STATE["parser"] is None


@pytest.mark.parametrize("origin", ["http://attacker.example", "null", "http://127.0.0.1:1"])
def test_load_with_cross_origin_rejected(server, wenjie_path, origin):
    status, _ = _raw(
        server,
        "POST",
        "/load",
        {"Host": urlsplit(server).netloc, "Content-Type": "application/json", "Origin": origin},
        json.dumps({"path": wenjie_path}).encode(),
    )
    assert status == 403
    assert webgui._STATE["parser"] is None


def test_load_with_same_origin_allowed(server, wenjie_path):
    # Mirrors what the page's own fetch() sends.
    status, body = _raw(
        server,
        "POST",
        "/load",
        {
            "Host": urlsplit(server).netloc,
            "Content-Type": "application/json",
            "Origin": server,
        },
        json.dumps({"path": wenjie_path}).encode(),
    )
    assert status == 200
    assert json.loads(body)["ok"] is True


@pytest.fixture
def wildcard_server():
    webgui._STATE["parser"] = None
    webgui._STATE["path"] = None
    srv = ThreadingHTTPServer(("0.0.0.0", 0), webgui.Handler)
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        srv.shutdown()
        thread.join(timeout=2)


@pytest.mark.parametrize("hostname", ["192.168.1.20", "10.0.0.5", "[::1]", "localhost"])
def test_wildcard_bind_accepts_ip_literal_hosts(wildcard_server, hostname):
    # Bound to 0.0.0.0 the server can't know which address it's reached
    # as, but an IP-literal Host can't be the product of DNS rebinding.
    port = urlsplit(wildcard_server).port
    status, _ = _raw(wildcard_server, "GET", "/tables", {"Host": f"{hostname}:{port}"})
    assert status == 200


def test_wildcard_bind_still_rejects_domain_hosts(wildcard_server):
    port = urlsplit(wildcard_server).port
    status, _ = _raw(wildcard_server, "GET", "/tables", {"Host": f"attacker.example:{port}"})
    assert status == 403


def test_field_renames_table_and_workbook_buttons(server, wenjie_path, tmp_path):
    import shutil

    book = tmp_path / "book.twb"
    shutil.copy(wenjie_path, book)
    status, data = _post(server, "/load", {"path": str(book)})
    assert status == 200 and data["datasources"]
    assert "field-renames" in data["counts"]

    status, table = _get(server, "/table?name=field-renames&only_changed=true&style=title")
    assert status == 200
    assert [r[table["columns"].index("suggested")] for r in table["data"]] == ["Mun", "Counts", "No Data"]

    status, err = _get(server, "/table?name=field-renames&reference=/nope.twb")
    assert status == 400

    with urllib.request.urlopen(server + "/download-workbook?style=title") as r:
        assert r.status == 200
        assert "book_renamed.twb" in r.headers["Content-Disposition"]
        assert b"No Data" in r.read()
    assert not (tmp_path / "book_renamed.twb").exists()  # download writes nothing

    status, made = _post(server, "/create-workbook", {"style": "title"})
    assert status == 200 and made["renamed"] == 3
    assert (tmp_path / "book_renamed.twb").exists()
    status, again = _post(server, "/create-workbook", {})
    assert status == 409


def test_create_workbook_needs_a_workbook(server):
    status, _ = _post(server, "/create-workbook", {})
    assert status == 400


def test_download_workbook_with_non_latin1_name(server, wenjie_path, tmp_path):
    # http.server encodes headers as latin-1; a raw CJK filename used to abort
    # the response mid-headers. (No quotes in the on-disk name: `"` is not a
    # legal Windows filename character -- that case is covered below.)
    import shutil
    from urllib.parse import quote

    book = tmp_path / "Ventes été 売上.twb"
    shutil.copy(wenjie_path, book)
    assert _post(server, "/load", {"path": str(book)})[0] == 200
    with urllib.request.urlopen(server + "/download-workbook?style=title") as r:
        assert r.status == 200
        disp = r.headers["Content-Disposition"]
    assert "filename*=UTF-8''" + quote("Ventes été 売上_renamed.twb", safe="") in disp
    disp.encode("latin-1")  # what http.server will do with it


def test_attachment_header_survives_quotes_and_backslashes():
    from urllib.parse import quote

    name = 'Ventes "été" \\ 売上.twb'
    disp = webgui._attachment(name)
    assert disp.count('"') == 2  # the name's own quotes don't end the fallback early
    assert "\\" not in disp.split("; filename*")[0]
    assert "filename*=UTF-8''" + quote(name, safe="") in disp
    disp.encode("latin-1")


def test_malformed_reference_workbook_is_a_400(server, wenjie_path, tmp_path):
    bad = tmp_path / "bad.twb"
    bad.write_text("<workbook")
    assert _post(server, "/load", {"path": str(wenjie_path)})[0] == 200
    status, err = _get(server, "/table?name=field-renames&reference=" + str(bad))
    assert status == 400 and "reference" in err["error"]
    status, err = _post(server, "/create-workbook", {"reference": str(bad)})
    assert status == 400


def test_post_body_must_be_a_json_object(server):
    for path in ("/load", "/create-workbook"):
        status, err = _post(server, path, [1])
        assert status == 400 and "object" in err["error"]


def test_everything_in_the_report_via_the_endpoints(server, tmp_path):
    from test_rename_all import WORKBOOK

    book = tmp_path / "report.twb"
    book.write_text(WORKBOOK, encoding="utf-8")
    assert _post(server, "/load", {"path": str(book)})[0] == 200

    status, table = _get(server, "/table?name=field-renames&only_changed=true")
    assert status == 200 and "kind" not in table["columns"]  # fields only by default

    status, table = _get(server, "/table?name=field-renames&only_changed=true&kinds=all")
    assert status == 200 and table["columns"][0] == "kind"
    kinds = {r[0] for r in table["data"]}
    assert {"worksheet", "dashboard", "datasource", "folder", "hierarchy", "parameter", "field"} <= kinds

    # only "all" is accepted from the web; anything else means fields only
    status, table = _get(server, "/table?name=field-renames&kinds=worksheet")
    assert status == 200 and "kind" not in table["columns"]

    status, made = _post(server, "/create-workbook", {"kinds": "all"})
    assert status == 200 and made["renamed"] > 3
    text = (tmp_path / "report_renamed.twb").read_text(encoding="utf-8")
    assert "My Dashboard" in text and "my dashboard" not in text
