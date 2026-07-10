"""Quarter-Kelly staking math. Every expected value below is computed BY HAND
in the comments — never from the code under test."""

import pytest

import engine


def rec(prob_a, grade="B"):
    return {"playerA": "Alpha", "playerB": "Beta", "myProbA": prob_a,
            "grade": grade, "marketProbA": None, "bestOdds": None,
            "edge": None, "units": 0, "rec": ""}


def test_cap_binds_when_kelly_exceeds_two_units():
    # oh=5.0, oa=1.15 -> imp 0.2 / 0.869565..., sum 1.069565...
    # novig_h = 0.2/1.069565 = 0.186993...; p=0.9 -> edge 0.713 (side A)
    # quarter-Kelly = 0.25*(0.9*5-1)/(5-1)*100 = 0.25*3.5/4*100 = 21.875 units
    # hard cap must bind: stake = 2.00
    r = rec(0.9, grade="B")
    engine.apply_edge(r, 5.0, 1.15, "bookX", bankroll=100)
    assert r["units"] == 2.00
    assert r["pickName"] == "Alpha"
    assert r["rec"].startswith("BET 2.00u on Alpha")


def test_c_grade_halves_the_capped_stake():
    # same numbers as above; C-grade halves AFTER the cap: 2.0 / 2 = 1.00
    r = rec(0.9, grade="C")
    engine.apply_edge(r, 5.0, 1.15, "bookX", bankroll=100)
    assert r["units"] == 1.00


def test_c_grade_halves_an_uncapped_stake():
    # oh=2.1, oa=1.9 -> imp 0.476190+0.526316=1.002506; novig_h=0.475
    # p=0.55 -> edge 0.075 >= 6%
    # quarter-Kelly on bankroll 20: 0.25*(0.55*2.1-1)/1.1*20
    #   = 0.25*0.155/1.1*20 = 0.7045... -> B stakes 0.70, C stakes 0.35
    r = rec(0.55, grade="B")
    engine.apply_edge(r, 2.1, 1.9, "bookX", bankroll=20)
    assert r["units"] == 0.70
    r = rec(0.55, grade="C")
    engine.apply_edge(r, 2.1, 1.9, "bookX", bankroll=20)
    assert r["units"] == 0.35


def test_stake_never_exceeds_cap_for_any_grade():
    # p=0.95 (model clamp ceiling), o=8.0: kelly = 0.25*(0.95*8-1)/7*100 = 23.57u
    for grade, expected in (("A", 2.0), ("B", 2.0), ("C", 1.0)):
        r = rec(0.95, grade=grade)
        engine.apply_edge(r, 8.0, 1.05, "bookX", bankroll=100)
        assert r["units"] <= 2.0
        assert r["units"] == expected


def test_edge_boundary_59_is_no_bet_60_is_bet():
    # oh=oa=1.96 -> novig exactly 0.5 each side.
    # p=0.559 -> edge 5.9% -> NO BET, stake 0
    r = rec(0.559)
    engine.apply_edge(r, 1.96, 1.96, "bookX", bankroll=100)
    assert r["units"] == 0
    assert r["rec"].startswith("NO BET")
    # p=0.560 -> edge 6.0% -> BET.
    # kelly = 0.25*(0.56*1.96-1)/0.96*100 = 0.25*0.0976/0.96*100 = 2.5417 -> cap 2.0
    r = rec(0.560)
    engine.apply_edge(r, 1.96, 1.96, "bookX", bankroll=100)
    assert r["units"] == 2.00


def test_negative_ev_stakes_zero_even_with_headline_edge():
    # Heavy vig: oh=oa=1.5 -> novig 0.5. p=0.56 -> edge 6% BUT p*o = 0.84 < 1,
    # so Kelly is negative: 0.25*(0.84-1)/0.5*100 = -8 units. Stake must be 0.
    r = rec(0.56)
    engine.apply_edge(r, 1.5, 1.5, "bookX", bankroll=100)
    assert r["units"] == 0
    assert r["rec"].startswith("NO BET")


def test_negative_edge_on_a_flips_bet_to_b():
    # p(A)=0.4 with fair 2.0/2.0 market (novig 0.5): edge on A is -10%,
    # so the bet is on B: p=0.6, o=2.0, kelly=0.25*(1.2-1)/1*100=5 -> cap 2.0
    r = rec(0.4)
    engine.apply_edge(r, 2.0, 2.0, "bookX", bankroll=100)
    assert r["units"] == 2.00
    assert r["pickName"] == "Beta"
    assert "on Beta" in r["rec"]


def test_zero_bankroll_stakes_zero():
    r = rec(0.9)
    engine.apply_edge(r, 5.0, 1.15, "bookX", bankroll=0)
    assert r["units"] == 0
    assert r["rec"].startswith("NO BET")
