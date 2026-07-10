#!/usr/bin/env python3
"""
Czech amateur pipeline: Czech Liga Pro + TT Cup (the high-volume matches
betting sites price around the clock).

Data source: api.aiscore.com/v1/m/api/matches — one protobuf response per day
containing every table-tennis match (competitions, players, start times,
statuses, final scores, and — when the book has posted a line — a compact
odds block per match). Field map verified against a captured live response
on 2026-07-10 (tests/fixtures/matches_20260710.bin):

  response  = { 15: body }
  body      = { 1: competition*, 2: match*, 3: team* }
  competition = { 1: id, 5: name, 23: slug }
  team        = { 1: id, 6: name, 19: slug }
  match       = { 1: id, 4:{1: competition id}, 6:{1: home team id},
                  7:{1: away team id}, 15: start unixtime, 16: status id,
                  30:{7:{1: odds-set*}}, 111:{1..7: per-set scores, 8: final sets} }
  odds-set    = repeated string, market rows of 4:
                [handicap h, line, handicap a, "0"], [win h, "0", win a, "0"],
                [over, total line, under, "0"]
  status id   = 1 upcoming, 5x live, 100 ended

Pipeline per run: discovery -> Elo update from finals -> settle pending czech
bets by match id -> gate (both players rated >= MIN_RATED_MATCHES) -> odds ->
edge -> quarter-Kelly stake via engine.apply_edge (grade hard-capped at C, so
stakes are automatically halved and can never exceed 1u).

Politeness: the whole slate for a day is ONE request. Odds mostly ride along
in that response; per-match odds calls are a bounded fallback.
"""

import time
from datetime import datetime, timedelta

import elo
import engine

MATCHES_URL = "https://api.aiscore.com/v1/m/api/matches?lang=2&sport_id=11&date=%s&tz=%s"
CZECH_COMPS = ("czech liga pro", "tt cup")   # matched case-insensitively by name
CIRCUIT = "czech"
LOOKAHEAD_HOURS = 12       # bound discovery: only matches starting inside this window
MAX_CANDIDATES = 40        # hard cap on modeled matches per run
MAX_ODDS_FETCHES = 15      # per-match odds calls per run (fallback only)
MAX_DATE_FETCHES = 4       # matches-list requests per run (today, spillover, settlements)
GRADE_CAP = "C"            # every amateur pick is C until circuit ROI proves otherwise


def fetch_bytes(url):
    """Raw-bytes fetch (shares the engine's headers + browser fallback)."""
    return engine.fetch_api_bytes(url)


def _s(v):
    return v.decode("utf-8", "replace") if isinstance(v, bytes) else None


def _first_str(msg_bytes, fno=1):
    v = engine._pb_fields(msg_bytes).get(fno, [None])[0]
    return _s(v)


def _packed_varints(buf):
    out, i = [], 0
    while i < len(buf):
        x, shift = 0, 0
        while True:
            b = buf[i]; i += 1
            x |= (b & 0x7F) << shift
            if not b & 0x80:
                break
            shift += 7
        out.append(x)
    return out


def towin_odds(odds_sets):
    """Pick the to-win market out of the per-match odds rows.
    Signature: [odds_home, "0", odds_away, ...] with both odds > 1.005 —
    same detection the odds/list endpoint parser uses. -> (oh, oa) or None."""
    for vals in odds_sets:
        if len(vals) >= 3 and vals[1] == "0":
            try:
                oh, oa = float(vals[0]), float(vals[2])
            except ValueError:
                continue
            if oh > 1.005 and oa > 1.005:
                return oh, oa
    return None


