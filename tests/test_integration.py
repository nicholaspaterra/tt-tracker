"""Full engine.main() runs with the network mocked at the urllib level.
Covers the real wiring: rankings scrape -> player pages -> odds -> model ->
czech pipeline -> bets.js write -> auto-log -> auto-settle on a later run."""

import io
import json
import re
import urllib.request
from datetime import datetime, timedelta

import pytest

import czech
import elo
import engine
import pbenc
from conftest import fresh_data


def rankings_html(players):
    rows = "".join(
        '<li><span class="w-52"> %d </span>'
        '<a href="/table-tennis/player-%s/x%d">'
        '<span class="teamName">%s</span></a>'
        '<span class="integral"> %s </span></li>'
        % (i + 1, re.sub(r"[^a-z]+", "-", name.lower()), i + 1, name,
           format(pts, ","))
        for i, (name, pts) in enumerate(players))
    return '<html><ul class="rankData">%s</ul></html>' % rows


def event_block(home, away, iso, tournament, mid, score=None):
    scores = ('<div class="scores">'
              '<span> %d </span><span> %d </span></div>' % score) if score else ""
    return ('<li itemtype="http://schema.org/SportsEvent">'
            '<meta itemprop="name" content="%s vs %s">'
            '<meta itemprop="startDate" content="%s">'
            '<meta itemprop="description" content="%s vs %s in the %s">'
            '<a href="/table-tennis/match-x/%s"></a>%s</li>'
            % (home, away, iso, home, away, tournament, mid, scores))


def player_html(rank, points, events):
    return ('<html><span>Current Rank</span> <span> %d </span>'
            '<span>Current Points</span> <span> %s </span>%s</html>'
            % (rank, format(points, ","), "".join(events)))


class FakeResponse(io.BytesIO):
    status = 200
    headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def wired_site(tmp_store, no_sleep, monkeypatch):
    """A miniature aiscore: 2 ranked players with one WTT match tomorrow
    (odds posted), plus a czech slate with a rated pairing and a line."""
    now = datetime.now().astimezone()
    iso = (now + timedelta(hours=20)).strftime("%Y-%m-%dT%H:%M:%S%z")
    iso = iso[:-2] + ":" + iso[-2:]

    upcoming = event_block("Alpha One", "Beta Two", iso,
                           "WTT Champions Testville, MS", "wtt1")
    history_a = [event_block("Alpha One", "Beta Two",
                             (now - timedelta(days=30 + i)).strftime("%Y-%m-%dT10:00:00+00:00"),
                             "WTT Contender Oldtown, MS", "h%d" % i,
                             score=(3, 1)) for i in range(6)]
    history_b = [event_block("Beta Two", "Gamma Three",
                             (now - timedelta(days=30 + i)).strftime("%Y-%m-%dT10:00:00+00:00"),
                             "WTT Contender Oldtown, MS", "hb%d" % i,
                             score=(0, 3)) for i in range(6)]
    pages = {
        "x1": player_html(1, 12000, history_a + [upcoming]),
        "x2": player_html(2, 9000, history_b + [upcoming]),
    }
    cz_ts = int(now.timestamp()) + 3600
    cz_raw = pbenc.matches_response(
        [pbenc.competition("c1", "Czech Liga Pro")],
        [pbenc.team("t1", "Karel"), pbenc.team("t2", "Milos")],
        [pbenc.match("czm1", "c1", "t1", "t2", cz_ts, 1,
                     towin=["2.4", "0", "1.55", "0"])])
    store = elo.empty_store()
    store["players"] = {"Karel": {"r": 1600.0, "n": 12},
                        "Milos": {"r": 1400.0, "n": 12}}
    elo.save_store(store, str(tmp_store / "elo.json"))
    monkeypatch.setattr(elo, "ELO_FILE", str(tmp_store / "elo.json"))

    state = {"pages": pages, "settle": False}

    def fake_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "rankings" in url:
            body = rankings_html([("Alpha One", 12000), ("Beta Two", 9000)])
        elif "/player-" in url:
            pid = url.rsplit("/", 1)[1]
            body = state["pages"][pid]
        elif "odds/list" in url:
            return FakeResponse(pbenc.odds_list_response(
                ["1.30", "0", "3.40", "0"], book="bet365"))
        elif "api/matches" in url:
            return FakeResponse(cz_raw)
        else:
            raise AssertionError("unexpected URL fetched: " + url)
        return FakeResponse(body.encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    engine.save_bets_file(fresh_data())
    return state, now


def test_full_run_models_logs_and_persists(wired_site):
    engine.main()
    data = engine.load_bets_file()

    wtt = [r for r in data["recommendations"] if r.get("circuit") == "wtt"]
    cz = [r for r in data["recommendations"] if r.get("circuit") == "czech"]
    assert len(wtt) == 1 and len(cz) == 1
    # WTT: model favours Alpha One (higher points + form); odds 1.30/3.40 are
    # posted, so the rec must be fully priced (edge computed, some decision made)
    assert wtt[0]["marketProbA"] is not None
    assert wtt[0]["edge"] is not None
    # Czech: Elo 1600 v 1400 with a 2.40/1.55 line -> C-grade 1.00u bet
    # (hand math in test_czech.py)
    assert cz[0]["units"] == 1.00 and cz[0]["grade"] == "C"

    logged = {b["id"]: b for b in data["bets"]}
    assert "bet-rec-cz-czm1" in logged
    assert logged["bet-rec-cz-czm1"]["circuit"] == "czech"
    # every auto-logged bet passes the log validator
    assert all(engine.validate_bet(b) == [] for b in data["bets"])
    # a pre-write backup exists
    import os
    assert os.listdir(engine.BACKUP_DIR)


def test_second_run_settles_the_wtt_bet_from_final_score(wired_site):
    state, now = wired_site
    engine.main()
    data = engine.load_bets_file()
    pending_wtt = [b for b in data["bets"] if b.get("circuit") == "wtt"
                   and b["status"] == "pending"]
    if not pending_wtt:  # the WTT rec may be NO BET depending on the edge; force one
        data["bets"].append({
            "id": "bet-manual", "date": now.strftime("%Y-%m-%d"),
            "event": "WTT Champions Testville, MS",
            "playerA": "Alpha One", "playerB": "Beta Two", "pick": "Alpha One",
            "odds": 1.30, "units": 1.0, "grade": "B", "status": "pending",
            "circuit": "wtt", "notes": ""})
        engine.save_bets_file(data)
    # the match finishes 3-1 to Alpha One and shows up on both player pages
    done = event_block("Alpha One", "Beta Two",
                       now.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                       "WTT Champions Testville, MS", "wtt1", score=(3, 1))
    state["pages"]["x1"] = player_html(1, 12000, [done])
    state["pages"]["x2"] = player_html(2, 9000, [done])
    engine.main()
    data = engine.load_bets_file()
    wtt_bets = [b for b in data["bets"] if b.get("circuit") == "wtt"]
    assert wtt_bets and all(b["status"] == "win" for b in wtt_bets)
