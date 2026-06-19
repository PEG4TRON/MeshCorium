#!/usr/bin/env bash
set -euo pipefail

# updater.sh — standalone script that downloads and installs a specific Meshcorium release.
# Does NOT manage service lifecycle. Caller is responsible for stop/start.
#
# Usage: bash updater.sh <version_tag>
#   e.g. bash updater.sh v0.7.2
#
# Exit codes: 0 = success, 1 = failure

TARGET_TAG="${1:-}"
if [[ -z "${TARGET_TAG}" ]]; then
    echo "error: version tag required" >&2
    echo "usage: bash updater.sh <version>" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

GITHUB_REPO="PEG4TRON/MeshCorium"
GITHUB_API="${MESHCORIUM_GITHUB_API:-https://api.github.com}"
DATA_DIR="${SCRIPT_DIR}/data"
LOGS_DIR="${SCRIPT_DIR}/logs"
BACKUP_DIR="${SCRIPT_DIR}/.update-backup"
KEEP_PATHS=("data" "logs" "other")

echo "Meshcorium updater starting for ${TARGET_TAG}..."
echo ""

# 1. Get tarball URL for the specific release
echo "fetching release info for ${TARGET_TAG}..."
release_json="$(curl -sf "${GITHUB_API}/repos/${GITHUB_REPO}/releases/tags/${TARGET_TAG}" 2>/dev/null || true)"
if [[ -z "${release_json}" ]]; then
    echo "error: could not fetch release ${TARGET_TAG} from GitHub" >&2
    exit 1
fi

tarball_url="$(echo "${release_json}" | grep -m1 '"tarball_url"' | sed 's/.*"tarball_url"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/')"
if [[ -z "${tarball_url}" ]]; then
    echo "error: could not find tarball URL for ${TARGET_TAG}" >&2
    exit 1
fi

# 2. Download
temp_dir="$(mktemp -d)"
tarball_path="${temp_dir}/meshcorium.tar.gz"
echo "downloading ${TARGET_TAG}..."
if ! curl -fSL --progress-bar -o "${tarball_path}" "${tarball_url}"; then
    echo "error: download failed" >&2
    rm -rf "${temp_dir}"
    exit 1
fi

# 3. Backup data
echo "backing up data..."
rm -rf "${BACKUP_DIR}"
mkdir -p "${BACKUP_DIR}"
for path in "${KEEP_PATHS[@]}"; do
    if [[ -e "${SCRIPT_DIR}/${path}" ]]; then
        mkdir -p "$(dirname "${BACKUP_DIR}/${path}")"
        cp -a "${SCRIPT_DIR}/${path}" "${BACKUP_DIR}/${path}"
    fi
done

# 4. Extract
echo "extracting ${TARGET_TAG}..."
extract_dir="${temp_dir}/extract"
mkdir -p "${extract_dir}"
if ! tar -xzf "${tarball_path}" -C "${extract_dir}" --strip-components=1; then
    echo "error: extraction failed" >&2
    rm -rf "${temp_dir}"
    exit 1
fi

# 5. Install new files, preserving data/logs/other + patched files
echo "installing updated files..."
for item in "${extract_dir}"/*; do
    name="$(basename "${item}")"
    # skip data/logs/other — restored from backup below
    if [[ "${name}" == "data" ]] || [[ "${name}" == "logs" ]] || [[ "${name}" == "other" ]]; then
        continue
    fi
    rm -rf "${SCRIPT_DIR:?}/${name}"
    cp -a "${item}" "${SCRIPT_DIR}/${name}"
done

# 5b. Cleanup orphaned flat .py files from pre-package versions (≤0.8.2 → 0.9+)
echo "removing legacy flat .py files if present..."
for old_py in meshcorium_web.py meshcorium_client.py meshcorium_transport.py \
    meshcorium_ble_transport.py meshcorium_wifi_transport.py \
    meshcorium_serial_transport.py meshcorium_serial_legacy.py \
    meshcorium_data_transfer.py mobile_push.py \
    contact_backend.py contact_service.py contact_admin.py \
    contact_groups.py contact_store.py \
    known_nodes.py download_meshcore_node_svgs.py; do
    rm -f "${SCRIPT_DIR:?}/${old_py}"
done

# 6. Restore data/logs/other backup
echo "restoring data..."
if [[ -d "${BACKUP_DIR}/data" ]]; then
    mkdir -p "${DATA_DIR}"
    cp -a "${BACKUP_DIR}/data"/* "${DATA_DIR}/" 2>/dev/null || true
fi
if [[ -d "${BACKUP_DIR}/logs" ]]; then
    mkdir -p "${LOGS_DIR}"
    cp -a "${BACKUP_DIR}/logs"/* "${LOGS_DIR}/" 2>/dev/null || true
fi
if [[ -d "${BACKUP_DIR}/other" ]]; then
    mkdir -p "${SCRIPT_DIR}/other"
    cp -a "${BACKUP_DIR}/other"/* "${SCRIPT_DIR}/other/" 2>/dev/null || true
fi

# 6b. Merge client_settings.json — preserve user values, add missing keys from new release.
# Best-effort: if the new meshcorium_web.py is importable (venv exists), use its
# _default_client_settings() to fill in any keys missing from the user's config.
# Otherwise, runtime normalization (_normalize_client_settings) will add missing
# keys on the next settings save through the web UI.
_merge_client_settings() {
    local old_json="${DATA_DIR}/client_settings.json"
    local web_py="${SCRIPT_DIR}/meshcorium/meshcorium_web.py"
    if [[ ! -f "${old_json}" ]] || [[ ! -f "${web_py}" ]]; then
        return 0
    fi
    python3 -c "
import json, sys
sys.path.insert(0, '${SCRIPT_DIR}/meshcorium')
old = {}
with open('${old_json}') as f: old = json.load(f)
try:
    from meshcorium_web import _default_client_settings
    defaults = _default_client_settings()
    added = 0
    for k, v in defaults.items():
        if k not in old:
            old[k] = v
            added += 1
    if added:
        with open('${old_json}', 'w') as f:
            json.dump(old, f, ensure_ascii=False, indent=2, sort_keys=True)
        print(f'client_settings.json: {len(old)} keys (added {added})')
except Exception:
    # venv not available — runtime normalization will handle on next save
    pass
" 2>/dev/null || true
}
_merge_client_settings

# 7. Fix permissions
if [[ -n "${SUDO_USER:-}" ]]; then
    chown -R "${SUDO_USER}:$(id -gn "${SUDO_USER}")" "${SCRIPT_DIR}" 2>/dev/null || true
fi
chmod -R a+rX "${SCRIPT_DIR}" 2>/dev/null || true

# 8. Cleanup
rm -rf "${temp_dir}" "${BACKUP_DIR}"

echo "updater.sh: ${TARGET_TAG} installed successfully"
exit 0
