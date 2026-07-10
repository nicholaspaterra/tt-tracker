"""Browser-fetch fallback: only kicks in on HTTP 403 AND with the opt-in
env flag; every other error propagates unchanged. Playwright itself is never
imported in tests — a fake browser_fetch module is injected."""

import io
import sys
import types
import urllib.error
import urllib.request

import pytest

import engine


def http_error(code):
    return urllib.error.HTTPError("https://x", code, "err", {}, io.BytesIO(b""))


@pytest.fixture
def blocked_network(monkeypatch):
    def deny(req, timeout=None):
        raise http_error(403)
    monkeypatch.setattr(urllib.request, "urlopen", deny)


@pytest.fixture
def fake_browser(monkeypatch):
    calls = []
    mod = types.ModuleType("browser_fetch")
    mod.fetch_text = lambda url: calls.append(("text", url)) or "<html>via-browser</html>"
    mod.fetch_bytes = lambda url: calls.append(("bytes", url)) or b"\x7a\x00"
    monkeypatch.setitem(sys.modules, "browser_fetch", mod)
    return calls


def test_403_without_flag_propagates(blocked_network, monkeypatch):
    monkeypatch.delenv("TT_BROWSER_FETCH", raising=False)
    with pytest.raises(urllib.error.HTTPError):
        engine.fetch("https://m.aiscore.com/whatever")


def test_403_with_flag_uses_browser_for_html(blocked_network, fake_browser, monkeypatch):
    monkeypatch.setenv("TT_BROWSER_FETCH", "1")
    assert engine.fetch("https://m.aiscore.com/x") == "<html>via-browser</html>"
    assert fake_browser == [("text", "https://m.aiscore.com/x")]


def test_403_with_flag_uses_browser_for_api_bytes(blocked_network, fake_browser, monkeypatch):
    monkeypatch.setenv("TT_BROWSER_FETCH", "1")
    assert engine.fetch_api_bytes("https://api.aiscore.com/x") == b"\x7a\x00"
    assert fake_browser == [("bytes", "https://api.aiscore.com/x")]


def test_non_403_errors_never_fall_back(fake_browser, monkeypatch):
    monkeypatch.setenv("TT_BROWSER_FETCH", "1")
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: (_ for _ in ()).throw(http_error(500)))
    with pytest.raises(urllib.error.HTTPError):
        engine.fetch("https://m.aiscore.com/x")
    assert fake_browser == []
