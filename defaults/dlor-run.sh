#!/bin/bash
# Generic launcher only. Recipe scripts are ALWAYS downloaded, never bundled or cached.
# Keep game argv and Steam's environment untouched outside the helper subshell.
usage() {
    printf 'Usage: ~/.dlor/run <recipe-name> <script-name> [commit-sha] -- <game command...>\n' >&2
    printf 'A full commit SHA is recommended; omitting it downloads from the dev branch.\n' >&2
}
if (( $# < 4 )); then
    usage
    exit 2
fi
recipe="$1"
script="$2"
sha=''
use_default=0
if [[ "$3" == -- ]]; then
    use_default=1
    shift 3
elif (( $# >= 5 )) && [[ "$4" == -- ]]; then
    sha="$3"
    shift 4
else
    usage
    exit 2
fi

(
    # Shell builtins must precede every host subprocess, including logging tools.
    unset LD_PRELOAD
    if [[ "${STEAM_RUNTIME:-}" == /* ]]; then
        export LD_LIBRARY_PATH="${SYSTEM_LD_LIBRARY_PATH:-}"
        export PATH="${SYSTEM_PATH:-/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin}"
        unset STEAM_RUNTIME
    fi

    log_dir="$HOME/.dlor/logs/run"
    printf -v timestamp '%(%Y-%m-%dT%H-%M-%S)T' -1
    log_file="$log_dir/$timestamp.${EPOCHREALTIME##*.}.$BASHPID.log"
    if mkdir -p -- "$log_dir" && : >> "$log_file" && command -v tee >/dev/null 2>&1; then
        exec > >(tee --output-error=warn -a -- "$log_file") 2>&1
    else
        printf 'Warning: could not enable logging to %s; continuing.\n' "$log_file" >&2
    fi

    set -Eeuo pipefail
    download=''
    cleanup() {
        status=$?
        set +e
        if [[ -n "$download" ]]; then rm -f -- "$download"; fi
        printf 'run finished with exit status %s.\n' "$status"
        exit "$status"
    }
    trap cleanup EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    trap 'printf "Error: run line %s: %s (exit %s)\n" "$LINENO" "$BASH_COMMAND" "$?" >&2' ERR

    if [[ ! "$recipe" =~ ^[a-z0-9]+(-[a-z0-9]+)*$ ||
          ! "$script" =~ ^[a-z0-9]+(-[a-z0-9]+)*$ ]]; then
        printf 'Error: invalid recipe or script name (omit .sh).\n' >&2
        exit 2
    fi
    if (( use_default )); then
        revision='refs/heads/dev'
    elif [[ "$sha" =~ ^[a-f0-9]{40}$ ]]; then
        revision="$sha"
    else
        printf 'Error: invalid full commit SHA.\n' >&2
        exit 2
    fi
    repository="${DLOR_REPOSITORY-Wurielle/decky-launch-options-recipes}"
    if [[ ! "$repository" =~ ^[a-zA-Z0-9_-][a-zA-Z0-9_.-]*/[a-zA-Z0-9_-][a-zA-Z0-9_.-]*$ ]]; then
        printf 'Error: invalid repository; expected owner/repository.\n' >&2
        exit 2
    fi
    url="https://raw.githubusercontent.com/$repository/$revision/recipes/$recipe/scripts/$script.sh"
    printf 'Starting %s/%s at %s\n' "$recipe" "$script" "$revision"

    # Download completely before executing: a failed/partial response must never run.
    # A unique temporary file permits concurrent launches and is removed on exit.
    download="$(mktemp "${TMPDIR:-/tmp}/dlor-script.XXXXXXXX.sh")"
    printf 'Downloading %s\n' "$url"
    curl -fsSL --proto '=https' --proto-redir '=https' \
        --connect-timeout 10 --max-time 60 --retry 3 --retry-delay 1 --retry-max-time 90 \
        --output "$download" "$url"
    if [[ ! -s "$download" ]]; then
        printf 'Error: downloaded script is empty.\n' >&2
        exit 1
    fi
    bash "$download" "${STEAM_COMPAT_INSTALL_PATH:-}"
)
helper_status=$?
if (( helper_status != 0 )); then
    printf 'Recipe helper failed (exit %s); continuing game launch.\n' "$helper_status" >&2
fi
exec "$@"
