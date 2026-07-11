#!/bin/bash
# Poke GitHub to run the engine now (skips if a run is already in progress).
GH="/Users/nickpaterra/.local/bin/gh"
BUSY=$("$GH" run list --repo nicholaspaterra/tt-tracker --workflow=engine.yml --limit 1 --json status -q '.[0].status' 2>/dev/null)
[ "$BUSY" = "in_progress" ] || [ "$BUSY" = "queued" ] && exit 0
"$GH" workflow run engine.yml --repo nicholaspaterra/tt-tracker 2>/dev/null || true
