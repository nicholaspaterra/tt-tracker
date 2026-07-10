#!/usr/bin/env python3
"""
TT Tracker — autonomous prediction engine.

Runs daily (via launchd or manually). Pipeline:
  1. Fetch ITTF world rankings (m.aiscore.com — server-rendered, no JS needed)
  2. Fetch top-N ranked players' pages: current points, last ~20 results, upcoming matches
  3. Find today's/tomorrow's WTT-sanctioned singles matches (Smash/Champions/Contender/etc.)
  4. Statistical model -> win probability per player (ranking points + recent form + H2H + fatigue)
  5. Write picks into bets.js "recommendations" -> dashboard shows them; you paste the odds
     from your sportsbook into the app and it computes edge + quarter-Kelly stake.

The model is a transparent heuristic (Bradley-Terry on ranking points, log-odds adjustments)
— NOT a guarantee. Probabilities are estimates; edge only exists relative to real odds.

Stdlib only. Python 3.9+. All numbers come from pages fetched at runtime — nothing invented.
"""

import json
import math
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta

# ---------------- config ----------------
BASE = "https://m.aiscore.com"
RANKINGS_URLS = [
    BASE + "/table-tennis/rankings/ittf-world-rankings",        # men's singles
    BASE + "/table-tennis/rankings/ittf-world-rankings-women",  # women's singles
]
TOP_N = 80                 # ranked players scanned per list (men + women)
REQUEST_DELAY = 1.2        # seconds between requests (be polite)
LOOKAHEAD_HOURS = 48       # treat matches starting within this window as "today's slate"
KEEP_REC_DAYS = 60         # prune recommendations older than this
MIN_EDGE = 0.06            # minimum edge to trigger a bet (6%)
AMATEUR_CIRCUITS = ("czech", "polish")  # bets settled by match id in czech.settle_bets
WTT_SINGLES = re.compile(r"(WTT|Smash|Champions|Contender|Feeder|World Cup|World Championship|Olympic)", re.I)
SINGLES_SUFFIX = re.compile(r",\s*(MS|WS)\s*$")   # aiscore tournament strings end ", MS"/", WS" for singles
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
HERE = os.path.dirname(os.path.abspath(__file__))
BETS_JS = os.path.join(HERE, "bets.js")
LOG_FILE = os.path.join(HERE, "engine_log.txt")
BACKUP_DIR = os.path.join(HERE, "backups")
MAX_BACKUPS = 30
VALID_GRADES = ("A", "B", "C")
VALID_STATUSES = ("pending", "win", "loss", "push")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# ---------------- io ----------------
def log(msg):
    line = "[%s] %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass

def _browser_fallback_ok(err):
    """aiscore 403s plain-Python clients on some networks. When the opt-in
    env flag is set, those requests retry through headless Chromium."""
    return (isinstance(err, urllib.error.HTTPError) and err.code == 403
            and os.environ.get("TT_BROWSER_FETCH") == "1")

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if _browser_fallback_ok(e):
            import browser_fetch
            return browser_fetch.fetch_text(url)
        raise

def fetch_api_bytes(url):
    """Raw-bytes fetch for the api.aiscore.com endpoints (protobuf)."""
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "*/*",
        "Origin": "https://m.aiscore.com", "Referer": "https://m.aiscore.com/",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if _browser_fallback_ok(e):
            import browser_fetch
            return browser_fetch.fetch_bytes(url)
        raise

def load_bets_file():
    with open(BETS_JS) as f:
        src = f.read()
    m = re.search(r"window\.BETS_FILE\s*=\s*(\{.*\});?\s*$", src, re.S)
    if not m:
        raise ValueError("could not parse bets.js")
    return json.loads(m.group(1))

def backup_bets_file(now=None):
    """Timestamped copy of bets.js into backups/ before this run writes anything.
    Keeps the newest MAX_BACKUPS. Never raises — a failed backup must not kill a run,
    but save_bets_file refuses to run if no backup was made this run (see main)."""
    try:
        if not os.path.exists(BETS_JS):
            return None
        os.makedirs(BACKUP_DIR, exist_ok=True)
        stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
        dest = os.path.join(BACKUP_DIR, "bets-%s.js" % stamp)
        if not os.path.exists(dest):
            shutil.copy2(BETS_JS, dest)
        names = sorted(f for f in os.listdir(BACKUP_DIR)
                       if f.startswith("bets-") and f.endswith(".js"))
        for f in names[:-MAX_BACKUPS]:
            os.remove(os.path.join(BACKUP_DIR, f))
        return dest
    except OSError as e:
        log("warn: bets.js backup failed: %s" % e)
        return None

