import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from twbparser_py import webgui


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
