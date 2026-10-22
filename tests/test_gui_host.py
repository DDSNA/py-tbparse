"""`py-tbparse-gui --host <non-loopback>` in local mode is refused unless --allow-network-local is given.
The decision is a plain function; no socket is opened."""

import pytest

from py_tbparse import webgui


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "LOCALHOST", "::1", "127.0.0.5"])
def test_loopback_starts_quietly(host):
    assert webgui._network_exposure(host, False, False) == (True, [])


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "", "192.168.1.20", "my-laptop.lan", "example.com"])
def test_network_host_is_refused_in_local_mode(host):
    start, lines = webgui._network_exposure(host, False, False)
    assert start is False
    assert len(lines) > 2 and lines[0].startswith("WARNING")
    assert "--allow-network-local" in lines[-1]


def test_flag_starts_with_the_warning():
    start, lines = webgui._network_exposure("0.0.0.0", False, True)
    assert start is True
    assert lines[0].startswith("WARNING") and "anyway" in lines[-1]


@pytest.mark.parametrize("flag", [False, True])
def test_server_mode_is_untouched(flag):
    assert webgui._network_exposure("0.0.0.0", True, flag) == (True, [])


def test_main_refuses_before_binding(monkeypatch, capsys):
    def no_socket(*a, **k):
        raise AssertionError("must not bind")

    monkeypatch.setattr(webgui, "ThreadingHTTPServer", no_socket)
    assert webgui.main(["--host", "0.0.0.0", "--no-browser"]) == 2
    err = capsys.readouterr().err
    assert "WARNING" in err and "Refusing to start" in err


def test_flag_exists_in_the_parser():
    args = webgui.build_arg_parser().parse_args(["--host", "0.0.0.0", "--allow-network-local"])
    assert args.allow_network_local is True
