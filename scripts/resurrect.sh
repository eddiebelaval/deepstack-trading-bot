#!/bin/bash
# Dae Resurrection Script — bring the bot back to life on this Mac.
#
# Run from anywhere inside the checkout:
#   bash scripts/resurrect.sh          # full sequence, ends with preflight
#   bash scripts/resurrect.sh --dry    # show what would happen, change nothing
#
# What it does:
#   1. git pull on main
#   2. Installs/updates dependencies into the venv (creates one if missing)
#   3. Regenerates both launchd plists with THIS checkout's absolute paths
#      (the bot service + the Tier-2 remediate/dead-man watchdog)
#   4. Bootstraps both services with launchd
#   5. Runs preflight and prints the go-live checklist
#
# It does NOT enable live trading by itself — the bot starts in whatever
# mode config.yaml specifies, and a stale high-water mark may hold live
# trading halted until you send "reset hwm" via Telegram.

set -euo pipefail

BOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAUNCH_AGENTS="${HOME}/Library/LaunchAgents"
BOT_LABEL="com.id8labs.deepstack-bot"
WATCHDOG_LABEL="com.id8labs.deepstack-remediate"
DRY=0
[ "${1:-}" = "--dry" ] && DRY=1

say() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
run() {
    if [ "$DRY" = 1 ]; then
        echo "[dry] $*"
    else
        "$@"
    fi
}

cd "$BOT_DIR"

say "1/5 Updating code (git pull on main)"
run git checkout main
run git pull

say "2/5 Python environment"
VENV_DIR="$BOT_DIR/venv"
[ -d "$BOT_DIR/.venv" ] && [ ! -d "$VENV_DIR" ] && VENV_DIR="$BOT_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "No venv found — creating $VENV_DIR"
    run python3 -m venv "$VENV_DIR"
fi
run "$VENV_DIR/bin/pip" install -q -r requirements.txt
echo "Dependencies installed into $VENV_DIR"

say "3/5 Generating launchd plists for this checkout ($BOT_DIR)"
mkdir -p "$LAUNCH_AGENTS"

BOT_PLIST="$LAUNCH_AGENTS/$BOT_LABEL.plist"
WATCHDOG_PLIST="$LAUNCH_AGENTS/$WATCHDOG_LABEL.plist"

gen_plist() {
    # $1 = template path, $2 = destination
    if [ "$DRY" = 1 ]; then
        echo "[dry] would render $1 -> $2 with paths under $BOT_DIR"
        return
    fi
    sed "s|/Users/eddiebelaval/clawd/projects/kalshi-trading|$BOT_DIR|g" "$1" > "$2"
    echo "Installed $2"
}

gen_plist "$BOT_DIR/com.id8labs.deepstack-bot.plist" "$BOT_PLIST"
gen_plist "$BOT_DIR/deploy/com.id8labs.deepstack-remediate.plist" "$WATCHDOG_PLIST"

say "4/5 Bootstrapping launchd services"
UID_NUM="$(id -u)"
for label in "$BOT_LABEL" "$WATCHDOG_LABEL"; do
    plist="$LAUNCH_AGENTS/$label.plist"
    # bootout is idempotent-ish: ignore "not loaded" errors
    run launchctl bootout "gui/$UID_NUM/$label" 2>/dev/null || true
    run launchctl bootstrap "gui/$UID_NUM" "$plist"
    run launchctl kickstart "gui/$UID_NUM/$label"
    echo "Started $label"
done

say "5/5 Preflight"
if [ "$DRY" = 1 ]; then
    echo "[dry] would run: $VENV_DIR/bin/python scripts/preflight.py"
else
    "$VENV_DIR/bin/python" scripts/preflight.py || true
fi

say "Post-launch checklist"
cat <<'EOF'
  [ ] Watch the log for a clean boot:
        tail -f ~/Library/Logs/deepstack/bot-stdout.log
  [ ] If DEEPSTACK_PATH is unset in .env you'll see one warning about
      internal risk fallbacks — that's fine; set it to restore the full
      DeepStack sizer if the sibling repo exists on this machine.
  [ ] If Telegram reports "LIVE TRADING HALTED ... stale high-water mark",
      reply:  reset hwm
  [ ] Confirm the dead-man watchdog is armed:
        launchctl print gui/$UID/com.id8labs.deepstack-remediate | grep state
  [ ] Dashboard should show the bot online within ~2 minutes.
EOF
