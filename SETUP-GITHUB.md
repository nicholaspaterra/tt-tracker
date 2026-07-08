# ☁️ Run 24/7 in the cloud (Mac off, tab closed — doesn't matter)

One-time setup, ~10 minutes. After this, the engine runs hourly on GitHub's servers and your dashboard is a website you can open from your phone, laptop, anywhere.

## Steps

1. **Create a free GitHub account** at github.com (skip if you have one).

2. **Create a new repository**: github.com/new → name it `tt-tracker` → set it to **Public** → Create.
   - ⚠️ Public means anyone who finds the repo can see your bet history and bankroll numbers. It contains no personal/financial info beyond that, but know it's visible. (GitHub Pages on private repos requires a paid plan.)

3. **Upload this whole folder**: on the repo page → "uploading an existing file" link → drag in ALL files in this folder **including the hidden `.github` folder** (in Finder press Cmd+Shift+. to show hidden files) → Commit.
   - If the `.github` folder won't drag, create the file manually: repo → Add file → Create new file → type `.github/workflows/engine.yml` as the name → paste the contents of that file → Commit.

4. **Enable the hourly runs**: repo → Actions tab → enable workflows if prompted → click "TT Engine (hourly)" → "Run workflow" to test it right now. A green check = working; click into the run to see the engine log.

5. **Turn the dashboard into a website**: repo → Settings → Pages → Source: "Deploy from a branch" → Branch: `main`, folder `/ (root)` → Save. After ~2 minutes your dashboard is live at:
   `https://YOUR-USERNAME.github.io/tt-tracker/`

## Things to know

- **Pick one home.** Cloud and local both running means two separate copies of the data that don't sync. Once cloud works, remove the local schedule: `bash install.sh remove`.
- **The website is read-only.** The engine does everything (log, settle, odds), so normally you touch nothing. But manual edits made in the browser (W/L/P, Edit, Del, unit size) won't survive a page reload on the website — to change something by hand, edit `bets.js` directly on GitHub (open the file → pencil icon → commit).
- **Timing:** GitHub runs hourly jobs on a best-effort basis — a run can start a few minutes late. Scheduled workflows pause if the repo sees no activity for 60 days, but the engine's own hourly commits count as activity, so this only matters if the engine breaks; a manual "Run workflow" click revives it.
- **If runs suddenly fail:** open the Actions log. If it shows fetch errors, the data source may be blocking GitHub's server IPs or changed its layout — bring the log back to Claude to get the engine fixed.
