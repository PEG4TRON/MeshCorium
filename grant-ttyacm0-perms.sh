#!/usr/bin/env bash
set -euo pipefail

DEVICE_PATH="${1:-/dev/ttyACM0}"
TARGET_USER="${SUDO_USER:-$USER}"

if [[ ! -e "$DEVICE_PATH" ]]; then
  echo "Device not found: $DEVICE_PATH" >&2
  exit 1
fi

echo "Granting rw access to $TARGET_USER for $DEVICE_PATH"
sudo setfacl -m "u:${TARGET_USER}:rw" "$DEVICE_PATH"
echo "Done."
