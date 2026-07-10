"""Czech amateur pipeline end-to-end with mocked network:
discovery -> Elo rating -> gate -> odds -> edge -> stake, plus settlement,
grade cap, auto-log integration, and cold-start behavior.

All numeric expectations are computed by hand in the comments."""

from datetime import datetime, timezone

import pytest

import czech
import elo
import engine
import pbenc
from conftest import fresh_data

NOW = datetime(2026, 7, 10, 10, 0, 0, tzinfo=timezone.utc)
TS = int(NOW.timestamp())

COMPS = [pbenc.competition("c1", "Czech Liga Pro"),
         pbenc.competition("c2", "TT Cup"),
         pbenc.competition("c3", "TT Elite Series"),
         pbenc.competition("c9", "WTT Feeder Somewhere, MS")]
TEAMS = [pbenc.team("t1", "Alpha"), pbenc.team("t2", "Beta"),
         pbenc.team("t3", "Gamma"), pbenc.team("t4", "Delta"),
         pbenc.team("t5", "Echo"), pbenc.team("t6", "Foxtrot"),
         pbenc.team("t7", "Duo One/Duo Two"), pbenc.team("t8", "Solo")]


def response(matches):
    return pbenc.matches_response(COMPS, TEAMS, matches)


def seeded_store_path(tmp_path):
    """Alpha 1600 / Beta 1400, both with 12 rated matches (bettable)."""
    path = str(tmp_path / "elo.json")
    store = elo.empty_store()
    store["players"] = {"Alpha": {"r": 1600.0, "n": 12},
                        "Beta": {"r": 1400.0, "n": 12}}
    elo.save_store(store, path)
    return path


def run(data, raw, store_path, monkeypatch=None, odds_result=None):
    if monkeypatch is not None:
        monkeypatch.setattr(engine, "fetch_match_odds", lambda mid: odds_result)
    return czech.run(data, NOW, fetch_bytes_fn=lambda url: raw,
                     store_path=store_path)


class TestFullBetFlow:
    def test_rated_pair_with_posted_line_produces_a_half_stake_c_bet(
            self, tmp_path, no_sleep):
        # Elo 1600 vs 1400 -> p(Alpha) = 1/(1+10^-0.5) = 0.759747
        # line 2.40/1.55 -> imp 0.416667/0.645161, novig_h = 0.392405
        # edge = 0.759747-0.392405 = 0.367342 >= 6%
        # quarter-Kelly = 0.25*(0.759747*2.4-1)/1.4*100 = 14.70u -> cap 2.0
        # grade C (hard amateur cap) -> stake 1.00
        raw = response([pbenc.match("m1", "c1", "t1", "t2", TS + 3600, 1,
                                    towin=["2.4", "0", "1.55", "0"])])
        recs, summary = run(fresh_data(), raw, seeded_store_path(tmp_path))
        assert len(recs) == 1
        r = recs[0]
        assert r["circuit"] == "czech"
        assert r["matchId"] == "m1"
        assert r["grade"] == "C"
        assert r["myProbA"] == 0.76          # 0.759747 rounded
        assert r["units"] == 1.00
        assert r["pickName"] == "Alpha"
        assert r["rec"].startswith("BET 1.00u on Alpha")
        assert "1 BET rec(s)" in summary

    def test_grade_is_capped_at_c_no_matter_how_rich_the_data(
            self, tmp_path, no_sleep):
        path = str(tmp_path / "elo.json")
        store = elo.empty_store()
        store["players"] = {"Alpha": {"r": 1600.0, "n": 500},
                            "Beta": {"r": 1400.0, "n": 500}}
        elo.save_store(store, path)
        raw = response([pbenc.match("m1", "c1", "t1", "t2", TS + 3600, 1,
                                    towin=["2.4", "0", "1.55", "0"])])
        recs, _ = run(fresh_data(), raw, path)
        assert recs[0]["grade"] == "C"

    def test_odds_endpoint_fallback_when_no_embedded_line(
            self, tmp_path, no_sleep, monkeypatch):
        raw = response([pbenc.match("m1", "c1", "t1", "t2", TS + 3600, 1)])
        recs, _ = run(fresh_data(), raw, seeded_store_path(tmp_path),
                      monkeypatch, odds_result=(2.4, 1.55, "bet365"))
        assert recs[0]["units"] == 1.00
        assert "(bet365)" in recs[0]["rec"]

    def test_no_line_anywhere_means_model_pick_and_no_stake(
            self, tmp_path, no_sleep, monkeypatch):
        raw = response([pbenc.match("m1", "c1", "t1", "t2", TS + 3600, 1)])
        recs, _ = run(fresh_data(), raw, seeded_store_path(tmp_path),
                      monkeypatch, odds_result=None)
        assert recs[0]["units"] == 0
        assert recs[0]["rec"].startswith("MODEL PICK")