def to_decimal_odds(v):
    """Odds in decimal (1.28) or American (-357 / +250) form -> decimal float, or
    None if not interpretable as odds. Decimal odds must exceed 1.005."""
    if isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(x) or math.isinf(x):
        return None
    if abs(x) >= 100:  # American
        return round(1 + (x / 100 if x > 0 else 100 / abs(x)), 4)
    return x if x > 1.005 else None

def validate_bet(b):
    """-> list of problems (empty means the entry is a usable bet)."""
    problems = []
    if not isinstance(b, dict):
        return ["not an object"]
    if not b.get("id"):
        problems.append("missing id")
    if not (isinstance(b.get("date"), str) and DATE_RE.match(b["date"])):
        problems.append("bad date %r" % (b.get("date"),))
    if to_decimal_odds(b.get("odds")) is None:
        problems.append("bad odds %r" % (b.get("odds"),))
    try:
        if not float(b.get("units")) > 0:
            problems.append("units must be > 0, got %r" % (b.get("units"),))
    except (TypeError, ValueError):
        problems.append("bad units %r" % (b.get("units"),))
    if b.get("grade") not in VALID_GRADES:
        problems.append("bad grade %r" % (b.get("grade"),))
    if b.get("status") not in VALID_STATUSES:
        problems.append("bad status %r" % (b.get("status"),))
    for k in ("pick", "playerA", "playerB"):
        if not (isinstance(b.get(k), str) and b[k].strip()):
            problems.append("missing %s" % k)
    return problems

def sanitize_bets(data):
    """Drop duplicate bet ids (first wins) and quarantine malformed entries into
    data['quarantine'] (nothing is ever silently deleted). Normalizes odds/units
    to numbers. -> (n_duplicates_dropped, n_quarantined)."""
    bets = data.get("bets")
    if not isinstance(bets, list):
        data["bets"] = []
        return 0, 0
    seen, keep, dupes, quarantined = set(), [], 0, 0
    for b in bets:
        problems = validate_bet(b)
        if problems:
            data.setdefault("quarantine", []).append(
                {"entry": b, "problems": problems})
            quarantined += 1
            continue
        if b["id"] in seen:
            dupes += 1
            continue
        seen.add(b["id"])
        b["odds"] = to_decimal_odds(b["odds"])
        b["units"] = round(float(b["units"]), 2)
        keep.append(b)
    data["bets"] = keep
    return dupes, quarantined

def save_bets_file(data):
    src = (
        "// TT Bet Tracker — canonical data file.\n"
        "// Updated by engine.py (recommendations) and by the app / Claude (bets).\n"
        "window.BETS_FILE = " + json.dumps(data, indent=2, ensure_ascii=False) + ";\n"
    )
    tmp = BETS_JS + ".tmp"
    with open(tmp, "w") as f:
        f.write(src)
    os.replace(tmp, BETS_JS)

# ---------------- parsing (structures verified against live pages 2026-07) ----------------
def parse_rankings(html):
    """-> list of {rank, name, points, url} from the rankData list."""
    players = []
    section = html.split('<ul class="rankData"', 1)
    if len(section) < 2:
        return players
    for li in section[1].split("<li")[1:]:
        rank = re.search(r'w-52"[^>]*>\s*(\d+)\s*<', li)
        href = re.search(r'href="(/table-tennis/player-[^"]+)"', li)
        name = re.search(r'teamName"[^>]*>([^<]+)<', li)
        pts = re.search(r'integral"[^>]*>\s*([\d,]+)\s*<', li)
        if rank and href and name and pts:
            players.append({
                "rank": int(rank.group(1)),
                "name": name.group(1).strip(),
                "points": int(pts.group(1).replace(",", "")),
                "url": BASE + href.group(1),
            })
    return players

