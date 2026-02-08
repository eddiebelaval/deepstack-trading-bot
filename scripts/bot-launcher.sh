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

# Load env from outside the repo (avoid secrets living next to git).
DEFAULT_ENV_PATH="${HOME}/Library/Application Support/deepstack/kalshi-trading.env"
ENV_PATH="${DEEPSTACK_BOT_ENV_PATH:-$DEFAULT_ENV_PATH}"
if [ -f "${ENV_PATH}" ]; then
    set -a
    source "${ENV_PATH}"
    set +a
fi

# Start the bot in multi-strategy mode
exec python3 "${BOT_DIR}/run_bot.py" --multi
