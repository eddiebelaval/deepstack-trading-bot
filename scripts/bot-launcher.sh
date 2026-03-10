#!/bin/bash
# DeepStack Trading Bot Launcher
# Called by launchd to start the bot with the correct environment.
# Activates the Python venv and runs in multi-strategy mode.

set -euo pipefail

BOT_DIR="/Users/eddiebelaval/clawd/projects/kalshi-trading"
VENV_DIR="${BOT_DIR}/venv"
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

# Start the bot in multi-strategy mode with paper balance
# Paper trading at $2,000 until graduation gates pass per asset class
exec python3 "${BOT_DIR}/run_bot.py" --multi --paper-balance 2000
