#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────
# Dae — DeepStack Trading Bot — Linux Server Setup
# ──────────────────────────────────────────────────────────
# Bootstraps a fresh Linux server (Ubuntu/Debian) to run Dae.
#
# What this does:
#   1. Creates 'deepstack' service user
#   2. Installs Python 3.11+ and system deps
#   3. Clones repo to /opt/deepstack
#   4. Creates venv and installs requirements
#   5. Installs systemd service + logrotate
#   6. Sets up log directory and permissions
#
# What this does NOT do:
#   - Write your .env file (you must provide credentials)
#   - Place your kalshi_private_key.pem (you must copy it)
#   - Start the service (you do that after configuring .env)
#
# Usage:
#   sudo bash deploy/setup.sh
#
# After setup:
#   1. Copy .env to /opt/deepstack/.env
#   2. Copy kalshi_private_key.pem to /opt/deepstack/
#   3. sudo systemctl start deepstack
#   4. sudo journalctl -u deepstack -f
# ──────────────────────────────────────────────────────────
set -euo pipefail

INSTALL_DIR="/opt/deepstack"
SERVICE_USER="deepstack"
LOG_DIR="/var/log/deepstack"
REPO_URL="https://github.com/eddiebelaval/kalshi-trading.git"

# ── Preflight ────────────────────────────────────────────

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: Must run as root (sudo bash deploy/setup.sh)"
    exit 1
fi

if ! command -v apt-get &>/dev/null; then
    echo "ERROR: This script requires apt-get (Ubuntu/Debian)"
    echo "For other distros, adapt the package install section."
    exit 1
fi

echo "============================================"
echo "  Dae — DeepStack Server Setup"
echo "  The Craftsman Who Never Sleeps"
echo "============================================"
echo ""

# ── 1. System dependencies ──────────────────────────────

echo "[1/6] Installing system dependencies..."
apt-get update -qq
apt-get install -y -qq \
    python3.11 \
    python3.11-venv \
    python3.11-dev \
    git \
    curl \
    build-essential \
    libffi-dev \
    libssl-dev \
    2>/dev/null

# Fallback: if python3.11 not available, try python3
if ! command -v python3.11 &>/dev/null; then
    echo "  python3.11 not found, using system python3..."
    PYTHON_BIN="python3"
else
    PYTHON_BIN="python3.11"
fi

PYTHON_VERSION=$("${PYTHON_BIN}" --version 2>&1)
echo "  Python: ${PYTHON_VERSION}"

# ── 2. Service user ─────────────────────────────────────

echo "[2/6] Creating service user '${SERVICE_USER}'..."
if id "${SERVICE_USER}" &>/dev/null; then
    echo "  User '${SERVICE_USER}' already exists, skipping."
else
    useradd \
        --system \
        --shell /usr/sbin/nologin \
        --home-dir "${INSTALL_DIR}" \
        --create-home \
        "${SERVICE_USER}"
    echo "  Created user '${SERVICE_USER}'"
fi

# ── 3. Clone or update repo ─────────────────────────────

echo "[3/6] Setting up ${INSTALL_DIR}..."
if [ -d "${INSTALL_DIR}/.git" ]; then
    echo "  Repo exists, pulling latest..."
    cd "${INSTALL_DIR}"
    sudo -u "${SERVICE_USER}" git pull --ff-only origin main || {
        echo "  WARNING: git pull failed (dirty state?). Skipping pull."
    }
else
    if [ -d "${INSTALL_DIR}" ] && [ "$(ls -A ${INSTALL_DIR} 2>/dev/null)" ]; then
        echo "  ${INSTALL_DIR} exists but is not a git repo."
        echo "  If you want to install from local files, copy them to ${INSTALL_DIR}."
        echo "  Otherwise, remove ${INSTALL_DIR} and re-run this script."
        exit 1
    fi
    git clone "${REPO_URL}" "${INSTALL_DIR}"
    chown -R "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}"
fi

cd "${INSTALL_DIR}"

# ── 4. Python venv + dependencies ───────────────────────

echo "[4/6] Creating Python virtual environment..."
if [ ! -d "${INSTALL_DIR}/.venv" ]; then
    sudo -u "${SERVICE_USER}" "${PYTHON_BIN}" -m venv "${INSTALL_DIR}/.venv"
    echo "  Created .venv"
else
    echo "  .venv exists, skipping creation."
fi

echo "  Installing dependencies..."
sudo -u "${SERVICE_USER}" "${INSTALL_DIR}/.venv/bin/pip" install --quiet --upgrade pip
sudo -u "${SERVICE_USER}" "${INSTALL_DIR}/.venv/bin/pip" install --quiet -r "${INSTALL_DIR}/requirements.txt"

INSTALLED_COUNT=$("${INSTALL_DIR}/.venv/bin/pip" list --format=columns 2>/dev/null | wc -l)
echo "  Installed ${INSTALLED_COUNT} packages"

# ── 5. Systemd service + logrotate ──────────────────────

echo "[5/6] Installing systemd service..."
cp "${INSTALL_DIR}/deploy/deepstack.service" /etc/systemd/system/deepstack.service
systemctl daemon-reload
systemctl enable deepstack
echo "  Installed and enabled deepstack.service"

echo "  Installing logrotate config..."
cp "${INSTALL_DIR}/deploy/deepstack.logrotate" /etc/logrotate.d/deepstack
echo "  Installed /etc/logrotate.d/deepstack"

# ── 6. Log directory + permissions ──────────────────────

echo "[6/6] Setting up directories and permissions..."
mkdir -p "${LOG_DIR}"
chown "${SERVICE_USER}:${SERVICE_USER}" "${LOG_DIR}"
chmod 750 "${LOG_DIR}"

# Ensure writable paths for systemd ReadWritePaths
touch "${INSTALL_DIR}/trade_journal.db" 2>/dev/null || true
touch "${INSTALL_DIR}/arena_results.db" 2>/dev/null || true
mkdir -p "${INSTALL_DIR}/kalshi_trader/mind/memory"
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}"

echo ""
echo "============================================"
echo "  Setup complete."
echo "============================================"
echo ""
echo "  Next steps:"
echo ""
echo "  1. Copy credentials:"
echo "     cp /path/to/.env ${INSTALL_DIR}/.env"
echo "     cp /path/to/kalshi_private_key.pem ${INSTALL_DIR}/"
echo "     chown ${SERVICE_USER}:${SERVICE_USER} ${INSTALL_DIR}/.env ${INSTALL_DIR}/kalshi_private_key.pem"
echo "     chmod 600 ${INSTALL_DIR}/.env ${INSTALL_DIR}/kalshi_private_key.pem"
echo ""
echo "  2. Verify config:"
echo "     cat ${INSTALL_DIR}/config.yaml"
echo ""
echo "  3. Start Dae:"
echo "     sudo systemctl start deepstack"
echo ""
echo "  4. Watch logs:"
echo "     sudo journalctl -u deepstack -f"
echo ""
echo "  5. Check status:"
echo "     sudo systemctl status deepstack"
echo ""
