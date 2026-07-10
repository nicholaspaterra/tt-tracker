"""Protobuf parsers against REAL captured bytes (2026-07-10 live capture) and
against constructed messages in the documented wire layout.

Cross-source verification: fixtures/matches_expected.json was extracted from
the aiscore web app's own parsed state (its JS data store), independently of
this repo's parser — the Python parser must reproduce it from the raw bytes."""

import json
import os

import engine
import czech
import pbenc
from conftest import FIXTURES


def load(name, mode="rb"):
    with open(os.path.join(FIXTURES, name), mode) as f:
        return f.read()


class TestMatchesParserAgainstCapturedBytes:
    def test_reproduces_the_sites_own_parse_of_all_40_matches(self):
        matches = czech.parse_matches(load("matches_20260710.bin"))
        expected = json.loads(load("matches_expected.json", "r"))
        assert len(matches) == len(expected) == 40
        got = {m["mid"]: m for m in matches}
        for e in expected:
            m = got[e["id"]]
            assert m["comp"] == e["comp"]
            assert m["home"] == e["home"]
            assert m["away"] == e["away"]
            assert m["start"] == e["matchTime"]
            assert m["status"] == e["statusId"]
            if e["statusId"] == 100:
                assert list(m["ft"]) == e["ft"]

    def test_finished_czech_matches_carry_decodable_odds(self):
        matches = czech.parse_matches(load("matches_20260710.bin"))
        m = next(x for x in matches if x["mid"] == "o07d1s4ry8whm7n")
        # raw block held ["1.4","-1.5","2.75","0"], ["1.83","0","1.83","0"],
        # ["1.83","76.5","1.83","0"] — the to-win row is the middle one
        assert m["odds"] == (1.83, 1.83)

    def test_upcoming_czech_matches_without_a_line_have_no_odds(self):
        matches = czech.parse_matches(load("matches_20260710.bin"))
        up = [m for m in matches if m["comp"] == "Czech Liga Pro" and m["status"] == 1]
        assert up and all(m["odds"] is None for m in up)

    def test_garbage_input_yields_no_matches(self):
        assert czech.parse_matches(b"") == []
        assert czech.parse_matches(pbenc.field(3, b"unrelated")) == []


class TestOddsEndpointParser:
    def test_real_disclaimer_response_yields_none(self):
        # captured live: odds/list returned only the "Gamble Responsibly" string
        assert engine.parse_match_odds(load("odds_disclaimer.bin")) is None

    def test_constructed_bet365_response_parses(self):
        raw = pbenc.odds_list_response(["1.85", "0", "1.95", "0"], book="bet365")
        assert engine.parse_match_odds(raw) == (1.85, 1.95, "bet365")

    def test_handicap_style_rows_are_not_mistaken_for_to_win(self):
        # vals[1] != "0" -> not the to-win market
        raw = pbenc.odds_list_response(["1.4", "-1.5", "2.75", "0"])
        assert engine.parse_match_odds(raw) is None

    def test_zero_or_absurd_odds_are_rejected(self):
        raw = pbenc.odds_list_response(["0", "0", "1.95", "0"])
        assert engine.parse_match_odds(raw) is None


class TestToWinSelection:
    def test_picks_the_row_with_the_draw_zero_signature(self):
        sets = [["1.4", "-1.5", "2.75", "0"],
                ["2.1", "0", "1.7", "0"],
                ["1.83", "76.5", "1.83", "0"]]
        assert czech.towin_odds(sets) == (2.1, 1.7)

    def test_no_signature_row_means_no_odds(self):
        assert czech.towin_odds([["1.4", "-1.5", "2.75", "0"]]) is None
        assert czech.towin_odds([]) is None