def parse_matches(raw):
    """Protobuf day-slate response -> list of match dicts (all competitions;
    the caller filters to czech). Unknown/malformed blocks are skipped."""
    top = engine._pb_fields(raw)
    body = top.get(15, [None])[0]
    if not isinstance(body, bytes):
        return []
    inner = engine._pb_fields(body)

    comps = {}
    for b in inner.get(1, []):
        f = engine._pb_fields(b)
        cid, name = _s(f.get(1, [None])[0]), _s(f.get(5, [None])[0])
        if cid:
            comps[cid] = name or ""

    teams = {}
    for b in inner.get(3, []):
        f = engine._pb_fields(b)
        tid, name = _s(f.get(1, [None])[0]), _s(f.get(6, [None])[0])
        if tid:
            teams[tid] = name or ""

    matches = []
    for b in inner.get(2, []):
        f = engine._pb_fields(b)
        mid = _s(f.get(1, [None])[0])
        if not mid:
            continue
        comp_id = _first_str(f[4][0]) if f.get(4) else None
        home_id = _first_str(f[6][0]) if f.get(6) else None
        away_id = _first_str(f[7][0]) if f.get(7) else None
        start = f.get(15, [None])[0]
        status = f.get(16, [None])[0]
        ft = None
        if f.get(111):
            sf = engine._pb_fields(f[111][0])
            if sf.get(8):
                pair = _packed_varints(sf[8][0])
                if len(pair) >= 2:
                    ft = (pair[0], pair[1])
        odds = None
        blk = f.get(30, [None])[0]
        if isinstance(blk, bytes) and blk:
            of = engine._pb_fields(blk)
            if of.get(7):
                g = engine._pb_fields(of[7][0])
                sets = [[_s(x) or "" for x in engine._pb_fields(st).get(1, [])]
                        for st in g.get(1, [])]
                odds = towin_odds(sets)
        matches.append({
            "mid": mid,
            "comp": comps.get(comp_id, ""),
            "home": teams.get(home_id, ""),
            "away": teams.get(away_id, ""),
            "start": start if isinstance(start, int) else None,
            "status": status if isinstance(status, int) else None,
            "ft": ft,
            "odds": odds,
        })
    return matches


def is_czech(match):
    return (match["comp"] or "").strip().lower() in CZECH_COMPS


def is_singles(match):
    return "/" not in match["home"] and "/" not in match["away"]


def decided(match):
    return (match["status"] == 100 and match["ft"]
            and match["ft"][0] != match["ft"][1])


def update_elo(store, matches, tz):
    """Feed every decided czech singles final into the Elo store. Dedup is by
    match id inside the store, so refetching the same day is safe."""
    applied = 0
    for m in matches:
        if not (is_czech(m) and is_singles(m) and decided(m)):
            continue
        if not (m["home"] and m["away"]):
            continue
        date = datetime.fromtimestamp(m["start"], tz).strftime("%Y-%m-%d") \
            if m["start"] else "unknown"
        if elo.record_result(store, m["home"], m["away"],
                             m["ft"][0] > m["ft"][1], m["mid"], date):
            applied += 1
    return applied


def settle_bets(data, matches_by_id):
    """Settle pending czech bets from final scores, matched by match id."""
    settled = 0
    for b in data.get("bets", []):
        if b.get("status") != "pending" or b.get("circuit") != CIRCUIT:
            continue
        m = matches_by_id.get(b.get("matchId"))
        if not m or not decided(m):
            continue
        winner = m["home"] if m["ft"][0] > m["ft"][1] else m["away"]
        b["status"] = "win" if winner == b.get("pick") else "loss"
        b["notes"] = (b.get("notes", "") + " | %s won %d-%d (auto-settled)"
                      % (winner, m["ft"][0], m["ft"][1])).strip(" |")
        settled += 1
        engine.log("czech settled: %s vs %s -> %s won -> bet %s"
                   % (b.get("playerA"), b.get("playerB"), winner, b["status"].upper()))
    return settled


def dates_to_fetch(data, now):
    """Bounded list of YYYYMMDD date strings: today, tomorrow when the
    lookahead window crosses midnight, plus dates of pending czech bets that
    still need results. Never more than MAX_DATE_FETCHES."""
    dates = [now.strftime("%Y%m%d")]
    horizon = now + timedelta(hours=LOOKAHEAD_HOURS)
    if horizon.date() != now.date():
        dates.append(horizon.strftime("%Y%m%d"))
    for b in data.get("bets", []):
        if b.get("status") == "pending" and b.get("circuit") == CIRCUIT:
            d = (b.get("date") or "").replace("-", "")
            if len(d) == 8 and d not in dates:
                dates.append(d)
    return dates[:MAX_DATE_FETCHES]


