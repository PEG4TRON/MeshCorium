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
    "${PYTHON_BIN}" -m venv --help >/dev/null 2>&1
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

if [[ ! -d "${VENV_DIR}" ]]; then
    create_virtual_environment
fi

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
        if (cd "${WEB_DIR}" && run_with_optional_timeout "${NPM_BUILD_TIMEOUT_SECONDS}" npm run build -- --configLoader runner --emptyOutDir false); then
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

stop_existing_meshcorium_listener "${WEB_PORT}"

exec "${VENV_PYTHON}" "${SCRIPT_DIR}/meshcorium_web.py" --host "${WEB_HOST}" --port "${WEB_PORT}" "${PASSTHROUGH_ARGS[@]}"
