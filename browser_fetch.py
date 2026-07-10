#!/usr/bin/env python3
"""
Browser-based fetch fallback for hosts where aiscore's bot protection 403s
plain-Python clients (it challenges urllib and curl alike; a real Chrome
gets through — verified 2026-07-10).

Loads the mobile site once in headless Chromium (Playwright), then issues
every fetch from inside the page — same network path a phone uses, and
api.aiscore.com already allows the m.aiscore.com origin.

Opt-in only: the engine uses this when TT_BROWSER_FETCH=1 AND a plain
request got HTTP 403. Requires:  pip install playwright
                                 playwright install --with-deps chromium
The hourly GitHub Actions workflow does both. Local runs stay stdlib-only.
"""

import base64

_pw = None
_browser = None
_page = None

_FETCH_JS = """async (u) => {
  const r = await fetch(u, {headers: {'Accept-Language': 'en'}});
  const buf = new Uint8Array(await r.arrayBuffer());
  let s = '';
  for (let i = 0; i < buf.length; i += 8192)
    s += String.fromCharCode.apply(null, Array.from(buf.slice(i, i + 8192)));
  return {status: r.status, b64: btoa(s)};
}"""


def _get_page():
    global _pw, _browser, _page
    if _page is None:
        from playwright.sync_api import sync_playwright
        _pw = sync_playwright().start()
        _browser = _pw.chromium.launch(headless=True)
        _page = _browser.new_page()
        _page.goto("https://m.aiscore.com/table-tennis",
                   wait_until="domcontentloaded", timeout=60000)
        _page.wait_for_timeout(3000)  # let any bot-check settle
    return _page


def fetch_bytes(url):
    res = _get_page().evaluate(_FETCH_JS, url)
    if res["status"] != 200:
        raise OSError("browser fetch got HTTP %s for %s" % (res["status"], url))
    return base64.b64decode(res["b64"])


def fetch_text(url):
    return fetch_bytes(url).decode("utf-8", "replace")


def close():
    global _pw, _browser, _page
    if _browser is not None:
        _browser.close()
    if _pw is not None:
        _pw.stop()
    _pw = _browser = _page = None