def model_candidate(m, store, now, tz):
    """One upcoming czech match -> recommendation dict (engine rec shape,
    plus circuit/matchId). The Elo gate and grade cap live here."""
    date = datetime.fromtimestamp(m["start"], tz).strftime("%Y-%m-%d")
    ra, na = elo.rating(store, m["home"])
    rb, nb = elo.rating(store, m["away"])
    rec = {
        "id": "rec-cz-" + m["mid"],
        "date": date,
        "event": m["comp"],
        "circuit": CIRCUIT,
        "matchId": m["mid"],
        "playerA": m["home"], "playerB": m["away"],
        "myProbA": None,
        "marketProbA": None, "bestOdds": None, "edge": None,
        "rec": "", "units": 0, "pickName": None,
        "grade": GRADE_CAP,
        "reasoning": "Elo %d (n=%d) vs %d (n=%d)" % (round(ra), na, round(rb), nb),
    }
    if min(na, nb) < elo.MIN_RATED_MATCHES:
        rec["rec"] = ("NO BET (Elo data too thin: %d and %d rated matches, need %d)"
                      % (na, nb, elo.MIN_RATED_MATCHES))
        return rec, False
    prob = elo.win_prob(store, m["home"], m["away"])
    rec["myProbA"] = round(prob, 3)
    fav = m["home"] if prob >= 0.5 else m["away"]
    rec["rec"] = ("MODEL PICK: %s (%.0f%%) — odds not found; enter odds in app"
                  % (fav, max(prob, 1 - prob) * 100))
    return rec, True


def run(data, now, fetch_bytes_fn=None, store_path=None):
    """Full czech pipeline for one engine run.
    -> (recommendations, one-line summary). Network via fetch_bytes_fn so
    tests can inject fixture bytes."""
    fetch = fetch_bytes_fn or fetch_bytes
    tz = now.tzinfo
    tz_param = now.strftime("%z")
    tz_param = (tz_param[:3] + ":" + tz_param[3:]) if tz_param else "+00:00"

    all_matches = []
    for d in dates_to_fetch(data, now):
        try:
            time.sleep(engine.REQUEST_DELAY)
            all_matches.extend(parse_matches(fetch(MATCHES_URL % (d, tz_param))))
        except Exception as e:
            engine.log("warn: czech matches fetch failed for %s: %s" % (d, e))

    store = elo.load_store(store_path)
    n_elo = update_elo(store, all_matches, tz)
    elo.prune_processed(store, now)
    elo.save_store(store, store_path)

    by_id = {m["mid"]: m for m in all_matches}
    n_settled = settle_bets(data, by_id)

    now_ts = now.timestamp()
    candidates = sorted(
        (m for m in all_matches
         if is_czech(m) and is_singles(m) and m["status"] == 1
         and m["home"] and m["away"] and m["start"]
         and -900 <= m["start"] - now_ts <= LOOKAHEAD_HOURS * 3600),
        key=lambda m: m["start"])
    # one rec per match id even if a match shows up on two fetched dates
    seen, uniq = set(), []
    for m in candidates:
        if m["mid"] not in seen:
            seen.add(m["mid"])
            uniq.append(m)
    candidates = uniq[:MAX_CANDIDATES]

    recs, odds_budget, n_gated, n_bets = [], MAX_ODDS_FETCHES, 0, 0
    bankroll = engine.bankroll_units(data)
    for m in candidates:
        rec, bettable = model_candidate(m, store, now, tz)
        if not bettable:
            n_gated += 1
            recs.append(rec)
            continue
        odds = m["odds"]
        book = "aiscore line"
        if odds is None and odds_budget > 0:
            odds_budget -= 1
            time.sleep(engine.REQUEST_DELAY)
            try:
                got = engine.fetch_match_odds(m["mid"])
                if got:
                    odds, book = (got[0], got[1]), got[2]
            except Exception as e:
                engine.log("warn: czech odds fetch failed for %s: %s" % (m["mid"], e))
        if odds:
            engine.apply_edge(rec, odds[0], odds[1], book, bankroll)
            if rec["units"] > 0:
                n_bets += 1
        recs.append(rec)

    summary = ("%d match(es) scanned, %d elo update(s), %d settled, "
               "%d candidate(s) in %dh window, %d gated NO BET (thin Elo), %d BET rec(s)"
               % (len(all_matches), n_elo, n_settled, len(candidates),
                  LOOKAHEAD_HOURS, n_gated, n_bets))
    return recs, summary