def parse_player_page(html):
    """-> {rank, points, matches:[{iso, date, home, away, sh, sa, tournament, done}]}"""
    out = {"rank": None, "points": None, "matches": []}
    m = re.search(r"Current Rank</span>\s*<span[^>]*>\s*(\d+)", html)
    if m:
        out["rank"] = int(m.group(1))
    m = re.search(r"Current Points</span>\s*<span[^>]*>\s*([\d,]+)", html)
    if m:
        out["points"] = int(m.group(1).replace(",", ""))
    for block in html.split('itemtype="http://schema.org/SportsEvent"')[1:]:
        block = block.split("</li>", 1)[0]
        names = re.search(r'itemprop="name"\s+content="(.+?) vs (.+?)"', block)
        iso = re.search(r'itemprop="startDate"\s+content="([^"]+)"', block)
        desc = re.search(r'itemprop="description"\s+content="[^"]*? in the ([^"]+)"', block)
        mid = re.search(r'href="/table-tennis/match-[a-zA-Z0-9-]+/([a-zA-Z0-9]+)"', block)
        if not (names and iso):
            continue
        scores_div = re.search(r'class="scores[^"]*"(.*?)</div>', block, re.S)
        nums = re.findall(r">\s*(\d+)\s*<", scores_div.group(1)) if scores_div else []
        done = len(nums) >= 2
        out["matches"].append({
            "iso": iso.group(1),
            "date": iso.group(1)[:10],
            "home": names.group(1).strip(),
            "away": names.group(2).strip(),
            "sh": int(nums[0]) if done else None,
            "sa": int(nums[1]) if done else None,
            "tournament": desc.group(1).strip() if desc else "",
            "done": done,
            "mid": mid.group(1) if mid else None,
        })
    return out

# ---------------- odds (api.aiscore.com, protobuf response) ----------------
ODDS_URL = "https://api.aiscore.com/v1/m/api/match/odds/list?match_id=%s&code=54&platform=2"

def _pb_varint(buf, i):
    val, shift = 0, 0
    while True:
        b = buf[i]; i += 1
        val |= (b & 0x7F) << shift
        if not b & 0x80:
            return val, i
        shift += 7

def _pb_fields(buf):
    """Minimal protobuf walk -> {field_no: [bytes-or-int, ...]}"""
    fields, i = {}, 0
    while i < len(buf):
        key, i = _pb_varint(buf, i)
        fno, wire = key >> 3, key & 7
        if wire == 0:
            val, i = _pb_varint(buf, i)
        elif wire == 2:
            ln, i = _pb_varint(buf, i)
            val = buf[i:i + ln]; i += ln
        elif wire == 5:
            val = buf[i:i + 4]; i += 4
        elif wire == 1:
            val = buf[i:i + 8]; i += 8
        else:
            raise ValueError("wire type %d" % wire)
        fields.setdefault(fno, []).append(val)
    return fields

def _odds_set(msg_bytes):
    """odds-set message = repeated string values (field 1)."""
    vals = []
    for v in _pb_fields(msg_bytes).get(1, []):
        if isinstance(v, bytes):
            vals.append(v.decode("utf-8", "replace"))
    return vals

def fetch_match_odds(match_id):
    """-> (odds_home, odds_away, bookmaker) or None."""
    return parse_match_odds(fetch_api_bytes(ODDS_URL % match_id))

def parse_match_odds(raw):
    """odds/list protobuf response -> (odds_home, odds_away, bookmaker) or None.
    Response: field 15 = bookmaker block {1:handicap, 2:to-win, 3:totals, 4:book info}.
    Each market = {1:opening, 2:current, 4:closing} odds-sets. The to-win set looks like
    [home, "0"(draw), away, "0"] — no draws in table tennis, which is how we detect it.
    A response whose field 15 holds only the gambling disclaimer yields None."""
    for block in _pb_fields(raw).get(15, []):
        if not isinstance(block, bytes):
            continue
        markets = _pb_fields(block)
        book = "unknown"
        for info in markets.get(4, []):
            if isinstance(info, bytes):
                for s in _pb_fields(info).get(2, []):
                    if isinstance(s, bytes):
                        book = s.decode("utf-8", "replace")
        for fno in (1, 2, 3):
            for market in markets.get(fno, []):
                if not isinstance(market, bytes):
                    continue
                m = _pb_fields(market)
                # prefer current (2), else closing (4), else opening (1)
                for pref in (2, 4, 1):
                    for s in m.get(pref, []):
                        vals = _odds_set(s) if isinstance(s, bytes) else []
                        if len(vals) >= 3 and vals[1] == "0":  # to-win signature
                            try:
                                oh, oa = float(vals[0]), float(vals[2])
                            except ValueError:
                                continue
                            if oh > 1.005 and oa > 1.005:
                                return oh, oa, book
    return None

