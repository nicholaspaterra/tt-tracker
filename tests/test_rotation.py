"""Bet rotation (MAX_OPEN_BETS) and quick-run mode."""

import engine


def rec(rid, edge, units=1.0):
    return {"id": rid, "date": "2026-07-10", "event": "Czech Liga Pro",
            "circuit": "czech", "playerA": "A", "playerB": "B",
            "myProbA": 0.6, "marketProbA": 0.5, "bestOdds": 2.0,
            "edge": edge, "units": units, "grade": "C",
            "pickName": "A", "rec": "BET %.2fu on A @ +100 (book)" % units,
            "reasoning": ""}


def pending_bet(bid):
    return {"id": bid, "recId": None, "date": "2026-07-10", "event": "E",
            "playerA": "X", "playerB": "Y", "pick": "X", "odds": 2.0,
            "units": 1.0, "grade": "C", "status": "pending", "notes": ""}


def data_with_pending(n):
    return {"settings": {"unitSize": 10, "startingBankrollUnits": 100},
            "recommendations": [], "bets": [pending_bet("p%d" % i) for i in range(n)]}


class TestRotation:
    def test_caps_open_bets_at_three(self):
        data = data_with_pending(1)  # one already open -> 2 slots
        recs = [rec("r1", 0.07), rec("r2", 0.09), rec("r3", 0.08), rec("r4", 0.10)]
        assert engine.auto_log_bets(data, recs) == 2
        assert sum(1 for b in data["bets"] if b["status"] == "pending") == 3

    def test_best_edges_win_the_slots(self):
        data = data_with_pending(1)
        recs = [rec("r1", 0.07), rec("r2", 0.09), rec("r3", 0.08), rec("r4", 0.10)]
        engine.auto_log_bets(data, recs)
        logged = {b["recId"] for b in data["bets"] if b.get("recId")}
        assert logged == {"r4", "r2"}  # 10% and 9% beat 8% and 7%

    def test_full_rotation_logs_nothing(self):
        data = data_with_pending(3)
        assert engine.auto_log_bets(data, [rec("r1", 0.20)]) == 0

    def test_slot_frees_when_bet_settles(self):
        data = data_with_pending(3)
        data["bets"][0]["status"] = "loss"
        assert engine.auto_log_bets(data, [rec("r1", 0.07)]) == 1


class TestQuickMode:
    def test_quick_run_skips_wtt_and_still_runs_amateur(self, tmp_path, monkeypatch):
        import czech, elo, json
        monkeypatch.setenv("TT_QUICK", "1")
        monkeypatch.setattr(engine, "BETS_JS", str(tmp_path / "bets.js"))
        monkeypatch.setattr(engine, "LOG_FILE", str(tmp_path / "log.txt"))
        monkeypatch.setattr(engine, "BACKUP_DIR", str(tmp_path / "backups"))
        monkeypatch.setattr(elo, "ELO_FILE", str(tmp_path / "elo.json"))
        (tmp_path / "bets.js").write_text(
            "window.BETS_FILE = " + json.dumps(
                {"settings": {"unitSize": 10, "startingBankrollUnits": 100},
                 "recommendations": [], "bets": []}) + ";\n")
        wtt_urls = []
        monkeypatch.setattr(engine, "fetch", lambda url: wtt_urls.append(url) or "")
        czech_calls = []
        monkeypatch.setattr(czech, "run",
                            lambda data, now, **kw: czech_calls.append(1) or ([], "quick ok"))
        engine.main()
        assert wtt_urls == []          # no rankings / player-page crawling
        assert czech_calls == [1]      # amateur pipeline still ran
