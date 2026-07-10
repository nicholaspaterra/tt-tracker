# Claude Code handoff

Run from inside the `tt-tracker` folder:

```
claude --model claude-fable-5
```

(or `/model claude-fable-5` inside an existing session), then paste the GOAL below.

---

```
GOAL: Bring the table tennis betting tracker in this folder to a fully
validated, test-covered v1, AND extend match coverage to the Czech
amateur leagues (Czech Liga Pro / TT Cup) that betting sites price
around the clock. You own this end-to-end. Plan your own approach,
work autonomously until every "Definition of Done" item passes, and
do not stop to ask questions — make reasonable decisions, log them
in DECISIONS.md, and continue.

EXISTING CODEBASE (audit before changing anything):
- engine.py — autonomous prediction engine. Scrapes m.aiscore.com
  (server-rendered mobile pages): ITTF rankings lists (men + women,
  top 80 each), player pages (last ~20 results + upcoming matches),
  and a protobuf odds endpoint
  (api.aiscore.com/v1/m/api/match/odds/list?match_id=...&code=54&platform=2,
  bet365 line; minimal protobuf walker already implemented and tested
  against captured bytes). Models win probability (Bradley-Terry on
  ranking points ^0.75, log-odds adjustments for last-10 form, H2H,
  fatigue), strips vig, computes edge, quarter-Kelly stake, and
  writes to bets.js. Auto-logs bets at edge >= 6% (MIN_EDGE) and
  auto-settles from final scores on later runs.
- index.html — single-file dashboard (no build step, reads bets.js
  via <script src>). Wager cards, picks table, active/history bet
  log, P&L, ROI by grade, bankroll chart, American odds display.
- bets.js — canonical data file: window.BETS_FILE = {settings,
  recommendations, bets}. The dashboard and engine both depend on
  this exact shape — keep it backward compatible.
- install.sh — macOS launchd hourly runs. .github/workflows/engine.yml
  — hourly GitHub Actions runs (repo: nicholaspaterra/tt-tracker;
  5 root files are committed; the workflow file itself was drafted
  but never committed — finish that via git).

SYSTEM SPEC (source of truth — code must match this):
- Staking: quarter-Kelly, hard cap of 2 units per bet, enforced in
  code. A stake can never exceed the cap regardless of Kelly output.
  C-grade picks stake half. Minimum edge to bet: 6% (MIN_EDGE).
- Confidence grades: A/B/C tied to data quality. Grading logic must
  be explicit, deterministic, and testable. Thin H2H (<3 meetings)
  or <5 recent matches caps at C.
- Bet log: persistent local storage (bets.js). Survives restarts.
  Handles duplicates and malformed entries gracefully.
- Reporting: ROI by confidence grade + overall bankroll curve, and
  (new) ROI split by circuit: WTT/ITTF vs Czech amateur — so the
  owner can see whether amateur betting actually makes money before
  trusting it.

NEW SCOPE — CZECH AMATEUR LEAGUES:
- Target: Czech Liga Pro and TT Cup matches (the high-volume matches
  priced on betting sites; aiscore lists them with live scores, and
  its odds endpoint covers them).
- CRITICAL MODELING CONSTRAINT: these players are NOT in ITTF
  rankings, so the existing ranking-points model cannot price them.
  Build a separate self-maintained Elo (or equivalent) rating store,
  bootstrapped and updated from scraped match results, persisted to
  its own file (e.g. elo.json). Players below a minimum rated-match
  count (default 10) are unbettable — engine must output NO BET.
- Every amateur pick is grade-capped at C (half stake) until the
  circuit-split ROI report proves otherwise to the owner. Log this
  as a DECISIONS.md entry with the reasoning.
- Amateur matches must be clearly labeled in bets.js entries
  (e.g. circuit: "czech") and visually distinguished on the
  dashboard.
- Cold-start honesty: for the first days the Elo store has little
  data, the correct behavior is few or zero amateur bets. Do not
  loosen gates to force volume.

YOUR MANDATE:
1. Audit the codebase first. Write what you find to STATUS.md
   before changing anything.
2. Decide your own task ordering and architecture improvements —
   but every claim of correctness must be backed by a test.
3. Verification standard: for the Kelly/cap math, the ROI-by-grade
   report, the circuit-split report, and Elo updates, build
   synthetic bet/match histories where the expected outputs are
   computed BY HAND inside the test. Do not test the code against
   its own output.
4. Required test coverage at minimum: negative-edge bets stake
   zero; cap binds when Kelly exceeds 2 units; C-grade halving;
   6% edge boundary (5.9% no-bet, 6.0% bet); log persistence
   across a simulated restart; duplicate rejection; corrupt-entry
   recovery; input validation (odds format incl. American/decimal,
   stake > 0, valid grade, valid date); protobuf odds parser
   against the captured-bytes fixture; Elo update math by hand;
   min-rated-matches gate; amateur grade cap.
5. Network calls must be mocked in tests. A separate opt-in smoke
   script may hit the live site once for manual verification.
6. Iterate: run the full suite, fix, re-run, until green.
7. Finish with SUMMARY.md — what changed, what you found, coverage,
   open questions for the owner's review.

DEFINITION OF DONE:
- Full test suite green
- 2-unit cap provably enforced by a passing test
- Bet log provably survives restart
- ROI report (by grade AND by circuit) matches hand-computed
  synthetic values
- Czech pipeline: discovery -> Elo rating -> gate -> odds -> edge ->
  stake, fully covered by mocked tests
- Dashboard renders both circuits without breaking the existing
  bets.js contract
- SUMMARY.md and DECISIONS.md current

HARD CONSTRAINTS:
- NEVER delete or overwrite the existing bet log data file. Before
  touching storage code, copy it to /backups with a timestamp.
- No external paid APIs. No placing or simulating real bets against
  live books. The tracker records decisions; the owner places bets.
- Keep scraping polite: keep/honor REQUEST_DELAY; Czech leagues run
  hundreds of matches daily — bound discovery per run (e.g. next N
  hours window) instead of crawling everything.
- If genuinely blocked, log the blocker in STATUS.md and route
  around it — never idle.
```