def _days_diff(d1, d2):
    a = datetime.strptime(d1, "%Y-%m-%d")
    b = datetime.strptime(d2, "%Y-%m-%d")
    return (a - b).days

def auto_log_bets(data, recs):
    """Log every BET recommendation as a pending bet (once per rec id)."""
    existing = set()
    for b in data.get("bets", []):
        if b.get("recId"):
            existing.add(b["recId"])
        m = re.search(r"\[rec:([^\]]+)\]", b.get("notes", ""))
        if m:
            existing.add(m.group(1))
    logged = 0
    for r in recs:
        if r.get("units", 0) <= 0 or not r.get("rec", "").startswith("BET") or r["id"] in existing:
            continue
        pick = r.get("pickName")
        if not pick:  # older recs carry the pick only inside the rec string
            m = re.search(r" on (.+?) @ ", r["rec"])
            pick = m.group(1) if m else None
        if not pick:
            continue
        bet = {
            "id": "bet-" + r["id"],
            "recId": r["id"],
            "date": r["date"],
            "startTime": r.get("startTime"),
            "event": r["event"],
            "playerA": r["playerA"], "playerB": r["playerB"],
            "pick": pick,
            "odds": r["bestOdds"], "units": r["units"], "grade": r["grade"],
            "status": "pending",
            "circuit": r.get("circuit", "wtt"),
            "notes": "auto-logged by engine [rec:%s]" % r["id"],
        }
        if r.get("matchId"):
            bet["matchId"] = r["matchId"]
        data["bets"].append(bet)
        logged += 1
    return logged

def auto_settle(data, pages, by_name):
    """Settle pending bets from completed results on the players' pages."""
    settled = 0
    for b in data.get("bets", []):
        if b.get("status") != "pending" or b.get("circuit") in AMATEUR_CIRCUITS:
            continue  # amateur bets settle by match id in czech.settle_bets
        result = None
        for nm in (b.get("playerA"), b.get("playerB")):
            if not nm:
                continue
            page = pages.get(nm)
            if page is None and nm in by_name:
                time.sleep(REQUEST_DELAY)
                try:
                    page = pages[nm] = parse_player_page(fetch(by_name[nm]["url"]))
                except Exception as e:
                    log("warn: settle fetch failed for %s: %s" % (nm, e))
                    continue
            if not page:
                continue
            for m in page["matches"]:
                if not m["done"]:
                    continue
                if {m["home"], m["away"]} == {b["playerA"], b["playerB"]}:
                    try:
                        dd = _days_diff(m["date"], b["date"])
                    except (ValueError, KeyError):
                        continue
                    if -1 <= dd <= 3:
                        winner = m["home"] if m["sh"] > m["sa"] else m["away"]
                        result = (winner, "%d-%d" % (m["sh"], m["sa"]))
                        break
            if result:
                break
        if result:
            b["status"] = "win" if result[0] == b.get("pick") else "loss"
            b["notes"] = (b.get("notes", "") + " | %s won %s (auto-settled)" % result).strip(" |")
            settled += 1
            log("settled: %s vs %s -> %s won %s -> bet %s" %
                (b["playerA"], b["playerB"], result[0], result[1], b["status"].upper()))
    return settled

def am_odds(d):
    """decimal -> American odds string (what US books display)."""
    if d < 1.005:
        return "—"
    return "+%d" % round((d - 1) * 100) if d >= 2 else "-%d" % round(100 / (d - 1))

def bankroll_units(data):
    net = 0.0
    for b in data.get("bets", []):
        if b.get("status") == "win":
            net += (b["odds"] - 1) * b["units"]
        elif b.get("status") == "loss":
            net -= b["units"]
    return data["settings"].get("startingBankrollUnits", 100) + net

