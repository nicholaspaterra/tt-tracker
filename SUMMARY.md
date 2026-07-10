# SUMMARY — tt-tracker v1 (2026-07-10)

## What changed

| Area | Change |
|---|---|
| `engine.py` | Pre-write timestamped backups (`backups/`, keep 30); corrupt bets.js aborts the run without writing; malformed entries quarantined + duplicate ids dropped on load; American/decimal odds normalization; structured `pickName` on recs (no more regex re-parsing); `circuit` labels on recs/bets; `roi_report()` (grade + circuit) logged each run; czech pipeline hooked in behind a try/except so it can never kill the WTT run; odds parser split into fetch + pure `parse_match_odds`. |
| `elo.py` (new) | Self-maintained Elo store for amateur players (K=32, start 1500), persisted to `elo.json`, match-id dedup, 10-rated-match bettability gate, probability clamp, atomic writes. |
| `czech.py` (new) | Czech Liga Pro + TT Cup pipeline: one day-slate API request discovers matches, final scores AND (when posted) odds; Elo bootstrap/update; settle-by-match-id; bounded discovery window (12h) and candidate cap (40); odds/list fallback capped at 15 calls; grade hard-capped at C. |
| `index.html` | Czech bets/picks visually distinct (amber CZE chips, amber wager-card border); **ROI by circuit** table (WTT/ITTF vs Czech amateur); `logRec` uses structured pickName + copies circuit/matchId; null-safe rendering for gated NO BET picks. bets.js shape only gained optional keys — fully backward compatible. |
| `tests/` (new) | 68 tests, all mocked, all key math hand-computed in-line. Real captured fixtures: 12KB day-slate protobuf (40 matches, cross-verified against the site's own parsed state 40/40) + real 45-byte disclaimer odds response. |
| Workflows | `engine.yml` now also commits `elo.json`; new `tests.yml` runs pytest on every push. |
| `smoke_live.py` (new) | Opt-in one-shot live check (never run by suite or engine). |

## Definition of Done — status

- ✅ Full test suite green: **68 passed** (`python3 -m pytest tests/ -q`)
- ✅ 2-unit cap provably enforced (`test_staking.py::test_cap_binds_when_kelly_exceeds_two_units`, plus per-grade sweep)
- ✅ Bet log provably survives restart (`test_storage.py::test_log_survives_a_simulated_restart`)
- ✅ ROI by grade AND circuit matches hand-computed synthetic values (`test_reports.py`), and the dashboard rendered the same synthetic history with matching numbers in a real browser
- ✅ Czech pipeline discovery → Elo → gate → odds → edge → stake fully covered by mocked tests (`test_czech.py`, 18 tests) plus a full `engine.main()` integration run with the network mocked at urllib level (`test_integration.py`)
- ✅ Dashboard renders both circuits, bets.js contract unchanged (additive keys only)
- ✅ DECISIONS.md and this file current

## What I found (worth your attention)

1. **The data source currently blocks all non-browser clients from this
   machine.** Every aiscore endpoint (HTML and API) returns a Cloudflare-style
   403 challenge to python/urllib/curl; a real Chrome session gets through
   fine (that's how the fixtures were captured). Consequence: hourly launchd
   runs on this Mac will log fetch failures until the block changes.
   **Next step for you:** run the GitHub workflow once manually (Actions →
   TT Engine (hourly) → Run workflow) and check its log. If Actions is blocked
   too, the realistic options are: a headless-browser fetcher in CI
   (needs a dependency — breaks the stdlib-only constraint, your call), a
   different data source, or accepting manual/browser-assisted runs.
2. **Odds are region-gated.** From this network, even the site's own odds tab
   is empty and the odds endpoint returns just a gambling disclaimer — yet
   *finished* Czech matches in the day slate carry real odds rows
   (e.g. 1.83/1.83), proving the odds block format and that lines DO exist
   for these matches. Where the engine runs will determine whether it sees
   pre-match lines. Everything degrades to MODEL PICK / NO BET gracefully.
3. **Big win for politeness:** the day-slate endpoint carries discovery,
   results AND odds in one response — the czech circuit costs 1-2 requests
   per run, not hundreds.
4. The GitHub repo `nicholaspaterra/tt-tracker` exists (single commit
   e0d8f47). Local work is committed on top of a fresh local history; see
   STATUS.md for push details.

## Open questions for you

- **Lift the C-cap on czech picks when?** Suggested bar: circuit ROI > 0 over
  ≥100 settled czech bets. Your call, via the dashboard's ROI-by-circuit table.
- **Where should the engine live?** Cloud (Actions) vs this Mac — decide after
  the manual workflow test above. Running both = two diverging data files.
- **elo.json in git:** the workflow commits it (ratings survive runner
  recycling). If the repo stays public, player ratings are visible — fine?

## How to run things

```
python3 -m pytest tests/ -q     # full suite (no network)
python3 engine.py               # one engine run (needs network access to aiscore)
python3 smoke_live.py           # opt-in live endpoint check
bash install.sh                 # hourly launchd runs on this Mac
```
