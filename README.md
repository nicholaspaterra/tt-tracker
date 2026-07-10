# 🏓 TT Tracker — betting analysis + bankroll tracking

## Files
- **index.html** — the dashboard. Open in Chrome/Edge. Bet log, P&L, charts, ROI by grade AND by circuit, and the "Claude's daily picks" panel (fed by the engine). Czech amateur picks wear an amber CZE chip.
- **bets.js** — all data (settings, picks, bets). The app and engine both read/write it. The engine snapshots it to `backups/` before every run.
- **engine.py** — the autonomous prediction engine. Fetches ITTF rankings, recent results, and upcoming WTT singles matches; models win probabilities; writes picks into bets.js.
- **czech.py + elo.py + elo.json** — the Czech amateur circuit (Czech Liga Pro, TT Cup). These players aren't in ITTF rankings, so a self-maintained Elo store is bootstrapped from scraped results. Players with <10 rated matches are unbettable (NO BET); every amateur pick is grade-capped at C (half stake, max 1u) until the ROI-by-circuit table proves the circuit out. See DECISIONS.md.
- **tests/** — 68 mocked tests incl. real captured protobuf fixtures. `python3 -m pytest tests/ -q`. `smoke_live.py` is the only thing that ever touches the live site outside engine runs, and only when you run it by hand.
- **install.sh** — sets up hourly auto-runs (`bash install.sh`; remove with `bash install.sh remove`).
- **Run Analysis.command** — double-click to run the engine any time.
- **engine_log.txt** — what the engine did each run.

## Setup (once)
1. Move this whole `tt-tracker` folder somewhere permanent (e.g. Documents).
2. `bash install.sh` in Terminal (from inside the folder) → daily 9 AM runs.
3. Open index.html → click **Link data file** → pick bets.js → your in-app edits auto-save.

## Daily flow (fully hands-off)
Every hour (while the Mac is awake), the engine:
1. Models each upcoming WTT singles match, **auto-pulls the bookmaker line** (bet365 via AiScore's odds feed), strips the vig, computes edge + quarter-Kelly stake (≥6% edge = BET, capped at 2 units, C-grade halved).
2. **Auto-logs every BET pick** into Active bets as pending (one entry per match, never duplicated; NO BET picks are shown in the picks panel but not logged). The 6% edge bar is deliberately strict — fewer bets, each with more margin for model error. To change it, edit MIN_EDGE in engine.py (and the matching constant in index.html).
3. **Auto-settles** finished matches from final scores — the bet moves from Active bets into the collapsible **History** section, and its win/loss stays in every stat, chart, and the bankroll forever.

You don't have to touch anything. Manual controls still exist if you want them: W/L/P buttons, Edit/Del on any bet, odds boxes on picks whose line wasn't posted yet, and + Add bet for bets you place on your own.

**Reminder:** this logs and tracks bets — it does not place them at your sportsbook. If you're betting real money, place the wager yourself and check the live line first (the engine's odds are a snapshot from its last run).

## How the model works (transparent, no magic)
Bradley-Terry base rate from ITTF ranking points (softened with a 0.75 exponent), adjusted in log-odds space for recent form (last-10 win rate), head-to-head (when ≥3 meetings), and fatigue (matches in last 3 days). Probabilities are clamped to 5-95%. Grade: A = rich data (H2H ≥5, 10+ recent matches each), C = thin H2H (<3) or <5 recent matches — C picks stake half. Data source: m.aiscore.com (server-rendered pages, ITTF-sanctioned events only; amateur leagues like Setka Cup are excluded); odds from api.aiscore.com (bet365 line).

**Honest limitations:** the model is a heuristic — it estimates, it doesn't know. Odds are a single book's line captured at run time — lines move, so glance at your book's current price before betting. Table tennis markets are thin; expect variance. Nothing here is financial advice — bet only what you can afford to lose.
