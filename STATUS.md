# STATUS — tt-tracker audit & work log

_Started 2026-07-10. Written BEFORE any code changes, per mandate._

## Audit findings (pre-change state)

### Files present
| File | State |
|---|---|
| `engine.py` (520 lines) | Working single-file engine: rankings scrape, player pages, protobuf odds, Bradley-Terry model, vig-strip, quarter-Kelly, auto-log, auto-settle. Stdlib only, Python 3.9 compatible. |
| `index.html` (577 lines) | Single-file dashboard, no build step. Reads `bets.js` via `<script src>`. Wager cards, picks table, stats, ROI-by-grade, bankroll/daily SVG charts, CRUD dialogs, File System Access API persistence. |
| `bets.js` | Canonical data: `window.BETS_FILE = {settings, recommendations, bets}`. Currently empty log (settings only). |
| `install.sh` | launchd hourly plist — looks correct. |
| `.github/workflows/engine.yml` | Drafted hourly Actions workflow. **Repo is NOT a git repo locally** — the workflow was never committed anywhere from here. |
| `README.md`, `SETUP-GITHUB.md`, `Run Analysis.command`, `engine_log.txt` | Docs/support. Log shows past synthetic-data test runs (Alpha One / Beta Two). |

### What matches the spec already
- Quarter-Kelly with 2u cap and C-grade halving exists in **both** `engine.py:apply_edge()` and `index.html:computeRecEdge()` (duplicated logic, must stay in sync — MIN_EDGE comment says so).
- MIN_EDGE = 0.06 enforced in both.
- Auto-log dedups per rec id (`recId` field + `[rec:...]` notes tag).
- Atomic write of bets.js (tmp + `os.replace`).
- Protobuf walker implemented; **no captured-bytes fixture exists anywhere in the repo** despite the goal describing one — needs a fixture (see DECISIONS.md).

### Gaps / risks found (pre-change)
1. **Zero tests.** No pytest, no fixtures, nothing.
2. **No backups.** Engine rewrites bets.js in place every run; a parse bug or crash mid-shape-change could lose the log. (Hard constraint: back up before touching storage code — done, see below.)
3. **Corrupt bets.js kills the engine** (`load_bets_file` raises; `main()` dies) — no graceful malformed-entry handling, no duplicate-id rejection on load.
4. **No Czech amateur support at all** — discovery is driven by ranked players' pages only; amateurs are invisible to it.
5. **No circuit labeling** in bets/recs; ROI report is grade-only.
6. **Cap-order ambiguity**: code does `min(kelly, 2)` then halves C (so C max = 1.0u). Spec is satisfiable either way; keeping cap-then-halve (documented in DECISIONS.md).
7. `auto_log_bets` parses the pick name back out of the rec **string** (`" on X @ "` regex) — fragile; a structured `pickName` field is safer.
8. `index.html` `logRec()` infers pick via `r.rec.includes(r.playerB)` — breaks if player A's name is a substring of B's or the rec string format changes.
9. Environment: system Python 3.9.6 only, pip present, **pytest not installed**; `gh` CLI absent; no local git repo; no homebrew Python.
10. Dashboard `renderRecTable` treats `r.rec !== 'NO BET'` as bet-ish, but engine writes `"NO BET (edge …)"` — harmless today because `units > 0` also gates, but brittle.

### Environment / blockers
- **Git/GitHub**: no `gh` CLI and no stored credentials found yet. Plan: `git init`, baseline commit, add workflow commit; attempt push to `nicholaspaterra/tt-tracker` — if auth fails, log blocker here and leave the repo ready to push.
- Network access from this machine: to be verified with a single polite capture run (also produces the real captured-bytes odds fixture).

## Work log
- 2026-07-10: Audit complete; this file written. Next: timestamped backup of bets.js to `backups/`, then git baseline.
