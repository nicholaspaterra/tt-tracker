#!/bin/bash
# TT Tracker — Mac-side run dispatcher.
#
# GitHub's cron scheduler is best-effort and often skips 30-minute schedules.
# This installs a launchd job that pokes GitHub every 30 minutes (while the
# Mac is awake) to start an engine run in the cloud. The cloud cron remains
# the fallback when the Mac is asleep. The engine itself always runs on
# GitHub's servers — this machine's network is bot-blocked by the data source.
#
# Requires: gh CLI authenticated (gh auth status).
# Run once:  bash install.sh     Uninstall:  bash install.sh remove
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.tt-tracker.dispatch"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
GH="$(command -v gh || echo "$HOME/.local/bin/gh")"

if [ "$1" = "remove" ]; then
  launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  # also remove the old local-engine job if present
  launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.tt-tracker.engine.plist" 2>/dev/null || true
  rm -f "$HOME/Library/LaunchAgents/com.tt-tracker.engine.plist"
  echo "Removed dispatcher."
  exit 0
fi

"$GH" auth status >/dev/null 2>&1 || { echo "gh CLI is not authenticated — run: gh auth login"; exit 1; }

cat > "$DIR/dispatch.sh" <<EOF
#!/bin/bash
# Poke GitHub to run the engine now (skips if a run is already in progress).
GH="$GH"
BUSY=\$("\$GH" run list --repo nicholaspaterra/tt-tracker --workflow=engine.yml --limit 1 --json status -q '.[0].status' 2>/dev/null)
[ "\$BUSY" = "in_progress" ] || [ "\$BUSY" = "queued" ] && exit 0
"\$GH" workflow run engine.yml --repo nicholaspaterra/tt-tracker 2>/dev/null || true
EOF
chmod +x "$DIR/dispatch.sh"

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$DIR/dispatch.sh</string>
  </array>
  <key>StartInterval</key><integer>1800</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$DIR/dispatch_log.txt</string>
  <key>StandardErrorPath</key><string>$DIR/dispatch_log.txt</string>
</dict>
</plist>
EOF

# retire the old local-engine job (engine now runs in the cloud only)
launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.tt-tracker.engine.plist" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/com.tt-tracker.engine.plist"

launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Installed: cloud run dispatched every 30 min while this Mac is awake (and once right now)."
