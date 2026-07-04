#!/bin/bash
# DeepStack Trading Bot Launcher
# Called by launchd to start the bot with the correct environment.
# Activates the Python venv and runs in multi-strategy mode.

set -euo pipefail

# Derive BOT_DIR from this script's location so a moved/renamed checkout
# doesn't leave launchd crash-looping on a stale hardcoded path.
# Override with BOT_DIR env var if the repo lives elsewhere.
BOT_DIR="${BOT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
VENV_DIR="${BOT_DIR}/venv"
if [ ! -d "${VENV_DIR}" ] && [ -d "${BOT_DIR}/.venv" ]; then
    VENV_DIR="${BOT_DIR}/.venv"
fi
LOG_DIR="${HOME}/Library/Logs/deepstack"

# Ensure log directory exists
mkdir -p "${LOG_DIR}"

# Activate the virtual environment
source "${VENV_DIR}/bin/activate"

# Change to the bot directory (so relative paths in config.yaml work)
cd "${BOT_DIR}"

# Load .env if present (run_bot.py does this too, but belt-and-suspenders)
if [ -f "${BOT_DIR}/.env" ]; then
    set -a
    source "${BOT_DIR}/.env"
    set +a
fi

# Start the bot in multi-strategy mode — LIVE TRADING
# Graduated 2026-03-11: 145 trades, 86.9% WR, $683.60 PnL, 17.5% max DD
exec python3 "${BOT_DIR}/run_bot.py" --multi
