#!/usr/bin/env bash
# Keep this bootstrap self-contained: Steam downloads this script into bash -s.
# These scripts run host tools only; keep Steam's libraries and overlay out of them.
# Use builtins before the first subprocess, including logging setup (bash -s safe).
unset LD_PRELOAD
if [[ "${STEAM_RUNTIME:-}" == /* ]]; then
    export LD_LIBRARY_PATH="${SYSTEM_LD_LIBRARY_PATH:-}"
    export PATH="${SYSTEM_PATH:-/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin}"
    unset STEAM_RUNTIME
fi
readonly RECIPE_NAME="reframework"
readonly SCRIPT_NAME="uninstall"
log_dir="${HOME}/.dlor/logs/$RECIPE_NAME/$SCRIPT_NAME"
printf -v log_timestamp '%(%Y-%m-%dT%H-%M-%S)T' -1
log_timestamp+=".${EPOCHREALTIME##*.}"
log_file="$log_dir/$log_timestamp.log"
if mkdir -p -- "$log_dir" && : >> "$log_file" && command -v tee >/dev/null 2>&1; then
    # Keep draining output even if a log write or the console fails.
    exec > >(tee --output-error=warn -a -- "$log_file") 2>&1
else
    printf 'Warning: could not enable logging to %s; continuing.\n' "$log_file" >&2
fi

set -Eeuo pipefail
trap 'printf "Error: %s line %s: %s (exit %s)\n" "$RECIPE_NAME/$SCRIPT_NAME" "$LINENO" "$BASH_COMMAND" "$?" >&2' ERR

on_exit() {
    local status=$?
    # A cleanup error must not skip other cleanup or hide the original status.
    set +e
    if declare -F cleanup >/dev/null; then
        cleanup
    fi
    printf '%s finished with exit status %s.\n' "$RECIPE_NAME/$SCRIPT_NAME" "$status"
    exit "$status"
}
trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
printf 'Starting %s\n' "$RECIPE_NAME/$SCRIPT_NAME"

readonly DLL_NAME="dinput8.dll"

usage() {
    cat <<EOF
Usage:
  $(basename "$0") /path/to/Game.exe
  $(basename "$0") /path/to/game-directory

Removes ${DLL_NAME} from beside the provided executable, or directly from the
provided directory. REFramework configuration, mods, and cached downloads are
left untouched.
EOF
}

fail() {
    printf 'Error: %s\n' "$*" >&2
    exit 1
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
    exit 0
fi

if (( $# != 1 )); then
    usage >&2
    exit 2
fi

target="$1"

if [[ -d "$target" ]]; then
    target_dir="$(cd -- "$target" && pwd -P)"
elif [[ -f "$target" ]]; then
    case "$target" in
        *.[Ee][Xx][Ee])
            target_dir="$(cd -- "$(dirname -- "$target")" && pwd -P)"
            ;;
        *)
            fail "The provided file is not an .exe: $target"
            ;;
    esac
else
    fail "Target does not exist or is not a regular file/directory: $target"
fi

destination="$target_dir/$DLL_NAME"

if [[ ! -e "$destination" && ! -L "$destination" ]]; then
    printf 'REFramework is not installed: %s\n' "$destination"
    exit 0
fi

if [[ -d "$destination" && ! -L "$destination" ]]; then
    fail "Refusing to remove a directory: $destination"
fi

rm -f -- "$destination"
printf 'Uninstalled: %s\n' "$destination"
