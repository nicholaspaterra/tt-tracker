"""Discord notifier message building — pure function, no network."""

import notify_discord


def bet(bid, status, **kw):
    b = {"id": bid, "date": "2026-07-10", "event": "Czech Liga Pro",
         "playerA": "Alpha", "playerB": "Beta", "pick": "Alpha",
         "odds": 1.83, "units": 1.0, "grade": "C", "status": status,
         "circuit": "czech", "startTime": 1783700000}
    b.update(kw)
    return b


def data_with(bets):
    return {"settings": {"unitSize": 10}, "recommendations": [], "bets": bets}


def test_new_pending_bet_announced_once():
    d = data_with([bet("b1", "pending")])
    lines, announced = notify_discord.build_lines(d, {})
    assert len(lines) == 1
    assert "BET 1.00u ($10) on Alpha @ -120" in lines[0]
    assert "[CZE]" in lines[0]
    # second run: nothing new
    lines2, _ = notify_discord.build_lines(d, announced)
    assert lines2 == []


def test_settlement_announced_with_net():
    d = data_with([bet("b1", "pending")])
    _, announced = notify_discord.build_lines(d, {})
    d["bets"][0]["status"] = "win"
    lines, announced = notify_discord.build_lines(d, announced)
    assert len(lines) == 1
    assert lines[0].startswith("✅ WON +0.83u")  # (1.83-1)*1.0 by hand
    lines2, _ = notify_discord.build_lines(d, announced)
    assert lines2 == []


def test_polish_tag_and_dollars_follow_unit_size():
    d = data_with([bet("b2", "pending", circuit="polish", units=0.5, odds=2.5)])
    d["settings"]["unitSize"] = 25
    lines, _ = notify_discord.build_lines(d, {})
    assert "BET 0.50u ($13) on Alpha @ +150" in lines[0] or \
           "BET 0.50u ($12) on Alpha @ +150" in lines[0]  # 12.5 rounds per %.0f
    assert "[POL]" in lines[0]
