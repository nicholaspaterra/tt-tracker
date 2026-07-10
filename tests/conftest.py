import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import engine  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


@pytest.fixture(autouse=True)
def isolated_log(tmp_path, monkeypatch):
    """No test may ever touch the real engine_log.txt."""
    monkeypatch.setattr(engine, "LOG_FILE", str(tmp_path / "engine_log.txt"))


@pytest.fixture
def tmp_store(tmp_path, monkeypatch):
    """Point the engine's storage (bets.js, backups) at a temp dir."""
    bets = tmp_path / "bets.js"
    monkeypatch.setattr(engine, "BETS_JS", str(bets))
    monkeypatch.setattr(engine, "BACKUP_DIR", str(tmp_path / "backups"))
    return tmp_path


@pytest.fixture
def no_sleep(monkeypatch):
    import czech
    monkeypatch.setattr(engine.time, "sleep", lambda *_: None)
    monkeypatch.setattr(czech.time, "sleep", lambda *_: None)


def fresh_data():
    return {"settings": {"unitSize": 10, "startingBankrollUnits": 100},
            "recommendations": [], "bets": []}
