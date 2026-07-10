#!/bin/bash
# Double-click to run the prediction engine on demand.
cd "$(dirname "$0")"
/usr/bin/python3 engine.py
echo ""
echo "Done — open index.html to see the picks. Press any key to close."
read -n 1
