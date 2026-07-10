"""Elo update math — every expected rating computed by hand in the comments."""

import pytest

import elo


def test_first_meeting_of_equals_moves_16_points():
    # both 1500 -> expected 0.5 -> winner +32*0.5 = +16
    store = elo.empty_store()
    assert elo.record_result(store, "A", "B", True, "m1", "2026-07-10")
    assert store["players"]["A"]["r"] == 1516.0
    assert store["players"]["B"]["r"] == 1484.0
    assert store["players"]["A"]["n"] == 1
    assert store["players"]["B"]["n"] == 1


def test_underdog_win_hand_computed():
    # C (1500) beats A (1516):
    #   expected_C = 1/(1+10^((1516-1500)/400)) = 1/(1+10^0.04) = 0.476990...
    #   delta = 32*(1-0.476990) = 16.73632
    #   C -> 1516.74, A -> 1516 - 16.73632 = 1499.26 (2dp)
    store = elo.empty_store()
    elo.record_result(store, "A", "B", True, "m1", "2026-07-10")
    elo.record_result(store, "C", "A", True, "m2", "2026-07-10")
    assert store["players"]["C"]["r"] == pytest.approx(1516.74, abs=0.01)
    assert store["players"]["A"]["r"] == pytest.approx(1499.26, abs=0.01)


def test_expected_score_formula():
    # by hand: 1/(1+10^((1400-1600)/400)) = 1/(1+10^-0.5) = 1/1.3162278 = 0.759747
    assert elo.expected_score(1600, 1400) == pytest.approx(0.759747, abs=1e-6)
    assert elo.expected_score(1500, 1500) == 0.5


def test_win_prob_is_clamped():
    store = elo.empty_store()
    store["players"]["Giant"] = {"r": 2400, "n": 50}
    store["players"]["Novice"] = {"r": 1200, "n": 50}
    # raw expectation ~0.999 -> clamped to 0.95
    assert elo.win_prob(store, "Giant", "Novice") == 0.95
    assert elo.win_prob(store, "Novice", "Giant") == 0.05


def test_same_match_id_never_double_counts():
    store = elo.empty_store()
    assert elo.record_result(store, "A", "B", True, "m1", "2026-07-10")
    assert not elo.record_result(store, "A", "B", True, "m1", "2026-07-10")
    assert store["players"]["A"]["r"] == 1516.0
    assert store["players"]["A"]["n"] == 1


def test_min_rated_matches_gate():
    store = elo.empty_store()
    for i in range(elo.MIN_RATED_MATCHES - 1):
        elo.record_result(store, "A", "opp%d" % i, True, "m%d" % i, "2026-07-10")
    assert not elo.is_bettable(store, "A")          # 9 matches: still gated
    elo.record_result(store, "A", "opp-last", True, "m-last", "2026-07-10")
    assert elo.is_bettable(store, "A")              # 10 matches: bettable
    assert not elo.is_bettable(store, "opp0")       # 1 match: gated
    assert not elo.is_bettable(store, "stranger")   # unknown: gated


def test_store_round_trips_to_disk(tmp_path):
    path = str(tmp_path / "elo.json")
    store = elo.empty_store()
    elo.record_result(store, "A", "B", False, "m1", "2026-07-10")
    elo.save_store(store, path)
    again = elo.load_store(path)
    assert again["players"] == store["players"]
    assert again["processed"] == {"m1": "2026-07-10"}


def test_missing_or_corrupt_store_loads_empty(tmp_path):
    assert elo.load_store(str(tmp_path / "nope.json"))["players"] == {}
    p = tmp_path / "bad.json"
    p.write_text("{broken")
    assert elo.load_store(str(p))["players"] == {}


def test_processed_ids_are_pruned_after_window():
    from datetime import datetime
    store = elo.empty_store()
    elo.record_result(store, "A", "B", True, "old", "2026-06-01")
    elo.record_result(store, "A", "B", True, "new", "2026-07-09")
    n = elo.prune_processed(store, now=datetime(2026, 7, 10))
    assert n == 1
    assert "old" not in store["processed"] and "new" in store["processed"]