def net_units(b):
    """Settled P&L of one bet in units (push/pending = 0)."""
    if b.get("status") == "win":
        return (b["odds"] - 1) * b["units"]
    if b.get("status") == "loss":
        return -b["units"]
    return 0.0

def roi_report(data):
    """ROI split by confidence grade AND by circuit (wtt vs czech), from settled
    bets only. Bets without a circuit label are WTT (pre-czech-era entries).
    -> {"byGrade": {...}, "byCircuit": {...}}; each row
       {bets, wins, losses, pushes, staked, net, roi} with roi as a fraction."""
    by_grade, by_circuit = {}, {}
    for b in data.get("bets", []):
        st = b.get("status")
        if st not in ("win", "loss", "push"):
            continue
        net = net_units(b)
        for key, table in ((b.get("grade", "?"), by_grade),
                           (b.get("circuit", "wtt"), by_circuit)):
            row = table.setdefault(key, {"bets": 0, "wins": 0, "losses": 0,
                                         "pushes": 0, "staked": 0.0, "net": 0.0})
            row["bets"] += 1
            row["staked"] += b["units"]
            row["net"] += net
            row["wins" if st == "win" else "losses" if st == "loss" else "pushes"] += 1
    for table in (by_grade, by_circuit):
        for row in table.values():
            row["staked"] = round(row["staked"], 2)
            row["net"] = round(row["net"], 2)
            row["roi"] = round(row["net"] / row["staked"], 4) if row["staked"] else 0.0
    return {"byGrade": by_grade, "byCircuit": by_circuit}

def apply_edge(rec, odds_home, odds_away, book, bankroll):
    """Vig-strip, edge, quarter-Kelly (cap 2u, C-grade halved). Mutates rec."""
    imp_h, imp_a = 1 / odds_home, 1 / odds_away
    novig_h = imp_h / (imp_h + imp_a)
    rec["marketProbA"] = round(novig_h, 3)
    edge_h = rec["myProbA"] - novig_h
    side_a = edge_h >= 0
    edge = abs(edge_h)
    rec["edge"] = round(edge, 3)
    p = rec["myProbA"] if side_a else 1 - rec["myProbA"]
    o = odds_home if side_a else odds_away
    name = rec["playerA"] if side_a else rec["playerB"]
    rec["bestOdds"] = o
    if edge >= MIN_EDGE:
        units = 0.25 * (p * o - 1) / (o - 1) * bankroll  # quarter-Kelly (bankroll in units)
        units = min(units, 2.0)                          # hard cap: nothing ever stakes > 2u
        if rec["grade"] == "C":
            units /= 2                                   # C-grade stakes half (max 1u)
        units = round(units, 2)
        if units > 0:
            rec["units"] = units
            rec["pickName"] = name
            rec["rec"] = "BET %.2fu on %s @ %s (%s)" % (units, name, am_odds(o), book)
            return
    rec["units"] = 0
    rec["pickName"] = None
    rec["rec"] = "NO BET (edge %.1f%% @ %s %s/%s)" % (edge * 100, book, am_odds(odds_home), am_odds(odds_away))

# ---------------- model ----------------
def completed_for(player_name, matches):
    """Completed matches, newest first, as (date, opponent, won)."""
    res = []
    for m in matches:
        if not m["done"]:
            continue
        if m["home"] == player_name:
            res.append((m["date"], m["away"], m["sh"] > m["sa"]))
        elif m["away"] == player_name:
            res.append((m["date"], m["home"], m["sa"] > m["sh"]))
    res.sort(reverse=True)
    return res

