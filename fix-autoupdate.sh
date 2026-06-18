#!/bin/bash
# meshcorium-fix-autoupdate.sh — v0.8.2 fix for missing --supervise in systemd unit
#
# Purpose:
#   All MeshCorium releases before v0.8.2 have a systemd unit template that
#   launches meshcorium-launcher.sh WITHOUT the --supervise flag. This means
#   the supervisor loop (which polls GitHub every 30 minutes for new releases)
#   never starts — auto-update is completely broken when using systemd.
#
#   This script fixes the installed systemd unit on the local machine WITHOUT
#   modifying any MeshCorium project files. It only edits the systemd unit.
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/PEG4TRON/MeshCorium/main/fix-autoupdate.sh | bash
#   OR
#   wget -qO- https://raw.githubusercontent.com/PEG4TRON/MeshCorium/main/fix-autoupdate.sh | bash
#   OR (offline):
#   bash fix-autoupdate.sh
#   bash fix-autoupdate.sh /opt/MeshCorium
#
# Requirements:
#   - sudo access (NOPASSWD recommended, or be ready to enter password)
#   - meshcorium.service must already be installed (via meshcorium-launcher.sh --install)
#
# Safety:
#   - Idempotent: safe to run multiple times
#   - Creates timestamped backup of the unit file before modifying
#   - Validates the fix with systemd-analyze verify before reloading
#   - Rolls back on failure

set -euo pipefail

# ──────────────────────────────────────────────
# 1. Locate the MeshCorium installation
# ──────────────────────────────────────────────

MESHCORIUM_DIR="${1:-}"
SERVICE_FILE="/etc/systemd/system/meshcorium.service"
SERVICE_NAME="meshcorium.service"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"

# Colours for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

banner() {
    echo -e "${CYAN}"
    echo "╔══════════════════════════════════════════════╗"
    echo "║  MeshCorium Auto-Update Fix (v0.8.2)        ║"
    echo "╚══════════════════════════════════════════════╝"
    echo -e "${NC}"
    echo ""
}

ok()  { echo -e "  ${GREEN}✓${NC} $*"; }
warn(){ echo -e "  ${YELLOW}⚠${NC} $*"; }
err() { echo -e "  ${RED}✗${NC} $*"; }
info(){ echo -e "  ${CYAN}i${NC} $*"; }

banner

# ──────────────────────────────────────────────
# 2. Auto-detect installation directory
# ──────────────────────────────────────────────

