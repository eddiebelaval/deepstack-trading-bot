#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────
# Dae — DeepStack Trading Bot — Deploy / Update Script
# ──────────────────────────────────────────────────────────
# Pulls latest code, installs deps, restarts the service.
# Safe to run on a live system — stops the bot gracefully
# before updating, then restarts.
#
# Usage:
#   sudo bash deploy/deploy.sh
#   sudo bash deploy/deploy.sh --branch feat/some-branch
# ──────────────────────────────────────────────────────────
set -euo pipefail

INSTALL_DIR="/opt/deepstack"
SERVICE_USER="deepstack"
BRANCH="${1:-main}"

# Handle --branch flag
if [ "${BRANCH}" = "--branch" ]; then
    BRANCH="${2:-main}"
fi

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: Must run as root"
    exit 1
fi

echo "============================================"
echo "  Dae — Deploying (branch: ${BRANCH})"
echo "============================================"

# ── 1. Pre-deploy snapshot ──────────────────────────────

CURRENT_COMMIT=$(cd "${INSTALL_DIR}" && sudo -u "${SERVICE_USER}" git rev-parse --short HEAD 2>/dev/null || echo "unknown")
echo "Current commit: ${CURRENT_COMMIT}"

# ── 2. Stop the bot gracefully ──────────────────────────

echo "Stopping deepstack service..."
if systemctl is-active --quiet deepstack; then
    systemctl stop deepstack
    echo "  Stopped. Waiting for clean shutdown..."
    sleep 3
else
    echo "  Service not running."
fi

# ── 3. Pull latest code ────────────────────────────────

echo "Pulling latest code..."
cd "${INSTALL_DIR}"
sudo -u "${SERVICE_USER}" git fetch origin
sudo -u "${SERVICE_USER}" git checkout "${BRANCH}"
sudo -u "${SERVICE_USER}" git pull --ff-only origin "${BRANCH}"

NEW_COMMIT=$(sudo -u "${SERVICE_USER}" git rev-parse --short HEAD)
echo "  ${CURRENT_COMMIT} -> ${NEW_COMMIT}"

# ── 4. Update dependencies ─────────────────────────────

echo "Updating dependencies..."
sudo -u "${SERVICE_USER}" "${INSTALL_DIR}/.venv/bin/pip" install --quiet -r "${INSTALL_DIR}/requirements.txt"

# ── 5. Run tests (optional but recommended) ─────────────

echo "Running smoke tests..."
if sudo -u "${SERVICE_USER}" "${INSTALL_DIR}/.venv/bin/python" -m pytest tests/ -x -q --tb=short 2>/dev/null; then
    echo "  Tests passed."
else
    echo "  WARNING: Tests failed. Proceeding anyway (check manually)."
    echo "  To abort: Ctrl+C now, then 'sudo systemctl start deepstack' to rollback."
    sleep 5
fi

# ── 6. Update systemd if service file changed ──────────

if ! diff -q "${INSTALL_DIR}/deploy/deepstack.service" /etc/systemd/system/deepstack.service &>/dev/null; then
    echo "Service file changed, updating..."
    cp "${INSTALL_DIR}/deploy/deepstack.service" /etc/systemd/system/deepstack.service
    systemctl daemon-reload
fi

# ── 7. Restart ──────────────────────────────────────────

echo "Starting deepstack service..."
systemctl start deepstack
sleep 2

if systemctl is-active --quiet deepstack; then
    echo ""
    echo "============================================"
    echo "  Deploy complete. Dae is running."
    echo "  ${CURRENT_COMMIT} -> ${NEW_COMMIT}"
    echo "============================================"
    echo ""
    echo "  Watch logs: sudo journalctl -u deepstack -f"
else
    echo ""
    echo "  ERROR: Service failed to start!"
    echo "  Check: sudo journalctl -u deepstack --no-pager -n 50"
    exit 1
fi