def model_match(pA, pB, dataA, dataB, now):
    """-> (probA, grade, reasoning). Transparent heuristic model."""
    ptsA, ptsB = float(pA["points"]), float(pB["points"])
    # Bradley-Terry on softened ranking points
    sA, sB = ptsA ** 0.75, ptsB ** 0.75
    base = sA / (sA + sB)
    base = min(max(base, 0.05), 0.95)
    logit = math.log(base / (1 - base))
    factors = ["rank pts %d vs %d -> base %.0f%%" % (ptsA, ptsB, base * 100)]

    # recent form: win rate over last 10 completed
    recA = completed_for(pA["name"], dataA["matches"])
    recB = completed_for(pB["name"], dataB["matches"])
    formA = sum(1 for _, _, w in recA[:10] if w) / max(len(recA[:10]), 1)
    formB = sum(1 for _, _, w in recB[:10] if w) / max(len(recB[:10]), 1)
    if recA[:10] and recB[:10]:
        logit += 1.2 * (formA - formB)
        factors.append("form L10: %.0f%% vs %.0f%%" % (formA * 100, formB * 100))

    # head-to-head from both players' visible histories
    h2h = [(d, w) for d, opp, w in recA if opp == pB["name"]]
    if len(h2h) >= 3:
        rate = sum(1 for _, w in h2h if w) / len(h2h)
        logit += 0.5 * (rate - 0.5) * 2
        factors.append("H2H %d/%d" % (sum(1 for _, w in h2h if w), len(h2h)))
    else:
        factors.append("H2H thin (%d)" % len(h2h))

    # fatigue: completed matches in the last 3 days
    cutoff = (now - timedelta(days=3)).strftime("%Y-%m-%d")
    fatA = sum(1 for d, _, _ in recA if d >= cutoff)
    fatB = sum(1 for d, _, _ in recB if d >= cutoff)
    if fatA != fatB:
        logit -= 0.10 * (fatA - fatB)
        factors.append("fatigue %d vs %d matches/3d" % (fatA, fatB))

    prob = 1 / (1 + math.exp(-logit))
    prob = min(max(prob, 0.05), 0.95)

    # data-quality grade (H2H thin or <5 recent matches caps at C — house rule)
    if len(h2h) < 3 or min(len(recA), len(recB)) < 5:
        grade = "C"
    elif len(h2h) >= 5 and min(len(recA), len(recB)) >= 10:
        grade = "A"
    else:
        grade = "B"
    return prob, grade, "; ".join(factors)

# ---------------- main ----------------
def trim_log(max_lines=1000):
    try:
        with open(LOG_FILE) as f:
            lines = f.readlines()
        if len(lines) > max_lines:
            with open(LOG_FILE, "w") as f:
                f.writelines(lines[-max_lines:])
    except OSError:
        pass

