#!/usr/bin/env python3
"""
OPT-IN live smoke test — hits the real site ONCE per endpoint for manual
verification. Never run by the test suite or the hourly engine.

    python3 smoke_live.py

Known limitation (2026-07-10): aiscore fronts everything with bot protection
that 403s plain-Python clients (urllib AND curl) from residential macOS.
A real browser gets through. If every check below prints 403, the engine
cannot fetch from this network either — try the GitHub Actions runner
(Actions tab -> TT Engine -> Run workflow) and read its log instead.
"""

import sys
import time

import czech
import engine

CHECKS = [
    ("ITTF rankings page (engine.parse_rankings)",
     lambda: len(engine.parse_rankings(engine.fetch(engine.RANKINGS_URLS[0])))),
    ("day-slate matches API (czech.parse_matches)",
     lambda: len(czech.parse_matches(czech.fetch_bytes(
         czech.MATCHES_URL % (time.strftime("%Y%m%d"), "+00:00"))))),
]


def main():
    failures = 0
    for name, check in CHECKS:
        try:
            n = check()
            print("OK   %-45s -> %d item(s) parsed" % (name, n))
            if n == 0:
                print("     ^ 200 but nothing parsed: page layout may have changed")
                failures += 1
        except Exception as e:
            print("FAIL %-45s -> %s" % (name, e))
            failures += 1
        time.sleep(engine.REQUEST_DELAY)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
