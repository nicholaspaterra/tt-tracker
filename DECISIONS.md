# DECISIONS — tt-tracker v1 + Czech amateur extension

Decisions made autonomously during the 2026-07-10 build, with reasoning.
Flag anything you disagree with and it's a small change.

## Staking & grading

1. **Cap order: cap first, then C-halving.** Spec says "hard cap of 2 units"
   and "C-grade picks stake half". The code does `min(kelly, 2.0)` then halves
   C — so a C pick can never exceed **1.0u**. This is the strictest reading of
   both rules, matches the pre-existing behavior in both engine.py and
   index.html, and is locked by tests (`test_staking.py`).

2. **Every Czech amateur pick is grade-capped at C (half stake).**
   Reasoning: the Elo model is bootstrapped from a few days of scraped
   results; its calibration is unproven, amateur matches are notoriously
   streaky, and the markets are thin. Until the **ROI by circuit** table shows
   the czech line is profitable over a meaningful sample, every amateur stake
   is automatically halved and capped at 1u. Lifting the cap is a one-line
   change in `czech.py` (`GRADE_CAP`) — but it should be YOUR call, made by
   looking at the dashboard, not the model's.

3. **Elo parameters: K=32, start 1500, min 10 rated matches, probability
   clamped to [0.05, 0.95].** Standard chess-style values; nothing exotic is
   justified until there's data to tune against. The 10-match gate is the
   spec default. Cold start therefore correctly produces ~zero amateur bets
   for the first day or two — the gates were NOT loosened to force volume.

## Czech pipeline design

4. **Discovery via the day-slate API, not per-match crawling.** The mobile
   site's own `api/matches?sport_id=11&date=...` endpoint returns every
   table-tennis match for a day in ONE protobuf response — including final
   scores (which feed Elo) and, when posted, a compact odds block per match.
   Czech leagues run 300+ matches/day; this design covers them with 1-2
   requests/run instead of hundreds. Field map verified against a captured
   live response (see tests/fixtures/) cross-checked against the site's own
   parsed state — 40/40 matches identical.

5. **Odds source order: embedded list odds first, odds/list endpoint as a
   bounded fallback (≤15 calls/run), only for matchups that already passed
   the Elo gate.** No odds → MODEL PICK, no stake.

6. **Czech settlement is by match id, not name-matching on player pages.**
   Amateur players have no scanned player pages, so czech bets store
   `matchId` and settle from the day-slate results. WTT bets keep the old
   player-page settlement. `auto_settle` skips czech bets explicitly.

7. **Doubles are excluded** (team names containing "/"): the Elo store rates
   individuals; mixing doubles results would poison singles ratings.

8. **Voided/walkover-looking finals (equal or empty set scores) neither rate
   Elo nor settle bets.** A bet on a match that never decides stays pending
   for manual review rather than being guessed at.

## Storage & safety

9. **bets.js is never auto-restored or auto-rewritten when unreadable.** If
   the file doesn't parse, the engine logs and exits without writing.
   Restoring from `backups/` is deliberately a human action.

10. **Malformed bet entries are quarantined, not deleted** — moved to a
    `quarantine` key in bets.js with the reasons, so no data is ever silently
    lost. Duplicate ids: first entry wins, later ones dropped (they are
    byte-identical re-logs in practice).

11. **A timestamped backup of bets.js lands in `backups/` at the start of
    every run** (before any write), keeping the newest 30. The pre-change
    manual backup from this build is `backups/bets-20260710-091011.js`.

## Fixtures & testing

12. **The "captured-bytes" odds fixture described in the brief did not exist
    in the repo.** What exists now: (a) a REAL captured odds/list response —
    which turned out to be a 45-byte "Gamble Responsibly" disclaimer, the
    parser-must-return-None case; (b) a REAL captured 12KB day-slate response
    with 40 matches incl. Czech Liga Pro/TT Cup finals carrying real odds
    rows; (c) a constructed bet365-layout odds response for the populated
    case, built byte-by-byte in tests to the documented wire format.

13. **ROI reporting logic exists twice** (engine.py `roi_report` for
    logs/tests, index.html for display) because the dashboard is deliberately
    a zero-build single file. The Python side carries the hand-computed
    tests; the JS side was verified rendering the same synthetic history in a
    real browser (values matched hand math). Keep the two in sync when
    changing either.

## Environment reality (important, see SUMMARY.md)

14. **aiscore serves HTTP 403 (bot challenge) to every non-browser client
    from this machine/network** — urllib AND curl, HTML pages AND API. The
    tracker's code is correct against captured real responses, but hourly
    runs from this Mac will currently log fetch failures. The GitHub Actions
    runner may or may not be blocked the same way — verify with one manual
    workflow run. This is an infrastructure/blocking issue, not a code issue;
    options if Actions is also blocked are listed in SUMMARY.md.

15. **Odds availability from this region was nil at capture time** — even
    the site's own odds tab rendered empty and odds/list returned only the
    disclaimer, while finished matches did carry odds rows in the day slate.
    The engine already degrades gracefully (MODEL PICK / NO BET). Expect
    "odds not found" until runs happen from a region/IP where the odds feed
    is served.
