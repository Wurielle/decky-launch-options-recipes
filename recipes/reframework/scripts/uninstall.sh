#!/usr/bin/env bash
set -Eeuo pipefail

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
