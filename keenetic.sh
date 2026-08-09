#!/usr/bin/env bash
#
# keenetic.sh — launcher for the Keenetic REST API utility
#
# Usage:
#   ./keenetic.sh                # normal run
#   ./keenetic.sh --debug        # debug mode
#   KEENETIC_ROUTER_IP="10.0.0.1" KEENETIC_ROUTER_PASSWORD="password" ./keenetic.sh
#
# The script can be run from any directory.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Find Python 3
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON="$cmd"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "[!] Python 3 not found. Install Python 3." >&2
    exit 1
fi

if [ ! -f "$SCRIPT_DIR/keenetic/__main__.py" ]; then
    echo "[!] Package keenetic not found: $SCRIPT_DIR/keenetic" >&2
    exit 1
fi

# Add the repository root to PYTHONPATH so the keenetic package is visible
# (needed for python -m keenetic / from keenetic.cli import main)
export PYTHONPATH="${SCRIPT_DIR}:${PYTHONPATH}"

exec "$PYTHON" -m keenetic "$@"