class TestGates:
    def test_min_rated_matches_gate_outputs_no_bet(self, tmp_path, no_sleep):
        # fresh store: everyone unrated -> NO BET even with a juicy line posted
        raw = response([pbenc.match("m2", "c1", "t3", "t4", TS + 3600, 1,
                                    towin=["3.0", "0", "1.3", "0"])])
        recs, _ = run(fresh_data(), raw, str(tmp_path / "elo.json"))
        assert len(recs) == 1
        assert recs[0]["units"] == 0
        assert "NO BET" in recs[0]["rec"]
        assert "too thin" in recs[0]["rec"]

    def test_nine_rated_matches_is_still_gated(self, tmp_path, no_sleep):
        path = str(tmp_path / "elo.json")
        store = elo.empty_store()
        store["players"] = {"Gamma": {"r": 1550.0, "n": 9},
                            "Delta": {"r": 1450.0, "n": 20}}
        elo.save_store(store, path)
        raw = response([pbenc.match("m2", "c1", "t3", "t4", TS + 3600, 1,
                                    towin=["2.0", "0", "1.8", "0"])])
        recs, _ = run(fresh_data(), raw, path)
        assert recs[0]["units"] == 0 and "too thin" in recs[0]["rec"]

    def test_cold_start_produces_zero_bets(self, tmp_path, no_sleep):
        # day one: plenty of matches, empty Elo store -> all NO BET, no stake
        ms = [pbenc.match("m%d" % i, "c1", "t3", "t4", TS + 3600 + i * 60, 1,
                          towin=["2.0", "0", "1.8", "0"]) for i in range(10)]
        recs, summary = run(fresh_data(), response(ms), str(tmp_path / "e.json"))
        assert all(r["units"] == 0 for r in recs)
        assert "0 BET rec(s)" in summary

    def test_doubles_are_skipped_entirely(self, tmp_path, no_sleep):
        raw = response([
            pbenc.match("md", "c1", "t7", "t8", TS + 3600, 1),          # doubles
            pbenc.match("mf", "c1", "t7", "t8", TS - 7200, 100, ft=(3, 0)),
        ])
        path = str(tmp_path / "elo.json")
        recs, _ = run(fresh_data(), raw, path)
        assert recs == []                                # not a candidate
        assert elo.load_store(path)["players"] == {}     # not rated either

    def test_non_czech_and_out_of_window_matches_are_ignored(
            self, tmp_path, no_sleep):
        raw = response([
            pbenc.match("mw", "c9", "t1", "t2", TS + 3600, 1),            # WTT
            pbenc.match("mo", "c1", "t1", "t2",
                        TS + (czech.LOOKAHEAD_HOURS + 2) * 3600, 1),      # too far out
            pbenc.match("ml", "c1", "t1", "t2", TS - 3600, 55),           # live
        ])
        recs, _ = run(fresh_data(), raw, seeded_store_path(tmp_path))
        assert recs == []

    def test_candidate_count_is_bounded(self, tmp_path, no_sleep):
        ms = [pbenc.match("m%d" % i, "c1", "t3", "t4", TS + 3600 + i, 1)
              for i in range(czech.MAX_CANDIDATES + 25)]
        recs, _ = run(fresh_data(), response(ms), str(tmp_path / "e.json"))
        assert len(recs) == czech.MAX_CANDIDATES


