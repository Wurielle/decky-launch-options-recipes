#!/usr/bin/env bash
# Keep this bootstrap self-contained: Steam downloads this script into bash -s.
readonly RECIPE_NAME="optiscaler"
readonly SCRIPT_NAME="update-nightly"
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

readonly REPOSITORY="optiscaler/OptiScaler-nightly"
readonly RELEASES_URL="https://api.github.com/repos/${REPOSITORY}/releases?per_page=1"
readonly CACHE_ROOT="${OPTISCALER_CACHE_DIR:-${TMPDIR:-/tmp}/update-optiscaler}"

fail() {
    printf 'Error: %s\n' "$*" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

usage() {
    printf 'Usage: bash update-nightly.sh /path/to/steam-game-directory\n'
    printf 'Updates fgmod dxgi.dll installations beside OptiScaler.ini, including subfolders.\n'
    printf 'Preserves configuration. Override cache with OPTISCALER_CACHE_DIR (default: %s).\n' "$CACHE_ROOT"
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
    exit 0
fi
if (( $# != 1 )); then
    usage >&2
    exit 2
fi
[[ -d "$1" ]] || fail "Game directory does not exist: $1"
target_dir="$(cd -- "$1" && pwd -P)"

# fgmod may install beside a nested executable rather than at the Steam root.
# Require its OptiScaler config so an unrelated dxgi.dll is not replaced.
install_dirs=()
while IFS= read -r -d '' config; do
    directory="${config%/*}"
    if [[ -f "$directory/dxgi.dll" ]]; then
        install_dirs+=("$directory")
    fi
done < <(find "$target_dir" -type f -iname 'OptiScaler.ini' -print0)
(( ${#install_dirs[@]} > 0 )) || fail "No fgmod OptiScaler installation found in: $target_dir"

require_command curl
require_command python3
require_command mktemp

mkdir -p -- "$CACHE_ROOT"
printf 'Checking the latest OptiScaler nightly release...\n'
# Nightlies are prereleases, which GitHub's /releases/latest endpoint excludes.
release_info="$(curl -fsSL --retry 3 --retry-delay 1 "$RELEASES_URL" | python3 -c '
import json, re, sys
releases = json.load(sys.stdin)
release = next(r for r in releases if not r["draft"])
asset = next(a for a in release["assets"]
             if a["name"].startswith("OptiScaler_") and a["name"].endswith(".7z"))
version, name = release["tag_name"], asset["name"]
if any(not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", s) for s in (version, name)):
    sys.exit("Invalid release version or asset name")
print(version)
print(name)
')" || fail "Could not determine the latest nightly release"
mapfile -t release_fields <<< "$release_info"
version="${release_fields[0]}"
asset_name="${release_fields[1]}"
version_dir="$CACHE_ROOT/$version"
archive="$version_dir/$asset_name"
cached_files="$version_dir/files"
asset_url="https://github.com/${REPOSITORY}/releases/download/${version}/${asset_name}"
mkdir -p -- "$version_dir"

download_tmp=""
extract_tmp=""
cleanup() {
    if [[ -n "$download_tmp" ]]; then
        rm -f -- "$download_tmp"
    fi
    if [[ -n "$extract_tmp" ]]; then
        rm -rf -- "$extract_tmp"
    fi
}

download_archive() {
    download_tmp="$(mktemp "$version_dir/.${asset_name}.XXXXXX")"
    printf 'Downloading %s...\n' "$version"
    curl -fsSL --retry 3 --retry-delay 1 "$asset_url" -o "$download_tmp"
    [[ -s "$download_tmp" ]] || fail "Downloaded archive is empty"
    mv -f -- "$download_tmp" "$archive"
    download_tmp=""
}

extract_files() {
    extract_tmp="$(mktemp -d "$version_dir/.files.XXXXXX")"
    if ! "$extractor" x -y "-o$extract_tmp" "$archive" ||
        [[ ! -s "$extract_tmp/OptiScaler.dll" ]]; then
        rm -rf -- "$extract_tmp"
        extract_tmp=""
        return 1
    fi
    rm -rf -- "$cached_files"
    mv -- "$extract_tmp" "$cached_files"
    extract_tmp=""
}

if [[ -s "$cached_files/OptiScaler.dll" ]]; then
    printf 'Using cached %s.\n' "$cached_files"
else
    extractor=""
    for candidate in 7zz 7z 7za; do
        if command -v "$candidate" >/dev/null 2>&1; then
            extractor="$candidate"
            break
        fi
    done
    [[ -n "$extractor" ]] || fail "Required command not found: 7zz, 7z, or 7za"
    if [[ -s "$archive" ]]; then
        printf 'Using cached archive %s.\n' "$archive"
    else
        download_archive
    fi
    if ! extract_files; then
        printf 'Cached archive is invalid; downloading it again.\n' >&2
        rm -f -- "$archive"
        download_archive
        extract_files || fail "The downloaded archive does not contain a valid OptiScaler.dll"
    fi
fi

for directory in "${install_dirs[@]}"; do
    # Copy bundled DLLs with their relative layout, leaving user config intact.
    while IFS= read -r -d '' source; do
        relative="${source#"$cached_files/"}"
        [[ "$relative" == 'OptiScaler.dll' ]] && continue
        destination="$directory/$relative"
        mkdir -p -- "${destination%/*}"
        cp -f -- "$source" "$destination"
    done < <(find "$cached_files" -type f -iname '*.dll' -print0)
    cp -f -- "$cached_files/OptiScaler.dll" "$directory/dxgi.dll"
    printf 'Upgraded: %s\n' "$directory"
done
printf 'Version: %s\nCache: %s\n' "$version" "$version_dir"
