#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_PYTHON="${VENV_DIR}/bin/python3"
WEB_HOST="${MESHCORIUM_HOST:-0.0.0.0}"
WEB_PORT="${MESHCORIUM_PORT:-8080}"
SERVICE_FILE_NAME="meshcorium.service"
SYSTEMD_UNIT_DIR="/etc/systemd/system"
SERVICE_FILE_PATH="${SYSTEMD_UNIT_DIR}/${SERVICE_FILE_NAME}"
REQ_HASH_FILE="${VENV_DIR}/.meshcorium_requirements_hash"
WEB_DIR="${SCRIPT_DIR}/web"
WEB_DEPS_HASH_FILE="${VENV_DIR}/.meshcorium_web_deps_hash"
WEB_BUILD_HASH_FILE="${VENV_DIR}/.meshcorium_web_build_hash"
WEB_DIST_INDEX="${WEB_DIR}/dist/index.html"
WEB_DIST_DIR="${WEB_DIR}/dist"
NPM_INSTALL_TIMEOUT_SECONDS="${MESHCORIUM_NPM_INSTALL_TIMEOUT_SECONDS:-30}"
NPM_BUILD_TIMEOUT_SECONDS="${MESHCORIUM_NPM_BUILD_TIMEOUT_SECONDS:-30}"
FRONTEND_NODE_MAX_OLD_SPACE_MB="${MESHCORIUM_FRONTEND_NODE_MAX_OLD_SPACE_MB:-1024}"

cd "${SCRIPT_DIR}"

SYSTEMD_INSTALL_USER="${SUDO_USER:-$(id -un)}"
SYSTEMD_INSTALL_GROUP="$(id -gn "${SYSTEMD_INSTALL_USER}")"
SYSTEM_PACKAGE_MANAGER=""
SYSTEM_PACKAGE_FAMILY=""
SYSTEM_INSTALL_APPROVAL_ENV="${MESHCORIUM_AUTO_APPROVE_SYSTEM_DEPS:-${MESHCORIUM_AUTO_APPROVE_DEPS:-0}}"
LAUNCH_MODE="run"
PASSTHROUGH_ARGS=()