class TestEloBootstrap:
    def test_finished_finals_feed_the_store(self, tmp_path, no_sleep):
        raw = response([pbenc.match("mf", "c2", "t5", "t6", TS - 7200, 100,
                                    ft=(3, 1))])
        path = str(tmp_path / "elo.json")
        _, summary = run(fresh_data(), raw, path)
        store = elo.load_store(path)
        # equals, Echo won: 1500+16 / 1500-16 (hand math, see test_elo)
        assert store["players"]["Echo"] == {"r": 1516.0, "n": 1, "last": "2026-07-10"}
        assert store["players"]["Foxtrot"]["r"] == 1484.0
        assert "1 elo update(s)" in summary

    def test_refetching_the_same_day_never_double_counts(self, tmp_path, no_sleep):
        raw = response([pbenc.match("mf", "c2", "t5", "t6", TS - 7200, 100,
                                    ft=(3, 1))])
        path = str(tmp_path / "elo.json")
        run(fresh_data(), raw, path)
        run(fresh_data(), raw, path)  # second engine run, same results online
        store = elo.load_store(path)
        assert store["players"]["Echo"]["n"] == 1
        assert store["players"]["Echo"]["r"] == 1516.0

    def test_undecided_or_unfinished_matches_do_not_rate(self, tmp_path, no_sleep):
        raw = response([
            pbenc.match("mu", "c1", "t5", "t6", TS - 3600, 100, ft=(0, 0)),  # void
            pbenc.match("ml", "c1", "t5", "t6", TS - 1800, 51, ft=(1, 0)),   # live
        ])
        path = str(tmp_path / "elo.json")
        run(fresh_data(), raw, path)
        assert elo.load_store(path)["players"] == {}


class TestSettlement:
    def pending_bet(self, pick):
        return {"id": "bet-rec-cz-m4", "recId": "rec-cz-m4",
                "date": "2026-07-09", "event": "Czech Liga Pro",
                "playerA": "Alpha", "playerB": "Beta", "pick": pick,
                "odds": 1.8, "units": 1.0, "grade": "C", "status": "pending",
                "circuit": "czech", "matchId": "m4", "notes": ""}

    def test_pending_czech_bet_settles_win_by_match_id(self, tmp_path, no_sleep):
        data = fresh_data()
        data["bets"] = [self.pending_bet("Alpha")]
        raw = response([pbenc.match("m4", "c1", "t1", "t2", TS - 7200, 100,
                                    ft=(3, 2))])
        _, summary = run(data, raw, str(tmp_path / "e.json"))
        assert data["bets"][0]["status"] == "win"
        assert "Alpha won 3-2" in data["bets"][0]["notes"]
        assert "1 settled" in summary

    def test_pending_czech_bet_settles_loss(self, tmp_path, no_sleep):
        data = fresh_data()
        data["bets"] = [self.pending_bet("Beta")]
        raw = response([pbenc.match("m4", "c1", "t1", "t2", TS - 7200, 100,
                                    ft=(3, 2))])
        run(data, raw, str(tmp_path / "e.json"))
        assert data["bets"][0]["status"] == "loss"

    def test_unfinished_match_leaves_bet_pending(self, tmp_path, no_sleep):
        data = fresh_data()
        data["bets"] = [self.pending_bet("Alpha")]
        raw = response([pbenc.match("m4", "c1", "t1", "t2", TS - 600, 52,
                                    ft=(1, 1))])
        run(data, raw, str(tmp_path / "e.json"))
        assert data["bets"][0]["status"] == "pending"

    def test_settlement_dates_are_fetched_for_old_pending_bets(
            self, tmp_path, no_sleep):
        data = fresh_data()
        data["bets"] = [self.pending_bet("Alpha")]
        dates = czech.dates_to_fetch(data, NOW)
        assert "20260710" in dates       # today
        assert "20260709" in dates       # the pending bet's day
        assert len(dates) <= czech.MAX_DATE_FETCHES


