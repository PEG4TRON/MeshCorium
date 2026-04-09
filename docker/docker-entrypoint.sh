#!/bin/sh
set -eu

APP_ROOT="/opt/meshcorium"
CONFIG_DIR="${MESHCORIUM_CONFIG_DIR:-/etc/meshcorium}"
DATA_DIR="${MESHCORIUM_DATA_DIR:-/var/lib/meshcorium}"
LOG_DIR="${MESHCORIUM_LOG_DIR:-/var/log/meshcorium}"
DEFAULT_CONFIG="${APP_ROOT}/defaults/client_settings.json"
CONFIG_PATH="${MESHCORIUM_CLIENT_SETTINGS_PATH:-${CONFIG_DIR}/client_settings.json}"
LEGACY_DATA_CONFIG="${DATA_DIR}/client_settings.json"

mkdir -p "${CONFIG_DIR}" "${DATA_DIR}" "${LOG_DIR}"

if [ ! -f "${CONFIG_PATH}" ]; then
    if [ -f "${LEGACY_DATA_CONFIG}" ]; then
        cp "${LEGACY_DATA_CONFIG}" "${CONFIG_PATH}"
    else
        cp "${DEFAULT_CONFIG}" "${CONFIG_PATH}"
    fi
fi

exec "${APP_ROOT}/.venv/bin/python3" "${APP_ROOT}/meshcorium_web.py" \
    --host "${MESHCORIUM_HOST:-0.0.0.0}" \
    --port "${MESHCORIUM_PORT:-8080}" \
    "$@"

