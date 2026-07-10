#!/usr/bin/env python3
"""
Self-maintained Elo rating store for amateur circuits (Czech Liga Pro / TT Cup).

These players are not in ITTF rankings, so the engine's ranking-points model
cannot price them. Instead we bootstrap ratings purely from scraped final
results and persist them to elo.json next to this file.

Cold-start honesty: everyone starts at START (1500). A player below
MIN_RATED_MATCHES completed results is UNBETTABLE — the pipeline must output
NO BET for their matches. Ratings only firm up as results accumulate; for the
first days that correctly means few or zero amateur bets.

Stdlib only. All writes are atomic (tmp + os.replace).
"""

import json
import math
import os
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ELO_FILE = os.path.join(HERE, "elo.json")

K = 32                    # classic Elo K-factor; amateur results are noisy, keep standard
START = 1500.0
MIN_RATED_MATCHES = 10    # below this a player is unbettable (NO BET)
PROCESSED_KEEP_DAYS = 14  # dedup window for already-counted match ids
PROB_CLAMP = 0.05         # model probabilities stay inside [0.05, 0.95]


def empty_store():
    return {"version": 1, "k": K, "start": START, "players": {}, "processed": {}}


def load_store(path=None):
    """Load elo.json; a missing or unreadable file yields a fresh empty store
    (ratings can always be rebuilt from results, unlike the bet log)."""
    path = path or ELO_FILE
    try:
        with open(path) as f:
            store = json.load(f)
    except (OSError, ValueError):
        return empty_store()
    if not isinstance(store, dict) or not isinstance(store.get("players"), dict):
        return empty_store()
    store.setdefault("processed", {})
    return store


def save_store(store, path=None):
    path = path or ELO_FILE
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(store, f, indent=1, ensure_ascii=False, sort_keys=True)
    os.replace(tmp, path)


def rating(store, name):
    """-> (rating, rated_match_count) — (START, 0) for unknown players."""
    p = store["players"].get(name)
    if not p:
        return START, 0
    return p.get("r", START), p.get("n", 0)


def expected_score(ra, rb):
    """Classic Elo expectation for A vs B."""
    return 1.0 / (1.0 + 10.0 ** ((rb - ra) / 400.0))


def is_bettable(store, name, min_matches=MIN_RATED_MATCHES):
    return rating(store, name)[1] >= min_matches


def win_prob(store, name_a, name_b):
    """Model win probability for A, clamped away from certainty."""
    ra, _ = rating(store, name_a)
    rb, _ = rating(store, name_b)
    p = expected_score(ra, rb)
    return min(max(p, PROB_CLAMP), 1 - PROB_CLAMP)


def record_result(store, home, away, home_won, match_id, date):
    """Apply one final result. Dedups by match_id so re-fetching the same day
    never double-counts. -> True if the result was applied."""
    if not (home and away and match_id):
        return False
    if match_id in store["processed"]:
        return False
    players = store["players"]
    ph = players.setdefault(home, {"r": START, "n": 0})
    pa = players.setdefault(away, {"r": START, "n": 0})
    exp_home = expected_score(ph["r"], pa["r"])
    score_home = 1.0 if home_won else 0.0
    delta = K * (score_home - exp_home)
    ph["r"] = round(ph["r"] + delta, 2)
    pa["r"] = round(pa["r"] - delta, 2)
    ph["n"] += 1
    pa["n"] += 1
    ph["last"] = pa["last"] = date
    store["processed"][match_id] = date
    return True


def prune_processed(store, now=None, keep_days=PROCESSED_KEEP_DAYS):
    """Drop processed-match ids older than the dedup window (results that old
    are no longer refetched, so the ids serve no purpose)."""
    cutoff = ((now or datetime.now()) - timedelta(days=keep_days)).strftime("%Y-%m-%d")
    stale = [mid for mid, d in store["processed"].items()
             if not isinstance(d, str) or d < cutoff]
    for mid in stale:
        del store["processed"][mid]
    return len(stale)
