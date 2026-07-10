"""Input validation: odds formats (American + decimal), stake, grade, date."""

import pytest

import engine
from test_storage import good_bet


class TestOddsConversion:
    def test_decimal_passthrough(self):
        assert engine.to_decimal_odds(1.28) == 1.28
        assert engine.to_decimal_odds(3.5) == 3.5
        assert engine.to_decimal_odds("2.75") == 2.75

    def test_american_negative(self):
        # -357 => 1 + 100/357 = 1.2801 (books' display for a 1.28 favourite)
        assert engine.to_decimal_odds(-357) == 1.2801
        assert engine.to_decimal_odds("-250") == 1.4

    def test_american_positive(self):
        assert engine.to_decimal_odds(250) == 3.5
        assert engine.to_decimal_odds("+150") == 2.5
        assert engine.to_decimal_odds(100) == 2.0  # +100 = even money

    def test_rejects_non_odds(self):
        for v in ("abc", None, "", 0, 1.0, 0.5, -50, -99.9, float("nan"),
                  float("inf"), True, [2.0]):
            assert engine.to_decimal_odds(v) is None, v


class TestBetValidation:
    def test_valid_bet_passes(self):
        assert engine.validate_bet(good_bet()) == []

    def test_stake_must_be_positive(self):
        assert engine.validate_bet(good_bet(units=0))
        assert engine.validate_bet(good_bet(units=-2))
        assert engine.validate_bet(good_bet(units="lots"))

    def test_grade_must_be_a_b_or_c(self):
        for g in ("D", "", None, "a", 1):
            assert engine.validate_bet(good_bet(grade=g))
        for g in ("A", "B", "C"):
            assert engine.validate_bet(good_bet(grade=g)) == []

    def test_date_must_be_iso(self):
        for d in ("07/01/2026", "2026-7-1", "20260701", "", None):
            assert engine.validate_bet(good_bet(date=d))
        assert engine.validate_bet(good_bet(date="2026-12-31")) == []

    def test_status_must_be_known(self):
        for s in ("open", "", None, "WIN"):
            assert engine.validate_bet(good_bet(status=s))

    def test_odds_accept_american_or_decimal(self):
        assert engine.validate_bet(good_bet(odds=-357)) == []
        assert engine.validate_bet(good_bet(odds=1.28)) == []
        assert engine.validate_bet(good_bet(odds="+240")) == []
        assert engine.validate_bet(good_bet(odds="evens"))