resolve_release_label() {
    if [[ -n "${MESHCORIUM_RELEASE_VERSION:-}" ]]; then
        printf '%s\n' "${MESHCORIUM_RELEASE_VERSION}"
        return
    fi
    case "${SCRIPT_DIR}" in
        */.release/*)
            basename "${SCRIPT_DIR}"
            ;;
        *)
            printf 'dev-worktree\n'
            ;;
    esac
}

print_launcher_banner() {
    local release_label
    release_label="$(resolve_release_label)"
    printf '\n\n\n\n\n'
    cat <<'EOF'
    __  ______________ __  ____________  ____  ______  ____  ___
   /  |/  / ____/ ___// / / / ____/ __ \/ __ \/  _/ / / /  |/  /
  / /|_/ / __/  \__ \/ /_/ / /   / / / / /_/ // // / / / /|_/ /
 / /  / / /___ ___/ / __  / /___/ /_/ / _, _// // /_/ / /  / /
/_/  /_/_____//____/_/ /_/\____/\____/_/ |_/___/\____/_/  /_/
EOF
    printf '\nRelease: %s\n\n\n' "${release_label}"
}

supports_systemd() {
    command -v systemctl >/dev/null 2>&1 || return 1
    [[ -d /run/systemd/system ]] || [[ "$(ps -p 1 -o comm= 2>/dev/null || true)" == "systemd" ]]
}

run_privileged() {
    if [[ "${EUID}" -eq 0 ]]; then
        "$@"
        return
    fi
    if ! command -v sudo >/dev/null 2>&1; then
        echo "error: sudo is required for this operation" >&2
        exit 1
    fi
    sudo "$@"
}

add_unique_value() {
    local value="$1"
    local existing
    for existing in "${@:2}"; do
        if [[ "${existing}" == "${value}" ]]; then
            return 0
        fi
    done
    return 1
}

detect_serial_access_groups() {
    local discovered=()
    local device_path=""
    local device_group=""
    local fallback_group=""

    while IFS= read -r device_path; do
        [[ -n "${device_path}" ]] || continue
        device_group="$(stat -c '%G' "${device_path}" 2>/dev/null || true)"
        [[ -n "${device_group}" && "${device_group}" != "UNKNOWN" ]] || continue
        if getent group "${device_group}" >/dev/null 2>&1; then
            if ! add_unique_value "${device_group}" "${discovered[@]}"; then
                discovered+=("${device_group}")
            fi
        fi
    done < <(
        find /dev -maxdepth 1 -type c \
            \( -name 'ttyUSB*' -o -name 'ttyACM*' -o -name 'ttyAMA*' -o -name 'ttyS*' \) \
            2>/dev/null \
            | sort
    )

    for fallback_group in dialout uucp; do
        if getent group "${fallback_group}" >/dev/null 2>&1; then
            if ! add_unique_value "${fallback_group}" "${discovered[@]}"; then
                discovered+=("${fallback_group}")
            fi
        fi
    done

    printf '%s\n' "${discovered[@]}"
}

ensure_serial_access_groups() {
    local target_user="${SUDO_USER:-$(id -un)}"
    local target_user_groups=""
    local missing_groups=()
    local group_name=""

    if [[ "${target_user}" == "root" ]]; then
        return 0
    fi
    if ! id "${target_user}" >/dev/null 2>&1; then
        return 0
    fi

    target_user_groups=" $(id -nG "${target_user}" 2>/dev/null || true) "
    while IFS= read -r group_name; do
        [[ -n "${group_name}" ]] || continue
        if [[ "${target_user_groups}" != *" ${group_name} "* ]]; then
            missing_groups+=("${group_name}")
        fi
    done < <(detect_serial_access_groups)

    if [[ "${#missing_groups[@]}" -eq 0 ]]; then
        return 0
    fi

    echo "adding ${target_user} to serial access groups:"
    printf '  - %s\n' "${missing_groups[@]}"
    run_privileged usermod -aG "$(IFS=,; echo "${missing_groups[*]}")" "${target_user}"
    echo "serial group membership updated for ${target_user}"
    echo "note: log out and back in for the new groups to apply to existing shells"
}

write_systemd_service_unit() {
    cat > "${1}" <<EOF
[Unit]
Description=Meshcorium launcher
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=${SYSTEMD_INSTALL_USER}
Group=${SYSTEMD_INSTALL_GROUP}
WorkingDirectory=${SCRIPT_DIR}
ExecStart=${SCRIPT_DIR}/meshcorium-launcher.sh
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
}

install_systemd_service_unit() {
    if ! supports_systemd; then
        echo "error: --service requires a systemd-based system with systemctl available" >&2
        exit 1
    fi
    local temp_service_file
    temp_service_file="$(mktemp)"

    write_systemd_service_unit "${temp_service_file}"
    run_privileged install -D -m 0644 "${temp_service_file}" "${SERVICE_FILE_PATH}"
    rm -f "${temp_service_file}"
    run_privileged systemctl daemon-reload
    run_privileged systemctl enable --now "${SERVICE_FILE_NAME}"

    echo "installed ${SERVICE_FILE_NAME} into ${SYSTEMD_UNIT_DIR}"
    echo "service user: ${SYSTEMD_INSTALL_USER}:${SYSTEMD_INSTALL_GROUP}"
}

remove_systemd_service_unit() {
    if supports_systemd; then
        run_privileged systemctl disable --now "${SERVICE_FILE_NAME}" >/dev/null 2>&1 || true
        run_privileged systemctl reset-failed "${SERVICE_FILE_NAME}" >/dev/null 2>&1 || true
    fi
    run_privileged rm -f "${SERVICE_FILE_PATH}"
    if supports_systemd; then
        run_privileged systemctl daemon-reload
    fi
    echo "removed ${SERVICE_FILE_PATH}"
}

GITHUB_REPO="PEG4TRON/MeshCorium"
GITHUB_API="${MESHCORIUM_GITHUB_API:-https://api.github.com}"
UPDATE_BACKUP_DIR="${SCRIPT_DIR}/.update-backup"
CURRENT_VERSION_FILE="${SCRIPT_DIR}/.meshcorium_version"

MESHCORIUM_UPDATE_PRESERVE_PATHS=(
    "data"
    "logs"
    ".venv/.meshcorium_requirements_hash"
)

read_current_version() {
    if [[ -f "${CURRENT_VERSION_FILE}" ]]; then
        cat "${CURRENT_VERSION_FILE}"
    else
        echo "unknown"
    fi
}

write_current_version() {
    local version="$1"
    printf '%s\n' "${version}" > "${CURRENT_VERSION_FILE}"
}

stop_meshcorium_service() {
    if [[ -f "${SERVICE_FILE_PATH}" ]]; then
        echo "stopping meshcorium service..."
        run_privileged systemctl stop "${SERVICE_FILE_NAME}" 2>/dev/null || true
        sleep 2
    fi
    # fallback: kill any running meshcorium on our port
    local running_pid
    running_pid="$(ss -tlnp 2>/dev/null | grep \":${WEB_PORT}\" | grep -oP 'pid=\K[0-9]+' | head -1 || true)"
    if [[ -n "${running_pid}" ]]; then
        echo "stopping direct meshcorium process pid=${running_pid}..."
        kill "${running_pid}" 2>/dev/null || true
        sleep 1
    fi
}

start_meshcorium_service() {
    if [[ -f "${SERVICE_FILE_PATH}" ]]; then
        echo "starting meshcorium service..."
        run_privileged systemctl start "${SERVICE_FILE_NAME}" 2>/dev/null || true
    fi
}

UPDATE_TO_VERSION=""

fetch_all_releases() {
    # returns newline-separated sorted tags, newest first
    local page=1
    local all_tags=()
    local page_json
    local page_tags
    while true; do
        page_json="$(curl -sf "${GITHUB_API}/repos/${GITHUB_REPO}/releases?per_page=30&page=${page}" 2>/dev/null || true)"
        if [[ -z "${page_json}" ]] || [[ "${page_json}" == "[]" ]]; then
            break
        fi
        page_tags="$(echo "${page_json}" | grep -oP '"tag_name"\s*:\s*"\K[^"]+' || true)"
        if [[ -z "${page_tags}" ]]; then
            break
        fi
        while IFS= read -r tag; do
            [[ -n "${tag}" ]] && all_tags+=("${tag}")
        done <<< "${page_tags}"
        ((page++))
        [[ ${page} -gt 5 ]] && break
    done
    # sort by version, newest first (alphabetical sort -r works for vX.Y.Z format)
    printf '%s\n' "${all_tags[@]}" | sort -r
}

find_next_release() {
    local current="$1"
    local target="${UPDATE_TO_VERSION:-}"
    local all_tags
    all_tags="$(fetch_all_releases)"
    if [[ -z "${all_tags}" ]]; then
        return 1
    fi
    # if explicit target given, validate it
    if [[ -n "${target}" ]]; then
        if ! echo "${all_tags}" | grep -qxF "${target}"; then
            echo "error: version ${target} not found in releases" >&2
            return 1
        fi
        echo "${target}"
        return 0
    fi
    # find next (newer) release — list is newest-first, so newer release comes before current
    local prev=""
    local tag
    while IFS= read -r tag; do
        if [[ "${tag}" == "${current}" ]]; then
            if [[ -n "${prev}" ]]; then
                echo "${prev}"
                return 0
            fi
            break
        fi
        prev="${tag}"
    done <<< "${all_tags}"
    return 1
}

get_release_tarball_url() {
    local tag="$1"
    curl -sf "${GITHUB_API}/repos/${GITHUB_REPO}/releases/tags/${tag}" 2>/dev/null \
        | grep -m1 '"tarball_url"' \
        | sed 's/.*"tarball_url"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/'
}

fetch_release_info() {
    # returns JSON with latest, all_tags, next for API consumption
    local current
    current="$(read_current_version)"
    local all_tags
    all_tags="$(fetch_all_releases)"
    local latest_tag
    latest_tag="$(echo "${all_tags}" | head -1)"
    local next_tag=""
    local found=0
    local prev=""
    local tag
    while IFS= read -r tag; do
        if [[ "${found}" -eq 1 ]]; then
            next_tag="${prev}"
            break
        fi
        [[ "${tag}" == "${current}" ]] && found=1
        prev="${tag}"
    done <<< "${all_tags}"
    # output JSON
    printf '{"current_version":"%s","latest_version":"%s","next_version":"%s","update_available":%s}\n' \
        "${current}" \
        "${latest_tag}" \
        "${next_tag}" \
        "$([[ -n "${next_tag}" ]] && echo "true" || echo "false")"
}

PENDING_UPDATE_FILE="${SCRIPT_DIR}/.meshcorium_pending_update"
UPDATE_STATE_FILE="${SCRIPT_DIR}/.meshcorium_update_state"
UPDATE_ERROR_FILE="${SCRIPT_DIR}/.meshcorium_update_error"
UPDATE_AVAILABLE_FILE="${SCRIPT_DIR}/.meshcorium_update_available"
OLD_RELEASES_DIR="${SCRIPT_DIR}/old-releases"
MAX_OLD_RELEASES=3
READINESS_TIMEOUT=120
UPDATE_CHECK_INTERVAL=1800

supervise_loop() {
    echo "Meshcorium supervisor starting..."
    echo ""

    local last_check=0
    local child_pid=0

    cleanup_child() {
        [[ "${child_pid}" -gt 0 ]] && kill "${child_pid}" 2>/dev/null || true
        wait "${child_pid}" 2>/dev/null || true
        child_pid=0
    }

    trap 'cleanup_child; exit 0' SIGTERM SIGINT

    while true; do
        # Auto-check for updates every UPDATE_CHECK_INTERVAL seconds
        local now
        now="$(date +%s)"
        if [[ $((now - last_check)) -ge ${UPDATE_CHECK_INTERVAL} ]]; then
            last_check="${now}"
            auto_check_updates
        fi

        # Start child if not running
        if [[ "${child_pid}" -le 0 ]] || ! kill -0 "${child_pid}" 2>/dev/null; then
            echo "supervisor: starting meshcorium_web.py..."
            "${VENV_PYTHON}" "${SCRIPT_DIR}/meshcorium_web.py" --host "${WEB_HOST}" --port "${WEB_PORT}" &
            child_pid=$!
            echo "supervisor: child pid=${child_pid}"
        fi

        # Check for pending update
        if [[ -f "${PENDING_UPDATE_FILE}" ]]; then
            local update_version
            update_version="$(cat "${PENDING_UPDATE_FILE}" | head -1)"
            rm -f "${PENDING_UPDATE_FILE}"
            if [[ -n "${update_version}" ]]; then
                perform_supervised_update "${update_version}"
            fi
        fi

        sleep 2
    done
}

auto_check_updates() {
    local current
    current="$(read_current_version)"
    local all_tags
    all_tags="$(fetch_all_releases 2>/dev/null || true)"
    if [[ -z "${all_tags}" ]]; then
        return 0
    fi
    local latest_tag
    latest_tag="$(echo "${all_tags}" | head -1)"
    local next_tag=""
    local prev=""
    local tag
    while IFS= read -r tag; do
        if [[ "${tag}" == "${current}" ]]; then
            next_tag="${prev}"
            break
        fi
        prev="${tag}"
    done <<< "${all_tags}"

    if [[ -n "${next_tag}" ]]; then
        printf '{"current":"%s","next":"%s","latest":"%s","release_url":"https://github.com/%s/releases/tag/%s","checked_at":%s}\n' \
            "${current}" "${next_tag}" "${latest_tag}" "${GITHUB_REPO}" "${next_tag}" "$(date +%s)" \
            > "${UPDATE_AVAILABLE_FILE}"
    else
        rm -f "${UPDATE_AVAILABLE_FILE}"
    fi
}

perform_supervised_update() {
    local target_version="$1"
    local old_version
    old_version="$(read_current_version)"

    echo "supervisor: update requested ${old_version} -> ${target_version}"
    echo "updating" > "${UPDATE_STATE_FILE}"
    rm -f "${UPDATE_ERROR_FILE}"

    # 1. Stop child
    echo "supervisor: stopping child..."
    cleanup_child

    # 2. Backup current version (copy contents, excluding heavy/recursive dirs)
    local backup_path="${OLD_RELEASES_DIR}/${old_version}"
    echo "supervisor: backing up to ${backup_path}..."
    rm -rf "${backup_path}"
    mkdir -p "${backup_path}"
    local item name
    for item in "${SCRIPT_DIR}"/*; do
        name="$(basename "${item}")"
        [[ "${name}" == ".venv" || "${name}" == "node_modules" || "${name}" == "logs" || "${name}" == "old-releases" || "${name}" == ".update-backup" ]] && continue
        cp -a "${item}" "${backup_path}/"
    done

    # 3. Run updater
    echo "supervisor: running updater.sh ${target_version}..."
    if bash "${SCRIPT_DIR}/updater.sh" "${target_version}"; then
        # 4. Write new version, clear flags BEFORE starting new process
        write_current_version "${target_version}"
        printf '{"current":"%s","next":"","latest":"%s","release_url":"","checked_at":%s}\n' \
            "${target_version}" "${target_version}" "$(date +%s)" \
            > "${UPDATE_AVAILABLE_FILE}"
        echo "idle" > "${UPDATE_STATE_FILE}"
        echo "supervisor: starting new version..."
        "${VENV_PYTHON}" "${SCRIPT_DIR}/meshcorium_web.py" --host "${WEB_HOST}" --port "${WEB_PORT}" &
        child_pid=$!

        # 5. Wait for readiness
        echo "supervisor: waiting for readiness on port ${WEB_PORT}..."
        local waited=0
        while [[ ${waited} -lt ${READINESS_TIMEOUT} ]]; do
            if kill -0 "${child_pid}" 2>/dev/null; then
                if curl -sf "http://127.0.0.1:${WEB_PORT}/api/ports" >/dev/null 2>&1; then
                    echo "supervisor: new version ready"
                    echo "idle" > "${UPDATE_STATE_FILE}"
                    prune_old_releases
                    return 0
                fi
            else
                echo "supervisor: child died during readiness wait"
                break
            fi
            sleep 2
            waited=$((waited + 2))
        done
    fi

    # 6. Rollback
    echo "supervisor: update failed, rolling back to ${old_version}..."
    if [[ -d "${backup_path}" ]]; then
        for item in "${backup_path}"/*; do
            name="$(basename "${item}")"
            [[ "${name}" == "old-releases" ]] && continue
            rm -rf "${SCRIPT_DIR:?}/${name}"
            cp -a "${item}" "${SCRIPT_DIR}/${name}"
        done
    fi
    write_current_version "${old_version}"
    printf '{"from":"%s","to":"%s","error":"update failed, restored %s","ts":%s}\n' \
        "${old_version}" "${target_version}" "${old_version}" "$(date +%s)" \
        > "${UPDATE_ERROR_FILE}"
    echo "idle" > "${UPDATE_STATE_FILE}"
    cleanup_child
    prune_old_releases
}

prune_old_releases() {
    local count=0
    if [[ ! -d "${OLD_RELEASES_DIR}" ]]; then
        return 0
    fi
    local dirs
    dirs="$(find "${OLD_RELEASES_DIR}" -maxdepth 1 -mindepth 1 -type d | sort -r)"
    while IFS= read -r d; do
        count=$((count + 1))
        if [[ ${count} -gt ${MAX_OLD_RELEASES} ]]; then
            echo "supervisor: pruning old release ${d}"
            rm -rf "${d}"
        fi
    done <<< "${dirs}"
}

print_launcher_help() {
    echo "launcher options:"
    echo "  --install"
    echo "      install missing system/runtime dependencies,"
    echo "      install ${SERVICE_FILE_NAME}, enable it,"
    echo "      and start it"
    echo "  --run"
    echo "      install missing system/runtime dependencies"
    echo "      and run Meshcorium directly"
    echo "      without installing a service"
    echo "  --service-remove"
    echo "      disable/remove ${SERVICE_FILE_NAME}"
    echo "      from ${SYSTEMD_UNIT_DIR} with sudo"
    echo "  --update-meshcorium"
    echo "      download and install the latest release"
    echo "      from GitHub ${GITHUB_REPO}"
    echo "      preserves local data, logs, and settings"
    echo "      stops the running instance, updates,"
    echo "      rebuilds frontend, and restarts"
    echo
    echo "default mode is equivalent to --run"
    echo "all other arguments are passed through to meshcorium_web.py"
}

detect_system_package_manager() {
    if [[ -n "${SYSTEM_PACKAGE_MANAGER}" ]]; then
        return 0
    fi
    if command -v apt-get >/dev/null 2>&1; then
        SYSTEM_PACKAGE_MANAGER="apt-get"
        SYSTEM_PACKAGE_FAMILY="apt"
        return 0
    fi
    if command -v dnf >/dev/null 2>&1; then
        SYSTEM_PACKAGE_MANAGER="dnf"
        SYSTEM_PACKAGE_FAMILY="dnf"
        return 0
    fi
    if command -v yum >/dev/null 2>&1; then
        SYSTEM_PACKAGE_MANAGER="yum"
        SYSTEM_PACKAGE_FAMILY="yum"
        return 0
    fi
    return 1
}

add_unique_package() {
    local pkg="$1"
    local existing
    for existing in "${SYSTEM_PACKAGES[@]:-}"; do
        if [[ "${existing}" == "${pkg}" ]]; then
            return 0
        fi
    done
    SYSTEM_PACKAGES+=("${pkg}")
}

python_supports_builtin_venv() {
    if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
        return 1
    fi
    local probe_dir
    probe_dir="$(mktemp -d "${TMPDIR:-/tmp}/meshcorium-venv-probe.XXXXXX")"
    if "${PYTHON_BIN}" -m venv "${probe_dir}" >/dev/null 2>&1; then
        rm -rf "${probe_dir}"
        return 0
    fi
    rm -rf "${probe_dir}"
    return 1
}

python_supports_virtualenv_module() {
    if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
        return 1
    fi
    "${PYTHON_BIN}" -m virtualenv --help >/dev/null 2>&1
}

resolve_venv_creation_mode() {
    if python_supports_builtin_venv; then
        printf 'venv\n'
        return 0
    fi
    if python_supports_virtualenv_module; then
        printf 'virtualenv\n'
        return 0
    fi
    printf 'missing\n'
    return 1
}

collect_missing_system_packages() {
    SYSTEM_PACKAGES=()
    SYSTEM_REQUIREMENTS=()

    local needs_python=0
    local needs_python_pip=0
    local needs_venv_support=0
    local needs_node=0
    local needs_npm=0
    local needs_bluez=0

    if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
        needs_python=1
        needs_python_pip=1
        needs_venv_support=1
        SYSTEM_REQUIREMENTS+=("${PYTHON_BIN}")
    else
        if ! python_supports_builtin_venv && ! python_supports_virtualenv_module; then
            needs_venv_support=1
            SYSTEM_REQUIREMENTS+=("python venv support")
        fi
        if [[ -x "${VENV_DIR}/bin/python" ]] && "${VENV_DIR}/bin/python" -m pip --version >/dev/null 2>&1; then
            needs_python_pip=0
        elif [[ -x "${VENV_DIR}/bin/python3" ]] && "${VENV_DIR}/bin/python3" -m pip --version >/dev/null 2>&1; then
            needs_python_pip=0
        elif ! "${PYTHON_BIN}" -m pip --version >/dev/null 2>&1; then
            needs_python_pip=1
            SYSTEM_REQUIREMENTS+=("python pip")
        fi
    fi

    if [[ -f "${WEB_DIR}/package.json" ]]; then
        if ! command -v node >/dev/null 2>&1; then
            needs_node=1
            SYSTEM_REQUIREMENTS+=("node")
        fi
        if ! command -v npm >/dev/null 2>&1; then
            needs_npm=1
            SYSTEM_REQUIREMENTS+=("npm")
        fi
    fi

    if [[ -f "${SCRIPT_DIR}/requirements.txt" ]] && grep -Eq '^[[:space:]]*bleak([<>=[:space:]]|$)' "${SCRIPT_DIR}/requirements.txt"; then
        if ! command -v bluetoothctl >/dev/null 2>&1; then
            needs_bluez=1
            SYSTEM_REQUIREMENTS+=("bluez/bluetoothctl")
        fi
    fi

    if [[ "${#SYSTEM_REQUIREMENTS[@]}" -eq 0 ]]; then
        return 0
    fi

    if ! detect_system_package_manager; then
        return 1
    fi

    case "${SYSTEM_PACKAGE_FAMILY}" in
        apt)
            if [[ "${needs_python}" -eq 1 ]]; then
                add_unique_package python3
            fi
            if [[ "${needs_python_pip}" -eq 1 ]]; then
                add_unique_package python3-pip
            fi
            if [[ "${needs_venv_support}" -eq 1 ]]; then
                add_unique_package python3-venv
            fi
            if [[ "${needs_node}" -eq 1 ]]; then
                add_unique_package nodejs
            fi
            if [[ "${needs_npm}" -eq 1 ]]; then
                add_unique_package npm
            fi
            if [[ "${needs_bluez}" -eq 1 ]]; then
                add_unique_package bluez
            fi
            ;;
        dnf|yum)
            if [[ "${needs_python}" -eq 1 ]]; then
                add_unique_package python3
            fi
            if [[ "${needs_python_pip}" -eq 1 ]]; then
                add_unique_package python3-pip
            fi
            if [[ "${needs_venv_support}" -eq 1 ]]; then
                add_unique_package python3-virtualenv
            fi
            if [[ "${needs_node}" -eq 1 ]]; then
                add_unique_package nodejs
            fi
            if [[ "${needs_npm}" -eq 1 ]]; then
                add_unique_package npm
            fi
            if [[ "${needs_bluez}" -eq 1 ]]; then
                add_unique_package bluez
            fi
            ;;
    esac

    return 0
}

confirm_system_package_install() {
    if [[ "${#SYSTEM_PACKAGES[@]}" -eq 0 ]]; then
        return 0
    fi
    if [[ "${SYSTEM_INSTALL_APPROVAL_ENV}" == "1" || "${SYSTEM_INSTALL_APPROVAL_ENV}" == "true" || "${SYSTEM_INSTALL_APPROVAL_ENV}" == "yes" ]]; then
        return 0
    fi
    if [[ ! -t 0 ]]; then
        echo "error: missing required system packages:" >&2
        printf '  - %s\n' "${SYSTEM_REQUIREMENTS[@]}" >&2
        echo "error: rerun interactively and approve installation," >&2
        echo "error: or set MESHCORIUM_AUTO_APPROVE_SYSTEM_DEPS=1" >&2
        return 1
    fi
    echo "Meshcorium is missing required system packages:"
    printf '  - %s\n' "${SYSTEM_REQUIREMENTS[@]}"
    echo "Package manager: ${SYSTEM_PACKAGE_MANAGER}"
    echo "Packages to install:"
    printf '  - %s\n' "${SYSTEM_PACKAGES[@]}"
    printf 'Install them now? [y/N]: '
    local reply=""
    IFS= read -r reply || true
    case "${reply}" in
        y|Y|yes|YES)
            return 0
            ;;
        *)
            echo "error: system package installation was not approved" >&2
            return 1
            ;;
    esac
}

install_missing_system_packages() {
    SYSTEM_PACKAGES=()
    SYSTEM_REQUIREMENTS=()
    if ! collect_missing_system_packages; then
        echo "error: could not detect a supported package manager" >&2
        echo "error: for this system" >&2
        echo "error: install the missing runtime manually and rerun" >&2
        echo "error: expected at least: ${SYSTEM_REQUIREMENTS[*]:-${PYTHON_BIN} node npm}" >&2
        exit 1
    fi
    if [[ "${#SYSTEM_PACKAGES[@]}" -eq 0 ]]; then
        return 0
    fi
    confirm_system_package_install || exit 1
    echo "installing system packages with ${SYSTEM_PACKAGE_MANAGER}:"
    printf '  - %s\n' "${SYSTEM_PACKAGES[@]}"
    case "${SYSTEM_PACKAGE_FAMILY}" in
        apt)
            run_privileged env DEBIAN_FRONTEND=noninteractive apt-get update
            run_privileged env DEBIAN_FRONTEND=noninteractive apt-get install -y "${SYSTEM_PACKAGES[@]}"
            ;;
        dnf)
            run_privileged dnf install -y "${SYSTEM_PACKAGES[@]}"
            ;;
        yum)
            run_privileged yum install -y "${SYSTEM_PACKAGES[@]}"
            ;;
        *)
            echo "error: unsupported package manager family: ${SYSTEM_PACKAGE_FAMILY}" >&2
            exit 1
            ;;
    esac
}

create_virtual_environment() {
    local venv_mode
    venv_mode="$(resolve_venv_creation_mode)"
    echo "creating virtual environment: ${VENV_DIR}"
    case "${venv_mode}" in
        venv)
            "${PYTHON_BIN}" -m venv "${VENV_DIR}"
            ;;
        virtualenv)
            "${PYTHON_BIN}" -m virtualenv "${VENV_DIR}"
            ;;
        *)
            echo "error: python environment lacks both venv and virtualenv support" >&2
            exit 1
            ;;
    esac
}

virtual_environment_is_usable() {
    [[ -f "${VENV_DIR}/bin/activate" ]] || return 1
    [[ -x "${VENV_DIR}/bin/python3" || -x "${VENV_DIR}/bin/python" ]] || return 1
}

ensure_virtual_environment() {
    if [[ ! -d "${VENV_DIR}" ]]; then
        create_virtual_environment
        return
    fi
    if virtual_environment_is_usable; then
        return
    fi
    echo "detected incomplete virtual environment, recreating: ${VENV_DIR}"
    rm -rf "${VENV_DIR}"
    create_virtual_environment
}

print_launcher_banner

for arg in "$@"; do
    if [[ "${arg}" == "-h" || "${arg}" == "--help" ]]; then
        print_launcher_help
        exit 0
    fi
    if [[ "${arg}" == "--install" ]]; then
        LAUNCH_MODE="install"
        continue
    fi
    if [[ "${arg}" == "--run" ]]; then
        LAUNCH_MODE="run"
        continue
    fi
    if [[ "${arg}" == "--service-remove" ]]; then
        remove_systemd_service_unit
        exit 0
    fi
    if [[ "${arg}" == "--update-meshcorium" ]]; then
        bash "${SCRIPT_DIR}/updater.sh" "$(fetch_all_releases | head -1)"
        exec bash "${SCRIPT_DIR}/meshcorium-launcher.sh" --run
        exit 0
    fi
    if [[ "${arg}" == "--supervise" ]]; then
        LAUNCH_MODE="supervise"
        continue
    fi
    if [[ "${arg}" == "--service" ]]; then
        echo "error: --service was removed" >&2
        echo "error: use --install to install the systemd service" >&2
        echo "error: or use --run to launch directly" >&2
        exit 1
    fi
    PASSTHROUGH_ARGS+=("${arg}")
done

install_missing_system_packages

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
    echo "error: python interpreter not found: ${PYTHON_BIN}" >&2
    exit 1
fi

ensure_serial_access_groups

ensure_virtual_environment

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

if [[ ! -x "${VENV_PYTHON}" ]]; then
    VENV_PYTHON="${VENV_DIR}/bin/python"
fi

if [[ ! -x "${VENV_PYTHON}" ]]; then
    echo "error: no python interpreter found inside ${VENV_DIR}/bin" >&2
    exit 1
fi

requirements_hash() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "${SCRIPT_DIR}/requirements.txt" | awk '{print $1}'
        return
    fi
    if command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "${SCRIPT_DIR}/requirements.txt" | awk '{print $1}'
        return
    fi
    echo "error: neither sha256sum nor shasum is available" >&2
    exit 1
}

hash_tree() {
    local root="$1"
    shift
    if [[ ! -d "${root}" ]]; then
        printf 'missing\n'
        return
    fi
    if command -v sha256sum >/dev/null 2>&1; then
        (
            cd "${root}"
            find "$@" -type f -print0 \
                | sort -z \
                | xargs -0 sha256sum
        ) | sha256sum | awk '{print $1}'
        return
    fi
    if command -v shasum >/dev/null 2>&1; then
        (
            cd "${root}"
            find "$@" -type f -print0 \
                | sort -z \
                | xargs -0 shasum -a 256
        ) | shasum -a 256 | awk '{print $1}'
        return
    fi
    echo "error: neither sha256sum nor shasum is available" >&2
    exit 1
}

warn_using_stale_frontend_dist() {
    local reason="$1"
    if [[ -f "${WEB_DIST_INDEX}" ]]; then
        echo "warning: ${reason}" >&2
        echo "warning: using existing frontend build from ${WEB_DIST_INDEX}" >&2
        return 0
    fi
    echo "error: ${reason}" >&2
    return 1
}

run_with_optional_timeout() {
    local timeout_seconds="$1"
    shift
    if command -v timeout >/dev/null 2>&1; then
        timeout --foreground "${timeout_seconds}" "$@"
        return $?
    fi
    "$@"
}

frontend_node_options() {
    local heap_mb
    heap_mb="$(printf '%s' "${FRONTEND_NODE_MAX_OLD_SPACE_MB}" | tr -cd '0-9')"
    if [[ -z "${heap_mb}" ]]; then
        heap_mb="1024"
    fi
    printf '%s\n' "--max-old-space-size=${heap_mb}"
}

write_hash_marker() {
    local marker_path="$1"
    local marker_value="$2"
    printf '%s\n' "${marker_value}" > "${marker_path}"
}

frontend_deps_look_installed() {
    [[ -d "${WEB_DIR}/node_modules" ]] || return 1
    [[ -x "${WEB_DIR}/node_modules/.bin/vite" ]] || return 1
    return 0
}

tree_newest_mtime() {
    local root="$1"
    shift
    if [[ ! -d "${root}" ]]; then
        printf '0\n'
        return
    fi
    (
        cd "${root}"
        find "$@" -type f -printf '%T@\n' 2>/dev/null
    ) | awk '
        BEGIN { max = 0 }
        NF && ($1 + 0) > max { max = $1 + 0 }
        END { printf "%.0f\n", max }
    '
}

frontend_dist_looks_fresh() {
    [[ -f "${WEB_DIST_INDEX}" ]] || return 1
    local source_mtime
    local dist_mtime
    source_mtime="$(tree_newest_mtime "${WEB_DIR}" index.html package.json package-lock.json vite.config.js src)"
    dist_mtime="$(tree_newest_mtime "${WEB_DIST_DIR}" .)"
    [[ "${dist_mtime}" -ge "${source_mtime}" ]]
}

listener_pids_for_port() {
    local port="$1"
    if ! command -v ss >/dev/null 2>&1; then
        return
    fi
    ss -ltnp 2>/dev/null \
        | awk -v needle=":${port}" '
            index($4, needle) {
                while (match($0, /pid=[0-9]+/)) {
                    print substr($0, RSTART + 4, RLENGTH - 4)
                    $0 = substr($0, RSTART + RLENGTH)
                }
            }
        ' \
        | awk '!seen[$0]++'
}

stop_existing_meshcorium_listener() {
    local port="$1"
    local pid
    local args
    local found=0
    local wait_round
    mapfile -t listener_pids < <(listener_pids_for_port "${port}")

    if [[ "${#listener_pids[@]}" -eq 0 ]]; then
        return 0
    fi

    for pid in "${listener_pids[@]}"; do
        [[ -n "${pid}" ]] || continue
        args="$(ps -p "${pid}" -o args= 2>/dev/null || true)"
        [[ -n "${args}" ]] || continue
        if [[ "${args}" == *"${SCRIPT_DIR}/meshcorium_web.py"* ]]; then
            found=1
            echo "stopping existing Meshcorium server on port ${port} (pid ${pid})"
            kill "${pid}" 2>/dev/null || true
            for wait_round in 1 2 3 4 5 6 7 8 9 10; do
                if ! ps -p "${pid}" >/dev/null 2>&1; then
                    break
                fi
                sleep 0.3
            done
            if ps -p "${pid}" >/dev/null 2>&1; then
                echo "error: existing Meshcorium server pid ${pid}" >&2
                echo "error: did not stop cleanly" >&2
                return 1
            fi
            continue
        fi
        echo "error: port ${port} is already in use by a different process:" >&2
        echo "  pid ${pid}: ${args}" >&2
        echo "set MESHCORIUM_PORT to another port" >&2
        echo "or stop that process first" >&2
        return 1
    done

    if [[ "${found}" -eq 1 ]]; then
        sleep 0.2
    fi
    return 0
}

CURRENT_REQ_HASH="$(requirements_hash)"
INSTALLED_REQ_HASH=""
if [[ -f "${REQ_HASH_FILE}" ]]; then
    INSTALLED_REQ_HASH="$(tr -d '[:space:]' < "${REQ_HASH_FILE}")"
fi

if [[ "${CURRENT_REQ_HASH}" != "${INSTALLED_REQ_HASH}" ]]; then
    echo "installing requirements from requirements.txt"
    "${VENV_PYTHON}" -m pip install --disable-pip-version-check -r "${SCRIPT_DIR}/requirements.txt"
    printf '%s\n' "${CURRENT_REQ_HASH}" > "${REQ_HASH_FILE}"
fi

if [[ -f "${WEB_DIR}/package.json" ]]; then
        if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
        if [[ -f "${WEB_DIST_INDEX}" ]]; then
            echo "warning: node/npm not available" >&2
            echo "warning: using bundled frontend build from:" >&2
            echo "warning: ${WEB_DIST_INDEX}" >&2
        else
            echo "error: node and npm are required" >&2
            echo "error: because no prebuilt frontend dist is available" >&2
            exit 1
        fi
    else
        CURRENT_WEB_DEPS_HASH="$(hash_tree "${WEB_DIR}" package.json package-lock.json)"
        INSTALLED_WEB_DEPS_HASH=""
        if [[ -f "${WEB_DEPS_HASH_FILE}" ]]; then
            INSTALLED_WEB_DEPS_HASH="$(tr -d '[:space:]' < "${WEB_DEPS_HASH_FILE}")"
        fi

        if [[ "${CURRENT_WEB_DEPS_HASH}" != "${INSTALLED_WEB_DEPS_HASH}" ]] && frontend_deps_look_installed; then
            write_hash_marker "${WEB_DEPS_HASH_FILE}" "${CURRENT_WEB_DEPS_HASH}"
            INSTALLED_WEB_DEPS_HASH="${CURRENT_WEB_DEPS_HASH}"
        fi

        if [[ ! -d "${WEB_DIR}/node_modules" || "${CURRENT_WEB_DEPS_HASH}" != "${INSTALLED_WEB_DEPS_HASH}" ]]; then
            echo "installing frontend dependencies in ${WEB_DIR}"
            if [[ -f "${WEB_DIR}/package-lock.json" ]]; then
                if ! (cd "${WEB_DIR}" && run_with_optional_timeout "${NPM_INSTALL_TIMEOUT_SECONDS}" npm ci); then
                    warn_using_stale_frontend_dist "frontend dependency install failed (npm ci)" || exit 1
                else
                    write_hash_marker "${WEB_DEPS_HASH_FILE}" "${CURRENT_WEB_DEPS_HASH}"
                fi
            else
                if ! (cd "${WEB_DIR}" && run_with_optional_timeout "${NPM_INSTALL_TIMEOUT_SECONDS}" npm install); then
                    warn_using_stale_frontend_dist "frontend dependency install failed (npm install)" || exit 1
                else
                    write_hash_marker "${WEB_DEPS_HASH_FILE}" "${CURRENT_WEB_DEPS_HASH}"
                fi
            fi
        fi

        CURRENT_WEB_BUILD_HASH="$(hash_tree "${WEB_DIR}" index.html package.json package-lock.json vite.config.js src)"

        echo "building frontend in ${WEB_DIR}"
        # Use Vite's runner config loader here. The default bundled loader writes a
        # temporary config artifact, which has been flaky specifically under the
        # systemd launcher environment even though manual builds succeed.
        #
        # Also disable emptyOutDir for the launcher path. Under service restarts,
        # Vite's dist cleanup has intermittently failed in emptyDir/rimraf even
        # though the actual build succeeds interactively. For the startup path it is
        # safer to keep old hashed assets around than to downgrade the whole launch
        # to a stale-dist warning.
        if (cd "${WEB_DIR}" && run_with_optional_timeout "${NPM_BUILD_TIMEOUT_SECONDS}" env NODE_OPTIONS="${NODE_OPTIONS:-} $(frontend_node_options)" npm run build -- --configLoader runner --emptyOutDir false); then
            write_hash_marker "${WEB_BUILD_HASH_FILE}" "${CURRENT_WEB_BUILD_HASH}"
        else
            warn_using_stale_frontend_dist "frontend build failed (npm run build)" || exit 1
        fi
    fi
fi

if [[ "${LAUNCH_MODE}" == "install" ]]; then
    install_systemd_service_unit
    exit 0
fi

if [[ "${LAUNCH_MODE}" == "supervise" ]]; then
    supervise_loop
    exit 0
fi

stop_existing_meshcorium_listener "${WEB_PORT}"

exec "${VENV_PYTHON}" "${SCRIPT_DIR}/meshcorium_web.py" --host "${WEB_HOST}" --port "${WEB_PORT}" "${PASSTHROUGH_ARGS[@]}"
