"""Bet-log persistence: survives restart, rejects duplicates, quarantines
malformed entries, never overwrites an unreadable file, keeps backups."""

import json
import os

import pytest

import engine
from conftest import fresh_data


def good_bet(id="b1", **kw):
    b = {"id": id, "date": "2026-07-01", "event": "E", "playerA": "A",
         "playerB": "B", "pick": "A", "odds": 2.0, "units": 1.0,
         "grade": "B", "status": "pending", "notes": ""}
    b.update(kw)
    return b


def test_log_survives_a_simulated_restart(tmp_store):
    data = fresh_data()
    data["bets"] = [good_bet("b1"), good_bet("b2", status="win")]
    data["recommendations"] = [{"id": "r1", "date": "2026-07-01"}]
    engine.save_bets_file(data)
    # "restart": fresh read from disk, nothing shared with the old dict
    reloaded = engine.load_bets_file()
    assert reloaded == data
    # and the file is valid JS for the dashboard (window.BETS_FILE = {...};)
    src = open(engine.BETS_JS).read()
    assert src.startswith("//")
    assert "window.BETS_FILE = {" in src


def test_duplicate_bet_ids_are_dropped_first_wins(tmp_store):
    data = fresh_data()
    data["bets"] = [good_bet("dup", units=1.0), good_bet("dup", units=9.0),
                    good_bet("other")]
    dupes, quarantined = engine.sanitize_bets(data)
    assert dupes == 1 and quarantined == 0
    assert [b["id"] for b in data["bets"]] == ["dup", "other"]
    assert data["bets"][0]["units"] == 1.0  # first occurrence kept


def test_malformed_entries_are_quarantined_not_deleted(tmp_store):
    bad = [
        good_bet("x1", odds="not-odds"),
        good_bet("x2", units=-1),
        good_bet("x3", grade="Z"),
        good_bet("x4", status="maybe"),
        good_bet("x5", date="07/01/2026"),
        good_bet("x6", pick=""),
        "just a string",
    ]
    data = fresh_data()
    data["bets"] = [good_bet("ok1")] + bad + [good_bet("ok2")]
    dupes, quarantined = engine.sanitize_bets(data)
    assert quarantined == 7 and dupes == 0
    assert [b["id"] for b in data["bets"]] == ["ok1", "ok2"]
    # nothing silently deleted: every reject is preserved with its reasons
    assert len(data["quarantine"]) == 7
    assert all(q["problems"] for q in data["quarantine"])


def test_american_odds_in_log_are_normalized_to_decimal(tmp_store):
    data = fresh_data()
    data["bets"] = [good_bet("a1", odds=-250), good_bet("a2", odds="+150")]
    engine.sanitize_bets(data)
    assert data["bets"][0]["odds"] == 1.4    # 1 + 100/250
    assert data["bets"][1]["odds"] == 2.5    # 1 + 150/100


def test_corrupt_file_aborts_run_without_overwriting(tmp_store, monkeypatch):
    with open(engine.BETS_JS, "w") as f:
        f.write("window.BETS_FILE = {this is not json};\n")
    before = open(engine.BETS_JS).read()
    with pytest.raises(SystemExit):
        engine.main()
    assert open(engine.BETS_JS).read() == before  # untouched


def test_missing_assignment_raises(tmp_store):
    with open(engine.BETS_JS, "w") as f:
        f.write("var whatever = 1;\n")
    with pytest.raises(ValueError):
        engine.load_bets_file()


def test_backup_created_before_write_and_pruned(tmp_store):
    data = fresh_data()
    data["bets"] = [good_bet()]
    engine.save_bets_file(data)
    from datetime import datetime, timedelta
    t0 = datetime(2026, 7, 10, 9, 0, 0)
    for i in range(engine.MAX_BACKUPS + 5):
        engine.backup_bets_file(t0 + timedelta(seconds=i))
    names = sorted(os.listdir(engine.BACKUP_DIR))
    assert len(names) == engine.MAX_BACKUPS
    # the newest backup is byte-identical to the log it protects
    newest = os.path.join(engine.BACKUP_DIR, names[-1])
    assert open(newest).read() == open(engine.BETS_JS).read()
