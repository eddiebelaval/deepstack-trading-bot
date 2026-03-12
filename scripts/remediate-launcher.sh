#!/bin/bash
# Launcher for Tier 2 Claude-routed remediation
# Sources env vars and runs remediate.py
# Called by launchd every 5 minutes: com.id8labs.deepstack-remediate

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BOT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$BOT_DIR"

# Source env vars
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

# Activate venv if present
if [ -f .venv/bin/activate ]; then
    source .venv/bin/activate
fi

exec python3 scripts/remediate.py