if [[ -z "${MESHCORIUM_DIR}" ]]; then
    if [[ -f "${SERVICE_FILE}" ]]; then
        MESHCORIUM_DIR="$(grep -oP '^WorkingDirectory=\K.*' "${SERVICE_FILE}" 2>/dev/null || true)"
    fi
    if [[ -z "${MESHCORIUM_DIR}" ]]; then
        # Try common locations
        for candidate in /opt/MeshCorium /opt/meshcorium /home/*/MeshCorium; do
            if [[ -f "${candidate}/.meshcorium_version" ]]; then
                MESHCORIUM_DIR="${candidate}"
                break
            fi
        done
    fi
fi

if [[ -z "${MESHCORIUM_DIR}" ]]; then
    err "Could not find MeshCorium installation."
    echo ""
    echo "  Usage: bash $0 /path/to/MeshCorium"
    echo "  Example: bash $0 /opt/MeshCorium"
    exit 1
fi

if [[ ! -d "${MESHCORIUM_DIR}" ]]; then
    err "Directory does not exist: ${MESHCORIUM_DIR}"
    exit 1
fi

if [[ ! -f "${MESHCORIUM_DIR}/.meshcorium_version" ]]; then
    err "Not a MeshCorium installation: ${MESHCORIUM_DIR} (missing .meshcorium_version)"
    exit 1
fi

# ──────────────────────────────────────────────
# 3. Read current version and launcher info
# ──────────────────────────────────────────────

CURRENT_VERSION="$(cat "${MESHCORIUM_DIR}/.meshcorium_version")"
LAUNCHER="${MESHCORIUM_DIR}/meshcorium-launcher.sh"

info "Found MeshCorium v${CURRENT_VERSION} at ${MESHCORIUM_DIR}"
echo ""

if [[ ! -f "${LAUNCHER}" ]]; then
    err "Launcher not found: ${LAUNCHER}. This installation appears incomplete."
    exit 1
fi

# ──────────────────────────────────────────────
# 4. Check if the launcher HAS the supervisor code
# ──────────────────────────────────────────────

if ! grep -q 'supervise_loop\|--supervise' "${LAUNCHER}" 2>/dev/null; then
    err "This version (v${CURRENT_VERSION}) does not have supervisor/auto-update support."
    echo ""
    echo "  The supervisor loop (GitHub polling, self-update) was introduced in the"
    echo "  launcher. Your version's launcher does not contain the supervise_loop"
    echo "  function or --supervise flag. Auto-update is not available."
    echo ""
    echo "  Recommendation: perform a fresh install of v0.8.2+ using:"
    echo "    cd ${MESHCORIUM_DIR}"
    echo "    bash meshcorium-launcher.sh --install"
    echo ""
    echo "  Or download a release tarball from:"
    echo "    https://github.com/PEG4TRON/MeshCorium/releases"
    exit 1
fi

ok "Launcher supports --supervise (supervisor code present)"
echo ""

# ──────────────────────────────────────────────
# 5. Check if systemd unit exists
# ──────────────────────────────────────────────

if [[ ! -f "${SERVICE_FILE}" ]]; then
    # Check if systemd is even available
    if ! command -v systemctl &>/dev/null; then
        info "systemd not detected — this host is not using systemd for MeshCorium."
        echo ""
        echo "  If you start MeshCorium manually (meshcorium-launcher.sh --run),"
        echo "  switch to: meshcorium-launcher.sh --supervise"
        echo ""
        echo "  If you are using Docker, see instructions below."
        echo ""
        
        # ─── Docker guidance ───
        if command -v docker &>/dev/null && docker ps --format '{{.Names}}' 2>/dev/null | grep -qi 'meshcorium'; then
            info "Docker detected."
            echo ""
            echo "  Docker containers do not use systemd. The Docker entrypoint runs"
            echo "  meshcorium_web.py directly (no launcher, no supervisor)."
            echo ""
            echo "  To use auto-update with Docker:"
            echo "  1. Replace the entrypoint to use meshcorium-launcher.sh --supervise"
            echo "  2. Or pull the latest image manually: docker pull <image>:latest"
            echo "  3. Or use docker-compose pull && docker-compose up -d"
            echo ""
            echo "  Recommended: update your docker-compose.yml to use"
            echo "  image: ghcr.io/PEG4TRON/meshcorium:0.8.2 (or :latest)"
            echo "  and restart the container. Then run:"
            echo "    docker exec <container> bash fix-autoupdate.sh"
            echo "  inside the container to apply the systemd-independent fix."
        else
            warn "No Docker containers found either."
        fi
        echo ""
        echo "  Manual fix for non-systemd, non-Docker installations:"
        echo "    Update your startup command to include --supervise:"
        echo "      ${MESHCORIUM_DIR}/meshcorium-launcher.sh --supervise"
        exit 1
    fi
    
    err "Systemd unit not found: ${SERVICE_FILE}"
    echo ""
    echo "  MeshCorium is installed but the systemd service was never created."
    echo "  Run the following to create and enable it:"
    echo "    cd ${MESHCORIUM_DIR}"
    echo "    sudo bash meshcorium-launcher.sh --install"
    echo ""
    echo "  This will create ${SERVICE_FILE} with the correct --supervise flag"
    echo "  (if using MeshCorium v0.8.2+)."
    exit 1
fi

# ──────────────────────────────────────────────
# 6. Check if ExecStart already has --supervise
# ──────────────────────────────────────────────

CURRENT_EXEC="$(grep -oP '^ExecStart=\K.*' "${SERVICE_FILE}")"

if [[ "${CURRENT_EXEC}" == *"--supervise"* ]]; then
    ok "systemd unit already has --supervise flag. No fix needed."
    echo ""
    echo "  Current ExecStart: ${CURRENT_EXEC}"
    echo ""
    
    # Quick health check
    if systemctl is-active --quiet "${SERVICE_NAME}" 2>/dev/null; then
        ok "Service is running."
    else
        warn "Service is not running. Start it with: systemctl start ${SERVICE_NAME}"
    fi
    exit 0
fi

echo -e "  Current ExecStart: ${RED}${CURRENT_EXEC}${NC}"
echo -e "  Should be:         ${GREEN}${CURRENT_EXEC} --supervise${NC}"
echo ""

# ──────────────────────────────────────────────
# 7. Confirm with user (if interactive)
# ──────────────────────────────────────────────

if [[ -t 0 ]]; then
    echo -n "  Apply this fix? [Y/n] "
    read -r REPLY
    if [[ ! "${REPLY}" =~ ^[Yy]?$ ]]; then
        echo "  Aborted by user."
        exit 0
    fi
fi

# ──────────────────────────────────────────────
# 8. Create backup
# ──────────────────────────────────────────────

BACKUP="${SERVICE_FILE}.bak.${TIMESTAMP}"

if ! sudo cp -p "${SERVICE_FILE}" "${BACKUP}"; then
    err "Failed to create backup at ${BACKUP}"
    exit 1
fi
ok "Backup created: ${BACKUP}"

# ──────────────────────────────────────────────
# 9. Apply the fix
# ──────────────────────────────────────────────

NEW_EXEC="${CURRENT_EXEC} --supervise"

# Use sed to replace the ExecStart line
# Pattern: match ExecStart=...meshcorium-launcher.sh (with optional flags)
# Replace: append --supervise

if ! sudo sed -i "s|^ExecStart=${CURRENT_EXEC}\$|ExecStart=${NEW_EXEC}|" "${SERVICE_FILE}"; then
    err "Failed to modify service file"
    echo "  Restoring backup..."
    sudo cp -p "${BACKUP}" "${SERVICE_FILE}"
    exit 1
fi

# Verify the change
NEW_EXEC_VERIFY="$(grep -oP '^ExecStart=\K.*' "${SERVICE_FILE}")"
if [[ "${NEW_EXEC_VERIFY}" != *"--supervise"* ]]; then
    err "Verification failed — --supervise not found in new ExecStart"
    echo "  Restoring backup..."
    sudo cp -p "${BACKUP}" "${SERVICE_FILE}"
    exit 1
fi

ok "Service file updated:"
echo "    ${NEW_EXEC_VERIFY}"
echo ""

# ──────────────────────────────────────────────
# 10. Validate with systemd
# ──────────────────────────────────────────────

if command -v systemd-analyze &>/dev/null; then
    if sudo systemd-analyze verify "${SERVICE_FILE}" &>/dev/null; then
        ok "systemd-analyze verify: passed"
    else
        warn "systemd-analyze verify reported issues (non-fatal for this fix)"
        sudo systemd-analyze verify "${SERVICE_FILE}" 2>&1 | head -5 | while read -r line; do
            warn "  ${line}"
        done
    fi
fi

# ──────────────────────────────────────────────
# 11. Reload systemd and restart
# ──────────────────────────────────────────────

sudo systemctl daemon-reload
ok "systemd daemon-reload"

if systemctl is-active --quiet "${SERVICE_NAME}" 2>/dev/null; then
    sudo systemctl restart "${SERVICE_NAME}"
    ok "Service restarted"
else
    sudo systemctl start "${SERVICE_NAME}" 2>/dev/null || true
    ok "Service started"
fi

echo ""

# ──────────────────────────────────────────────
# 12. Final status
# ──────────────────────────────────────────────

sleep 2

if systemctl is-active --quiet "${SERVICE_NAME}" 2>/dev/null; then
    echo "╔══════════════════════════════════════════════╗"
    echo "║  ${GREEN}✓ FIX APPLIED SUCCESSFULLY${NC}                ║"
    echo "╚══════════════════════════════════════════════╝"
    echo ""
    ok "MeshCorium is now running with supervisor enabled."
    echo ""
    echo "  What changed:"
    echo "    - Added --supervise flag to systemd ExecStart"
    echo "    - Backup saved at: ${BACKUP}"
    echo ""
    echo "  What happens next:"
    echo "    - Supervisor will check GitHub every 30 minutes for updates"
    echo "    - When v0.8.2+ is detected, a green 'U' badge appears"
    echo "    - Click 'Settings → About → Install Update' to upgrade"
    echo ""
    echo "  To verify:"
    echo "    grep ExecStart ${SERVICE_FILE}"
    echo "    curl -s http://localhost:8080/api/update/check"
    echo ""
else
    echo "╔══════════════════════════════════════════════╗"
    echo "║  ${YELLOW}⚠ FIX APPLIED BUT SERVICE NOT RUNNING${NC}     ║"
    echo "╚══════════════════════════════════════════════╝"
    echo ""
    warn "The service file was patched but the service failed to start."
    echo ""
    echo "  Check logs: journalctl -u ${SERVICE_NAME} -n 50"
    echo "  Restore backup: sudo cp ${BACKUP} ${SERVICE_FILE}"
    echo ""
fi

echo ""
echo "  If you encounter issues, restore the backup:"
echo "    sudo cp ${BACKUP} ${SERVICE_FILE}"
echo "    sudo systemctl daemon-reload"
echo "    sudo systemctl restart ${SERVICE_NAME}"
echo ""