class TestPolishCircuit:
    def test_tt_elite_series_is_covered_with_polish_label(self, tmp_path, no_sleep):
        # same Elo pool, same math as the czech flow (hand math in TestFullBetFlow),
        # but the circuit label and rec id mark it as the Polish league
        raw = response([pbenc.match("pm1", "c3", "t1", "t2", TS + 3600, 1,
                                    towin=["2.4", "0", "1.55", "0"])])
        recs, _ = run(fresh_data(), raw, seeded_store_path(tmp_path))
        assert len(recs) == 1
        r = recs[0]
        assert r["circuit"] == "polish"
        assert r["id"] == "rec-pl-pm1"
        assert r["grade"] == "C"
        assert r["units"] == 1.00

    def test_polish_finals_feed_the_shared_elo_store(self, tmp_path, no_sleep):
        raw = response([pbenc.match("pf1", "c3", "t5", "t6", TS - 7200, 100,
                                    ft=(3, 0))])
        path = str(tmp_path / "elo.json")
        run(fresh_data(), raw, path)
        store = elo.load_store(path)
        assert store["players"]["Echo"]["r"] == 1516.0  # equals, winner +16

    def test_polish_bet_settles_by_match_id(self, tmp_path, no_sleep):
        data = fresh_data()
        data["bets"] = [{"id": "bet-rec-pl-pm4", "recId": "rec-pl-pm4",
                         "date": "2026-07-09", "event": "TT Elite Series",
                         "playerA": "Alpha", "playerB": "Beta", "pick": "Beta",
                         "odds": 2.5, "units": 0.5, "grade": "C",
                         "status": "pending", "circuit": "polish",
                         "matchId": "pm4", "notes": ""}]
        raw = response([pbenc.match("pm4", "c3", "t1", "t2", TS - 7200, 100,
                                    ft=(1, 3))])
        run(data, raw, str(tmp_path / "e.json"))
        assert data["bets"][0]["status"] == "win"

    def test_wtt_auto_settle_skips_amateur_bets(self, tmp_path, no_sleep):
        data = fresh_data()
        for circ in ("czech", "polish"):
            data["bets"].append({"id": "b-" + circ, "date": "2026-07-09",
                                 "event": "E", "playerA": "Alpha",
                                 "playerB": "Beta", "pick": "Alpha",
                                 "odds": 2.0, "units": 1.0, "grade": "C",
                                 "status": "pending", "circuit": circ,
                                 "matchId": "x", "notes": ""})
        assert engine.auto_settle(data, {}, {}) == 0
        assert all(b["status"] == "pending" for b in data["bets"])


class TestStartTime:
    def test_rec_carries_match_start_timestamp(self, tmp_path, no_sleep):
        raw = response([pbenc.match("st1", "c1", "t1", "t2", TS + 3600, 1,
                                    towin=["2.4", "0", "1.55", "0"])])
        recs, _ = run(fresh_data(), raw, seeded_store_path(tmp_path))
        assert recs[0]["startTime"] == TS + 3600

    def test_auto_logged_bet_copies_start_time(self, tmp_path, no_sleep):
        raw = response([pbenc.match("st2", "c1", "t1", "t2", TS + 3600, 1,
                                    towin=["2.4", "0", "1.55", "0"])])
        data = fresh_data()
        recs, _ = run(data, raw, seeded_store_path(tmp_path))
        engine.auto_log_bets(data, recs)
        assert data["bets"][0]["startTime"] == TS + 3600


class TestAutoLogIntegration:
    def test_czech_bet_rec_is_auto_logged_once_with_labels(
            self, tmp_path, no_sleep):
        data = fresh_data()
        raw = response([pbenc.match("m1", "c1", "t1", "t2", TS + 3600, 1,
                                    towin=["2.4", "0", "1.55", "0"])])
        recs, _ = run(data, raw, seeded_store_path(tmp_path))
        assert engine.auto_log_bets(data, recs) == 1
        b = data["bets"][0]
        assert b["id"] == "bet-rec-cz-m1"
        assert b["circuit"] == "czech"
        assert b["matchId"] == "m1"
        assert b["pick"] == "Alpha"
        assert b["units"] == 1.00
        assert b["grade"] == "C"
        assert engine.validate_bet(b) == []
        # a later run with the same rec must not double-log
        assert engine.auto_log_bets(data, recs) == 0
        assert len(data["bets"]) == 1
