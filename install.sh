#!/bin/bash
# TT Tracker — installs the engine.py auto-run every hour (macOS launchd).
# Run once:  bash install.sh     Uninstall:  bash install.sh remove
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.tt-tracker.engine"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

if [ "$1" = "remove" ]; then
  launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Removed daily auto-run."
  exit 0
fi

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>$DIR/engine.py</string>
  </array>
  <key>StartInterval</key><integer>3600</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$DIR/engine_log.txt</string>
  <key>StandardErrorPath</key><string>$DIR/engine_log.txt</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Installed: engine.py runs every hour, around the clock (and once right now)."
echo "Note: the Mac must be awake; a missed run happens at next wake. Manual run: python3 \"$DIR/engine.py\""