def main():
    now = datetime.now().astimezone()
    trim_log()
    log("engine run started")
    try:
        data = load_bets_file()
    except (ValueError, json.JSONDecodeError) as e:
        # Never write over a bets.js we could not read — that file is the bet log.
        log("ERROR: bets.js unreadable (%s). Not touching it. "
            "Restore the latest copy from backups/ and re-run." % e)
        sys.exit(1)
    backup_bets_file(now)
    data.setdefault("recommendations", [])
    n_dupes, n_quarantined = sanitize_bets(data)
    if n_dupes or n_quarantined:
        log("bet log sanitized: %d duplicate(s) dropped, %d malformed entrie(s) quarantined"
            % (n_dupes, n_quarantined))

    lists = []
    for url in RANKINGS_URLS:
        try:
            lst = parse_rankings(fetch(url))
        except Exception as e:
            log("warn: rankings fetch failed (%s): %s" % (url, e))
            lst = []
        if lst:
            lists.append(lst)
        time.sleep(REQUEST_DELAY)
    if not lists:
        log("ERROR: all rankings pages failed (site layout may have changed)")
        sys.exit(1)
    by_name = {p["name"]: p for lst in lists for p in lst}
    scan = [p for lst in lists for p in lst[:TOP_N]]
    log("rankings parsed: %d players across %d lists; scanning %d" % (len(by_name), len(lists), len(scan)))

    # scan top-N player pages (men + women) for upcoming WTT singles matches
    pages, upcoming = {}, {}
    for p in scan:
        if p["name"] in pages:
            continue
        time.sleep(REQUEST_DELAY)
        try:
            pages[p["name"]] = parse_player_page(fetch(p["url"]))
        except Exception as e:
            log("warn: fetch failed for %s: %s" % (p["name"], e))
            continue
        for m in pages[p["name"]]["matches"]:
            if m["done"] or not m["tournament"]:
                continue
            if not (WTT_SINGLES.search(m["tournament"]) and SINGLES_SUFFIX.search(m["tournament"])):
                continue
            try:
                start = datetime.fromisoformat(m["iso"])
            except ValueError:
                continue
            hours = (start - now).total_seconds() / 3600
            if -3 <= hours <= LOOKAHEAD_HOURS:
                key = "|".join(sorted([m["home"], m["away"]]))
                upcoming[key] = m
    log("upcoming WTT singles matches found: %d" % len(upcoming))

    # model each match
    new_recs = []
    for key, m in upcoming.items():
        a, b = m["home"], m["away"]
        if a not in by_name or b not in by_name:
            log("skip %s vs %s: player not in rankings table" % (a, b))
            continue
        for nm in (a, b):  # make sure both players' pages are loaded
            if nm not in pages:
                time.sleep(REQUEST_DELAY)
                try:
                    pages[nm] = parse_player_page(fetch(by_name[nm]["url"]))
                except Exception as e:
                    log("warn: fetch failed for %s: %s" % (nm, e))
        if a not in pages or b not in pages:
            continue
        prob, grade, why = model_match(by_name[a], by_name[b], pages[a], pages[b], now)
        fav = a if prob >= 0.5 else b
        try:
            start_ts = int(datetime.fromisoformat(m["iso"]).timestamp())
        except (ValueError, KeyError, OSError):
            start_ts = None
        rec_id = "rec-" + m["date"].replace("-", "") + "-" + re.sub(r"[^a-z0-9]+", "-", key.lower())[:40]
        rec = {
            "id": rec_id,
            "date": m["date"],
            "startTime": start_ts,
            "event": m["tournament"],
            "circuit": "wtt",
            "playerA": a, "playerB": b,
            "myProbA": round(prob, 3),
            "marketProbA": None, "bestOdds": None, "edge": None,
            "rec": "MODEL PICK: %s (%.0f%%) — odds not found; enter odds in app" % (fav, max(prob, 1 - prob) * 100),
            "units": 0, "grade": grade,
            "reasoning": why,
        }
        if m.get("mid"):
            rec["matchId"] = m["mid"]
        # auto-pull odds and compute edge + stake
        if m.get("mid"):
            time.sleep(REQUEST_DELAY)
            try:
                odds = fetch_match_odds(m["mid"])
                if odds:
                    apply_edge(rec, odds[0], odds[1], odds[2], bankroll_units(data))
                    rec["reasoning"] += " | odds pulled %s" % now.strftime("%H:%M")
                else:
                    log("no odds posted yet for %s vs %s" % (a, b))
            except Exception as e:
                log("warn: odds fetch failed for %s vs %s: %s" % (a, b, e))
        new_recs.append(rec)
        log("modeled %s vs %s -> %.0f%% / %s / grade %s" % (a, b, prob * 100, rec["rec"], grade))

    # Czech amateur pipeline (Liga Pro / TT Cup): separate Elo model + settlement.
    # A czech failure must never take down the WTT run.
    czech_recs = []
    try:
        import czech
        czech_recs, cz_summary = czech.run(data, now)
        log("czech pipeline: %s" % cz_summary)
    except Exception as e:
        log("warn: czech pipeline failed: %s" % e)
    new_recs.extend(czech_recs)

    # merge: replace same-id recs, prune old ones
    cutoff = (now - timedelta(days=KEEP_REC_DAYS)).strftime("%Y-%m-%d")
    ids = {r["id"] for r in new_recs}
    data["recommendations"] = (
        [r for r in data["recommendations"] if r["id"] not in ids and r.get("date", "9999") >= cutoff]
        + new_recs
    )

    # settle finished bets, then log new qualifying ones
    n_settled = auto_settle(data, pages, by_name)
    n_logged = auto_log_bets(data, new_recs)

    save_bets_file(data)
    rep = roi_report(data)
    for label, table in (("grade", rep["byGrade"]), ("circuit", rep["byCircuit"])):
        for key in sorted(table):
            r = table[key]
            log("ROI by %s %s: %dW-%dL-%dP staked %.2fu net %+.2fu roi %+.1f%%"
                % (label, key, r["wins"], r["losses"], r["pushes"],
                   r["staked"], r["net"], r["roi"] * 100))
    log("run summary: %d rec(s), %d bet(s) auto-logged, %d bet(s) auto-settled"
        % (len(new_recs), n_logged, n_settled))
    if not new_recs:
        log("no WTT singles matches in the next %dh" % LOOKAHEAD_HOURS)

if __name__ == "__main__":
    main()
