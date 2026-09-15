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
readonly SCRIPT_NAME="update"
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

readonly REPOSITORY="praydog/REFramework-nightly"
readonly ASSET_NAME="REFramework.zip"
readonly DLL_NAME="dinput8.dll"
readonly LATEST_RELEASE_URL="https://github.com/${REPOSITORY}/releases/latest"
readonly CACHE_ROOT="${REFRAMEWORK_CACHE_DIR:-${TMPDIR:-/tmp}/update-reframework}"

usage() {
    cat <<EOF
Usage:
  $(basename "$0") /path/to/Game.exe
  $(basename "$0") /path/to/game-directory

Downloads the latest REFramework release and copies ${DLL_NAME} next to the
provided executable, or directly into the provided directory.

Cache directory:
  ${CACHE_ROOT}

Override it with REFRAMEWORK_CACHE_DIR=/another/path.
EOF
}

fail() {
    printf 'Error: %s\n' "$*" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
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

require_command curl
require_command unzip
require_command mktemp

mkdir -p -- "$CACHE_ROOT"

printf 'Checking the latest REFramework release...\n'
release_url="$(
    curl -fsSL \
        --retry 3 \
        --retry-delay 1 \
        -o /dev/null \
        -w '%{url_effective}' \
        "$LATEST_RELEASE_URL"
)"

release_url="${release_url%/}"
version="${release_url##*/}"
version="${version%%\?*}"
version="${version%%\#*}"

if [[ -z "$version" || "$version" == "latest" ]]; then
    fail "Could not determine the latest release version from: $release_url"
fi

version_dir="$CACHE_ROOT/$version"
archive="$version_dir/$ASSET_NAME"
cached_dll="$version_dir/$DLL_NAME"
asset_url="https://github.com/${REPOSITORY}/releases/download/${version}/${ASSET_NAME}"

mkdir -p -- "$version_dir"

download_tmp=""
dll_tmp=""

cleanup() {
    if [[ -n "$download_tmp" ]]; then
        rm -f -- "$download_tmp"
    fi
    if [[ -n "$dll_tmp" ]]; then
        rm -f -- "$dll_tmp"
    fi
}

download_archive() {
    download_tmp="$(mktemp "$version_dir/.${ASSET_NAME}.XXXXXX")"

    printf 'Downloading %s...\n' "$version"
    curl -fsSL \
        --retry 3 \
        --retry-delay 1 \
        "$asset_url" \
        -o "$download_tmp"

    [[ -s "$download_tmp" ]] || fail "Downloaded archive is empty"

    mv -f -- "$download_tmp" "$archive"
    download_tmp=""
}

extract_dll() {
    dll_tmp="$(mktemp "$version_dir/.${DLL_NAME}.XXXXXX")"

    if ! unzip -p "$archive" "$DLL_NAME" > "$dll_tmp"; then
        rm -f -- "$dll_tmp"
        dll_tmp=""
        return 1
    fi

    if [[ ! -s "$dll_tmp" ]]; then
        rm -f -- "$dll_tmp"
        dll_tmp=""
        return 1
    fi

    mv -f -- "$dll_tmp" "$cached_dll"
    dll_tmp=""
}

if [[ -s "$cached_dll" ]]; then
    printf 'Using cached %s.\n' "$cached_dll"
else
    if [[ -s "$archive" ]]; then
        printf 'Using cached archive %s.\n' "$archive"
    else
        download_archive
    fi

    if ! extract_dll; then
        printf 'Cached archive is invalid; downloading it again.\n' >&2
        rm -f -- "$archive"
        download_archive
        extract_dll || fail "The downloaded archive does not contain a valid $DLL_NAME"
    fi
fi

destination="$target_dir/$DLL_NAME"
cp -f -- "$cached_dll" "$destination"

printf 'Installed: %s\n' "$destination"
printf 'Version:   %s\n' "$version"
printf 'Cache:     %s\n' "$version_dir"
