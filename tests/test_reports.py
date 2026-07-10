"""ROI report (by grade AND by circuit) against a synthetic bet history whose
totals are computed by hand below — never from the code under test."""

import pytest

import engine
from conftest import fresh_data


def bet(id, grade, circuit, status, units, odds=2.0):
    b = {"id": id, "date": "2026-07-01", "event": "E", "playerA": "A",
         "playerB": "B", "pick": "A", "odds": odds, "units": units,
         "grade": grade, "status": status}
    if circuit is not None:
        b["circuit"] = circuit
    return b


def synthetic_history():
    data = fresh_data()
    data["bets"] = [
        # win 2u @2.5  -> net +3.0   (A, wtt)
        bet("b1", "A", "wtt", "win", 2.0, 2.5),
        # loss 1u      -> net -1.0   (A, wtt)
        bet("b2", "A", "wtt", "loss", 1.0, 3.0),
        # win 0.5u @1.8 -> net +0.4  (B, unlabeled circuit => counts as wtt)
        bet("b3", "B", None, "win", 0.5, 1.8),
        # loss 0.5u    -> net -0.5   (C, czech)
        bet("b4", "C", "czech", "loss", 0.5, 1.9),
        # win 1u @2.2  -> net +1.2   (C, czech)
        bet("b5", "C", "czech", "win", 1.0, 2.2),
        # push 1u      -> net 0      (A, wtt)
        bet("b6", "A", "wtt", "push", 1.0, 2.0),
        # pending bets must not count anywhere
        bet("b7", "B", "wtt", "pending", 1.0, 2.0),
        # win 1u @3.0  -> net +2.0   (C, polish)
        bet("b8", "C", "polish", "win", 1.0, 3.0),
    ]
    return data


def test_roi_by_grade_matches_hand_computed_values():
    rep = engine.roi_report(synthetic_history())
    g = rep["byGrade"]
    # Grade A: bets 3 (2W? no: 1W 1L 1P), staked 2+1+1=4.0, net 3.0-1.0+0=2.0, roi 0.5
    assert g["A"] == {"bets": 3, "wins": 1, "losses": 1, "pushes": 1,
                      "staked": 4.0, "net": 2.0, "roi": 0.5}
    # Grade B: 1 win, staked 0.5, net +0.4, roi 0.8
    assert g["B"] == {"bets": 1, "wins": 1, "losses": 0, "pushes": 0,
                      "staked": 0.5, "net": 0.4, "roi": 0.8}
    # Grade C: 2W 1L, staked 1.5+1=2.5, net 1.2-0.5+2.0=2.7, roi 2.7/2.5=1.08
    assert g["C"] == {"bets": 3, "wins": 2, "losses": 1, "pushes": 0,
                      "staked": 2.5, "net": 2.7, "roi": 1.08}


def test_roi_by_circuit_matches_hand_computed_values():
    rep = engine.roi_report(synthetic_history())
    c = rep["byCircuit"]
    # wtt: b1,b2,b3(unlabeled->wtt),b6 = 4 bets, staked 4.5, net 2.4, roi 0.5333
    assert c["wtt"] == {"bets": 4, "wins": 2, "losses": 1, "pushes": 1,
                        "staked": 4.5, "net": 2.4, "roi": 0.5333}
    # czech: b4,b5 = 2 bets, staked 1.5, net 0.7, roi 0.4667
    assert c["czech"] == {"bets": 2, "wins": 1, "losses": 1, "pushes": 0,
                          "staked": 1.5, "net": 0.7, "roi": 0.4667}
    # polish: b8 = 1 bet, staked 1.0, net +2.0, roi 2.0
    assert c["polish"] == {"bets": 1, "wins": 1, "losses": 0, "pushes": 0,
                           "staked": 1.0, "net": 2.0, "roi": 2.0}


def test_bankroll_curve_inputs_net_units_per_bet():
    # by hand: +3.0 -1.0 +0.4 -0.5 +1.2 +0 +2.0 = 5.1
    data = synthetic_history()
    assert engine.bankroll_units(data) == pytest.approx(105.1)


def test_empty_history_reports_empty_tables():
    rep = engine.roi_report(fresh_data())
    assert rep == {"byGrade": {}, "byCircuit": {}}
