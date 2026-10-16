#!/usr/bin/env bash
# This header must remain: DLO must not classify the quoted shell body as an env assignment.
# This launcher is embedded in the recipe; only auxiliary commands leave Steam's runtime.
host() (
    unset LD_PRELOAD PYTHONHOME PYTHONPATH
    if [[ "${STEAM_RUNTIME:-}" == /* ]]; then
        export LD_LIBRARY_PATH="${SYSTEM_LD_LIBRARY_PATH:-}"
        export PATH="${SYSTEM_PATH:-/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin}"
        unset STEAM_RUNTIME
    fi
    "$@"
)
exec {stdout_fd}>&1 {stderr_fd}>&2
logger_pid=''
log_dir="$HOME/.dlor/logs/helixsr/launcher"
printf -v timestamp '%(%Y-%m-%dT%H-%M-%S)T' -1
log_file="$log_dir/$timestamp.${EPOCHREALTIME##*.}.$BASHPID.log"
if host mkdir -p -- "$log_dir" && host command -v tee >/dev/null && : >> "$log_file"; then
    exec > >(host tee --output-error=warn -a -- "$log_file") 2>&1
    logger_pid=$!
    (
        export LC_ALL=C
        shopt -s nullglob
        logs=()
        for candidate in "$log_dir/"*.log; do
            if [[ -f "$candidate" && ! -L "$candidate" ]]; then logs+=("$candidate"); fi
        done
        excess=$(( ${#logs[@]} - 10 ))
        if (( excess > 0 )); then
            host rm -f -- "${logs[@]:0:excess}" || printf 'Warning: could not remove old logs in %s; continuing.\n' "$log_dir" >&2
        fi
    )
else
    printf 'Warning: could not enable logging to %s; continuing.\n' "$log_file" >&2
fi
cleanup() {
    if [[ -n "${DLOR_HELIXSR_RUNTIME_FILE:-}" ]]; then
        host rm -f -- "$DLOR_HELIXSR_RUNTIME_FILE" "$DLOR_HELIXSR_RUNTIME_FILE.setup" \
            "$DLOR_HELIXSR_RUNTIME_FILE.config" "$DLOR_HELIXSR_RUNTIME_FILE.configured" || true
    fi
}
launch_game() {
    cleanup
    trap - EXIT
    unset DLOR_HELIXSR_ARGS DLOR_HELIXSR_RUNTIME_FILE
    printf 'HelixSR launcher preparation finished; launching game.\n'
    # Finish logging before exec; game output must not become recipe log output.
    exec 1>&"$stdout_fd" 2>&"$stderr_fd"
    exec {stdout_fd}>&- {stderr_fd}>&-
    if [[ -n "$logger_pid" ]]; then wait "$logger_pid" || true; fi
    exec "$@"
}
failed() {
    printf 'HelixSR %s failed or was cancelled; launching the game without enabling HelixSR. Check ~/.dlor/logs/helixsr/.\n' "$1" >&2
}
trap cleanup EXIT
runtime_dir="$HOME/.dlor/runtime/helixsr"
if ! host mkdir -p -m 700 -- "$runtime_dir"; then
    failed "runtime preparation"
    launch_game "$@"
fi
DLOR_HELIXSR_RUNTIME_FILE=$(host mktemp "$runtime_dir/launch.XXXXXXXX") || { failed "runtime preparation"; launch_game "$@"; }
DLOR_HELIXSR_ARGS=$(host python3 -c 'import json,sys; print(json.dumps(sys.argv[1:]))' "$@") || { failed "argument preparation"; launch_game "$@"; }
export DLOR_HELIXSR_RUNTIME_FILE DLOR_HELIXSR_ARGS
if [[ "${DLOR_HELIXSR_ACTION:-off}" == on ]]; then
    host env @@SETUP@@
    if [[ ! -f "$DLOR_HELIXSR_RUNTIME_FILE.setup" ]]; then
        failed "setup"
        launch_game "$@"
    fi
    host env @@DEPENDENCY@@
    if [[ ! -s "$DLOR_HELIXSR_RUNTIME_FILE" || ! -s "$DLOR_HELIXSR_RUNTIME_FILE.config" ]]; then
        failed "OptiScaler dependency"
        launch_game "$@"
    fi
    IFS= read -r HELIXSR_CONFIG < "$DLOR_HELIXSR_RUNTIME_FILE.config"
    export HELIXSR_CONFIG
    host env @@CONFIGURE@@
    if [[ ! -f "$DLOR_HELIXSR_RUNTIME_FILE.configured" ]]; then
        failed "configuration"
        # Undo only this launch's owned dependency after configuration rollback succeeds.
        export DLOR_HELIXSR_ACTION=off
        host env @@CONFIGURE@@
        if [[ -f "$DLOR_HELIXSR_RUNTIME_FILE.configured" ]]; then host env @@DEPENDENCY@@; fi
        launch_game "$@"
    fi
    IFS= read -r proxy < "$DLOR_HELIXSR_RUNTIME_FILE"
    case "$proxy" in
        dxgi|winmm|version|dinput8|d3d12|dbghelp|wininet|winhttp) ;;
        *) failed "proxy selection"; launch_game "$@" ;;
    esac
    merged=$(host python3 - "$proxy" "${WINEDLLOVERRIDES:-}" <<'PY'
import sys
proxy, incoming = sys.argv[1:]
kept = []
for item in incoming.split(";"):
    if not item:
        continue
    names, separator, mode = item.partition("=")
    names = ",".join(name for name in names.split(",") if name.strip().lower().removesuffix(".dll") != proxy)
    if names:
        kept.append(names + separator + mode)
kept.append(proxy + "=n,b")
print(";".join(kept))
PY
    ) || { failed "Wine overrides"; launch_game "$@"; }
    export WINEDLLOVERRIDES="$merged"
else
    host env @@CONFIGURE@@
    if [[ -f "$DLOR_HELIXSR_RUNTIME_FILE.configured" ]]; then
        host env @@DEPENDENCY@@
    else
        printf 'HelixSR restoration failed; keeping dependency ownership for the next attempt.\n' >&2
    fi
fi
launch_game "$@"
