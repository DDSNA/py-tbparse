import os
import threading
from http.server import ThreadingHTTPServer

from pathlib import Path

import pytest
from lxml import etree

import py_tbparse
from py_tbparse import webgui

FIXTURES = Path(__file__).parent / "fixtures"


def _check_same_checkout():
    """Fail fast when py_tbparse comes from another checkout than these tests.

    A venv with an editable install points at one checkout; running its `pytest` inside a git worktree
    then tests the other copy and passes or fails for the wrong code. See docs/development.md."""
    tests_root = Path(__file__).resolve().parent.parent
    imported = Path(py_tbparse.__file__).resolve().parent
    # An installed copy (a wheel in site-packages, as the sdist check uses) has no pyproject.toml beside it;
    # only another source checkout is a mistake.
    other_checkout = imported.parent != tests_root and (imported.parent / "pyproject.toml").exists()
    if other_checkout and os.environ.get("TBPARSE_ALLOW_OTHER_CHECKOUT") != "1":
        raise pytest.UsageError(
            f"py_tbparse was imported from {imported}, but these tests are in {tests_root}. "
            f"Run with PYTHONPATH={tests_root} (or scripts/ci-like-tests.sh), "
            "or set TBPARSE_ALLOW_OTHER_CHECKOUT=1 to test an installed copy on purpose."
        )


_check_same_checkout()


@pytest.fixture
def wenjie_xml():
    return etree.parse(str(FIXTURES / "test_for_wenjie.twb"))


@pytest.fixture
def wenjie_path():
    return str(FIXTURES / "test_for_wenjie.twb")


@pytest.fixture
def zip_twbx_path():
    return str(FIXTURES / "test_for_zip.twbx")


def xml_from_string(s: str):
    return etree.fromstring(s.encode("utf-8"))


# Real Tableau workbooks give every column in the "Parameters" datasource a
# @param-domain-type attribute plus a <calculation> holding its value.
REAL_PARAMS_XML = """
<workbook>
  <datasources>
    <datasource name="Parameters" hasconnection="false" inline="true">
      <aliases enabled="yes"/>
      <column caption="Top N" datatype="integer" name="[Parameter 1]"
              param-domain-type="range" role="measure" type="quantitative" value="10">
        <calculation class="tableau" formula="10"/>
        <range granularity="1" max="50" min="1"/>
      </column>
      <column caption="Region Pick" datatype="string" name="[Parameter 2]"
              param-domain-type="list" role="measure" type="nominal" value="&quot;East&quot;">
        <calculation class="tableau" formula="&quot;East&quot;"/>
        <members>
          <member value="&quot;East&quot;"/>
          <member value="&quot;West&quot;"/>
        </members>
      </column>
    </datasource>
    <datasource name="Orders">
      <column name="[Amount]" caption="Amount" datatype="real" role="measure">
        <calculation class="tableau" formula="SUM([Sales])"/>
      </column>
    </datasource>
  </datasources>
</workbook>
"""


# --- shared browser fixtures: defined once here so the session-scoped browser really is one instance
# (a fixture imported into several test modules is instantiated once per module, and a second
# sync_playwright() inside the first one's event loop fails).

def _pw():
    return pytest.importorskip("playwright.sync_api", reason="playwright not installed")


_REPO_ROOT = Path(__file__).resolve().parent.parent
_LOCAL_LIBS = _REPO_ROOT / ".browser-libs" / "root" / "usr" / "lib" / "x86_64-linux-gnu"
_LOCAL_XKB = _REPO_ROOT / ".browser-libs" / "root" / "usr" / "share" / "X11" / "xkb"
_LOCAL_FONTS_CONF = _REPO_ROOT / ".browser-libs" / "fonts.conf"


def _browser_env() -> dict:
    """Chromium needs a handful of system libraries. On a machine where
    they're installed system-wide (CI) the plain environment is fine; on
    one where they were unpacked locally instead of apt-installed (see
    scripts/setup-browser-libs.sh), point the loader at them."""
    env = dict(os.environ)
    if _LOCAL_LIBS.is_dir():
        existing = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = f"{_LOCAL_LIBS}:{existing}" if existing else str(_LOCAL_LIBS)
    # Keyboard layouts and fonts unpacked by the same script, if the host
    # has none of its own (otherwise key input is dropped / text can't render).
    if _LOCAL_XKB.is_dir():
        env.setdefault("XKB_CONFIG_ROOT", str(_LOCAL_XKB))
    if _LOCAL_FONTS_CONF.is_file():
        env.setdefault("FONTCONFIG_FILE", str(_LOCAL_FONTS_CONF))
    return env


@pytest.fixture(scope="session")
def browser():
    with _pw().sync_playwright() as pw:
        try:
            instance = pw.chromium.launch(env=_browser_env())
        except _pw().Error as e:
            # Playwright's own exception type for "the browser process
            # didn't come up" (missing binary, missing system libs, etc).
            # Deliberately NOT a bare `except Exception`: that would also
            # swallow bugs in this fixture itself (a bad kwarg, a renamed
            # API) as a silent, green "skipped" -- which is exactly the
            # false-confidence failure mode this whole test file exists to
            # catch for the GUI itself. Let anything else propagate as a
            # real test error.
            pytest.skip(f"chromium could not launch: {str(e)[:200]}")
        yield instance
        instance.close()


@pytest.fixture
def gui_server():
    webgui._STATE["parser"] = None
    webgui._STATE["path"] = None
    webgui._STATE["uploaded"] = False
    webgui._STATE["report"] = None
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webgui.Handler)
    host, port = srv.server_address
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://{host}:{port}"
    finally:
        srv.shutdown()
        thread.join(timeout=2)


def new_page(browser, url, **context_args):
    """A page on the GUI at `url` with JS errors recorded on `page.js_errors`. `context_args` go to
    `browser.new_context`, so a test can pick a viewport, colour scheme or reduced motion. Close it
    with `page.ctx.close()`."""
    ctx = browser.new_context(**context_args)
    ctx.grant_permissions(["clipboard-read", "clipboard-write"])
    pg = ctx.new_page()
    pg.ctx = ctx
    pg.js_errors = []
    pg.on("pageerror", lambda e: pg.js_errors.append(str(e)))
    pg.on(
        "console",
        lambda msg: pg.js_errors.append(f"console.{msg.type}: {msg.text}")
        if msg.type == "error"
        else None,
    )
    pg.goto(url)
    return pg


@pytest.fixture
def page(browser, gui_server):
    """A page on the running GUI, with JS errors recorded on `page.js_errors`."""
    pg = new_page(browser, gui_server)
    yield pg
    pg.ctx.close()


