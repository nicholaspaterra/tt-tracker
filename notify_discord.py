#!/usr/bin/env python3
"""
Post new wagers and settlements to a Discord channel after each engine run.

Reads bets.js, compares against .discord_posted.json (bet id -> last status
announced), and posts one message per change to the webhook in the
DISCORD_WEBHOOK env var. No webhook configured -> prints what it would send
and exits 0, so the engine workflow never fails on notification problems.

State file is committed by the workflow alongside bets.js, so announcements
survive across CI runs and each bet is announced once per status.
"""

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

import engine

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, ".discord_posted.json")
CIRCUIT_TAG = {"czech": "CZE", "polish": "POL"}


def _fmt_start(ts, tzname):
    if not ts:
        return "start time unknown"
    tz = ZoneInfo(tzname) if ZoneInfo else timezone.utc
    d = datetime.fromtimestamp(ts, tz)
    return "starts " + d.strftime("%a %-I:%M %p").replace(" 0", " ")


def _fmt_bet(b, unit_size, tzname):
    tag = CIRCUIT_TAG.get(b.get("circuit"), "WTT")
    opp = b["playerB"] if b.get("pick") == b.get("playerA") else b["playerA"]
    return ("\U0001F3D3 **BET %.2fu ($%.0f) on %s @ %s** — vs %s · %s [%s] · %s"
            % (b["units"], b["units"] * unit_size, b["pick"], engine.am_odds(b["odds"]),
               opp, b.get("event", ""), tag, _fmt_start(b.get("startTime"), tzname)))


def _fmt_settle(b):
    net = engine.net_units(b)
    icon = "✅ WON" if b["status"] == "win" else \
           "❌ LOST" if b["status"] == "loss" else "↩ PUSH"
    return ("%s %+.2fu — %s @ %s (%s vs %s)"
            % (icon, net, b.get("pick"), engine.am_odds(b["odds"]),
               b.get("playerA"), b.get("playerB")))


def build_lines(data, announced, tzname="America/New_York"):
    """-> (lines to post, updated announced map). Pure — no I/O."""
    unit_size = data.get("settings", {}).get("unitSize", 10)
    lines, out = [], dict(announced)
    for b in data.get("bets", []):
        bid, status = str(b.get("id")), b.get("status")
        if status not in ("pending", "win", "loss", "push") or out.get(bid) == status:
            continue
        if status == "pending":
            lines.append(_fmt_bet(b, unit_size, tzname))
        elif out.get(bid) is not None or status != "pending":
            lines.append(_fmt_settle(b))
        out[bid] = status
    return lines, out


def post(webhook, content):
    req = urllib.request.Request(
        webhook, data=json.dumps({"content": content}).encode(),
        headers={"Content-Type": "application/json", "User-Agent": engine.UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        r.read()


def main():
    data = engine.load_bets_file()
    try:
        with open(STATE_FILE) as f:
            announced = json.load(f)
    except (OSError, ValueError):
        announced = {}
    tzname = os.environ.get("TT_TZ", "America/New_York")
    lines, announced = build_lines(data, announced, tzname)
    if not lines:
        print("discord: nothing new to announce")
        return
    webhook = os.environ.get("DISCORD_WEBHOOK", "").strip()
    if not webhook:
        print("discord: no DISCORD_WEBHOOK set; would have sent:")
        for ln in lines:
            print("  " + ln)
    else:
        chunk = ""
        for ln in lines:
            if len(chunk) + len(ln) > 1900:
                post(webhook, chunk)
                chunk = ""
            chunk += ln + "\n"
        if chunk:
            post(webhook, chunk)
        print("discord: announced %d update(s)" % len(lines))
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(announced, f, indent=1, sort_keys=True)
    os.replace(tmp, STATE_FILE)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # notifications must never break the engine run
        print("discord: failed: %s" % e)
        sys.exit(0)
