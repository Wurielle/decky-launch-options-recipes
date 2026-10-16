#!/bin/bash
# Generic launcher only. Recipe scripts are ALWAYS downloaded, never bundled or cached.
# Keep game argv and Steam's environment untouched outside the helper subshell.
usage() {
    printf 'Usage: ~/.dlor/run [--wrapper] <recipe-name> <script-name> [commit-sha] -- <game command...>\n' >&2
    printf 'A full commit SHA is recommended; omitting it downloads from the dev branch.\n' >&2
}
# Mode is invocation-scoped: Steam shares launch-option assignments with every
# runner in a command chain, so an environment flag cannot safely select it.
mode=''
export -n mode
if [[ "${1:-}" == --wrapper ]]; then
    mode=wrapper
    shift
fi
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

clean_host_environment() {
    # Shell builtins must precede every host subprocess, including logging tools.
    unset LD_PRELOAD
    if [[ "$mode" == wrapper ]]; then unset PYTHONHOME PYTHONPATH; fi
    if [[ "${STEAM_RUNTIME:-}" == /* ]]; then
        export LD_LIBRARY_PATH="${SYSTEM_LD_LIBRARY_PATH:-}"
        export PATH="${SYSTEM_PATH:-/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin}"
        unset STEAM_RUNTIME
    fi
}
host_clean() (
    clean_host_environment
    "$@"
)

# Only wrappers need a download path visible to the original game environment.
download=''
if [[ "$mode" == wrapper ]]; then
    if ! download="$(host_clean mktemp "${TMPDIR:-/tmp}/dlor-script.XXXXXXXX.sh")"; then
        if [[ -n "$download" ]]; then host_clean rm -f -- "$download"; fi
        printf 'Error: could not allocate wrapper download; continuing game launch.\n' >&2
        exec "$@"
    fi
    cleanup_wrapper_download() {
        local status=$?
        # EXIT traps also run in subshells; only the owning parent may remove
        # a successful download before its body has been read.
        if [[ "$BASHPID" == "$$" ]]; then
            trap - EXIT INT TERM
            host_clean rm -f -- "$download"
            exit "$status"
        fi
    }
    trap cleanup_wrapper_download EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
fi
(
    clean_host_environment

    log_dir="$HOME/.dlor/logs/run"
    printf -v timestamp '%(%Y-%m-%dT%H-%M-%S)T' -1
    log_file="$log_dir/$timestamp.${EPOCHREALTIME##*.}.$BASHPID.log"
    if mkdir -p -- "$log_dir" && command -v tee >/dev/null 2>&1 && : >> "$log_file"; then
        exec > >(tee --output-error=warn -a -- "$log_file") 2>&1
        # Timestamped filenames sort oldest first; keep the latest 10 per folder.
        # Stay self-contained for scripts downloaded separately, including bash -s.
        (
            export LC_ALL=C
            shopt -s nullglob
            logs=()
            for candidate in "$log_dir/"*.log; do
                if [[ -f "$candidate" && ! -L "$candidate" ]]; then
                    logs+=("$candidate")
                fi
            done
            excess=$(( ${#logs[@]} - 10 ))
            if (( excess > 0 )); then
                rm -f -- "${logs[@]:0:excess}" ||
                    printf 'Warning: could not remove old logs in %s; continuing.\n' "$log_dir" >&2
            fi
        )
    else
        printf 'Warning: could not enable logging to %s; continuing.\n' "$log_file" >&2
    fi

    set -Eeuo pipefail
    cleanup() {
        status=$?
        set +e
        if [[ -n "$download" ]] && { (( status != 0 )) || [[ "$mode" != wrapper ]]; }; then
            rm -f -- "$download"
        fi
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
    if (( use_default )) && [[ "$mode" == wrapper ]]; then
        printf 'Error: wrapper requires a full commit SHA.\n' >&2
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
    if [[ "$mode" != wrapper ]]; then
        download="$(mktemp "${TMPDIR:-/tmp}/dlor-script.XXXXXXXX.sh")"
    fi
    printf 'Downloading %s\n' "$url"
    curl -fsSL --proto '=https' --proto-redir '=https' \
        --connect-timeout 10 --max-time 60 --retry 3 --retry-delay 1 --retry-max-time 90 \
        --output "$download" "$url"
    if [[ ! -s "$download" ]]; then
        printf 'Error: downloaded script is empty.\n' >&2
        exit 1
    fi
    if [[ "$mode" != wrapper ]]; then
        bash "$download" "${STEAM_COMPAT_INSTALL_PATH:-}"
    fi
)
helper_status=$?
if [[ "$mode" == wrapper ]]; then
    # Read with Bash, not a host subprocess or stdin-consuming pipeline. Execute
    # only a complete download, after deleting its sole temporary copy.
    body=''
    if (( helper_status == 0 )) && body=$(< "$download") && [[ -n "$body" ]]; then
        if host_clean rm -f -- "$download"; then
            trap - EXIT INT TERM
            export DLOR_SCRIPT_REVISION="$sha"
            exec bash -c "$body" -- "$@"
        fi
    fi
    host_clean rm -f -- "$download"
    trap - EXIT INT TERM
    printf 'Recipe wrapper unavailable; continuing game launch.\n' >&2
fi
if (( helper_status != 0 )); then
    printf 'Recipe helper failed (exit %s); continuing game launch.\n' "$helper_status" >&2
fi
exec "$@"
