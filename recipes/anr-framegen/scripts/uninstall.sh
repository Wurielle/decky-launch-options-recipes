#!/usr/bin/env bash
# Generated from entrypoint.sh.in; Python stays in the authenticated loader.py.
# Narrow acquisition/logging pattern from the independent OptiScaler recipe.
host_exec() {
    unset LD_PRELOAD PYTHONHOME PYTHONPATH
    if [[ ${STEAM_RUNTIME:-} == /* ]]; then
        export PATH="${SYSTEM_PATH:-/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin}"
        export LD_LIBRARY_PATH="${SYSTEM_LD_LIBRARY_PATH:-}"
        unset STEAM_RUNTIME
    fi
    exec "$@"
}
host() ( host_exec "$@" )
start_log() {
    local log_dir stamp candidate excess component attributes owner mode
    logger_pid=''
    exec {console_out}>&1 {console_err}>&2
    # HOME may legitimately be a symlink; controlled descendants may not.
    IFS= read -r -d '' log_dir < <(host readlink -ez -- "$HOME") || return 0
    for component in .dlor logs anr-framegen "$1"; do
        log_dir=$log_dir/$component
        if [[ -L $log_dir || ( -e $log_dir && ! -d $log_dir ) ]]; then
            printf 'Warning: unsafe log directory; console logging only.\n' >&2
            return 0
        fi
        if [[ ! -d $log_dir ]]; then
            (umask 077; host mkdir -m 700 -- "$log_dir") || return 0
        fi
        attributes=$(host stat -c '%u:%a' -- "$log_dir") || return 0
        owner=${attributes%%:*} mode=${attributes#*:}
        [[ $owner == "$EUID" && $mode =~ ^[0-7]{3,4}$ ]] || return 0
        (( (8#$mode & 022) == 0 )) || return 0
    done
    if [[ -d $log_dir ]]; then
        stamp=$(host date -u +%Y%m%dT%H%M%S.%N)-$$
        if (umask 077; : > "$log_dir/$stamp.log"); then
            exec > >(
                if ! host tee --output-error=warn -- "$log_dir/$stamp.log" >&"$console_out" 2>&"$console_err"; then
                    printf 'Warning: logger failed; continuing on console.\n' >&"$console_err"
                    while IFS= read -r line || [[ -n $line ]]; do
                        printf '%s\n' "$line" >&"$console_out"
                    done
                fi
            ) 2>&1
            logger_pid=$!
            (
                export LC_ALL=C
                shopt -s nullglob
                logs=()
                for candidate in "$log_dir/"*.log; do
                    [[ -f $candidate && ! -L $candidate ]] && logs+=("$candidate")
                done
                excess=$(( ${#logs[@]} - 10 ))
                if (( excess > 0 )); then
                    host rm -f -- "${logs[@]:0:excess}" || printf 'Warning: log retention failed; continuing.\n' >&2
                fi
            )
        else
            printf 'Warning: logging unavailable; continuing.\n' >&2
        fi
    else
        printf 'Warning: logging unavailable; continuing.\n' >&2
    fi
}
finish_log() {
    printf 'ANR FG %s exit status: %s\n' "$entry_name" "$1"
    exec 1>&"$console_out" 2>&"$console_err"
    [[ -z $logger_pid ]] || wait "$logger_pid" || :
    exec {console_out}>&- {console_err}>&-
}
BUNDLE_REVISION=42c3bc9b31bfc10d8aab67b8b782ce63a8595bd6
BUNDLE_REPOSITORY=Wurielle/decky-launch-options-recipes
MANIFEST_SHA256=50044ca8a901045d7d40d4fb28e318fa4706e11e373a0e9b600ddd08cdfcb1ac
run_loader() (
    inherited_umask=$(umask)
    umask 077
    private_work=''
    download_pid=''
    cleanup_loader() {
        [[ -z $download_pid ]] || { kill -KILL "$download_pid" 2>/dev/null || :; wait "$download_pid" 2>/dev/null || :; }
        [[ -z $private_work ]] || host rm -rf -- "$private_work"
        :
    }
    trap cleanup_loader EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    revision=$BUNDLE_REVISION
    repository=$BUNDLE_REPOSITORY
    if [[ ! $revision =~ ^[a-f0-9]{40}$ ||
          ! $repository =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*$ ||
          ! $MANIFEST_SHA256 =~ ^[a-f0-9]{64}$ ]]; then
        printf 'ANR FG: invalid bundle reference\n' >&2
        return 1
    fi
    IFS= read -r -d '' canonical_home < <(host readlink -ez -- "$HOME") || return 1
    cache=$canonical_home
    for part in .dlor cache anr-framegen source "$revision"; do
        cache=$cache/$part
        if [[ ! -e $cache && ! -L $cache ]]; then
            host mkdir -m 700 -- "$cache" || [[ -d $cache ]] || return 1
        fi
        if [[ -L $cache || ! -d $cache ]]; then
            printf 'ANR FG: unsafe cache directory: %s\n' "$cache" >&2
            return 1
        fi
        attributes=$(host stat -c '%u:%a' -- "$cache") || return 1
        owner=${attributes%%:*} mode=${attributes#*:}
        [[ $owner == "$EUID" && $mode =~ ^[0-7]{3,4}$ ]] || return 1
        (( (8#$mode & 022) == 0 )) || { printf 'ANR FG: writable cache directory\n' >&2; return 1; }
    done
    for name in downloads.json loader.py; do
        if [[ -L $cache/$name || ( -e $cache/$name && ! -f $cache/$name ) ]]; then
            printf 'ANR FG: unsafe source cache file\n' >&2
            return 1
        fi
    done
    private_work=$(host mktemp -d "$cache/.loader.XXXXXXXX") || return 1
    verify_source() {
        local actual
        actual=$(host sha256sum < "$1") || return 1
        [[ ${actual%% *} == "$2" ]]
    }
    snapshot_source() {
        local name=$1 expected=$2 status
        if [[ ! -f $cache/$name ]] || ! verify_source "$cache/$name" "$expected"; then
            printf 'ANR FG: fetching authenticated %s\n' "$name"
            ( host_exec curl -fL --silent --show-error --connect-timeout 15 --max-time 180 \
                --proto '=https' --proto-redir '=https' --max-redirs 5 --tlsv1.2 \
                -o "$private_work/download" \
                "https://raw.githubusercontent.com/$repository/$revision/recipes/anr-framegen/scripts/$name" </dev/null ) &
            download_pid=$!
            wait "$download_pid"
            status=$?
            download_pid=''
            (( status == 0 )) || return "$status"
            verify_source "$private_work/download" "$expected" || { printf 'ANR FG: source checksum mismatch\n' >&2; return 1; }
            host mv -f -- "$private_work/download" "$cache/$name" || return 1
        fi
        host cp -- "$cache/$name" "$private_work/$name" || return 1
        verify_source "$private_work/$name" "$expected" || return 1
        host chmod 400 -- "$private_work/$name" || return 1
    }
    snapshot_source downloads.json "$MANIFEST_SHA256" || return $?
    loader_digest='' digest_lines=0
    while IFS= read -r line; do
        if [[ $line =~ ^[[:space:]]*\"loader.py\":\ \"([a-f0-9]{64})\",?$ ]]; then
            loader_digest=${BASH_REMATCH[1]}
            (( digest_lines += 1 ))
        fi
    done < "$private_work/downloads.json"
    (( digest_lines == 1 )) || { printf 'ANR FG: invalid loader manifest entry\n' >&2; return 1; }
    snapshot_source loader.py "$loader_digest" || return $?
    umask "$inherited_umask"
    DLOR_ANR_MANIFEST="$private_work/downloads.json" \
    DLOR_ANR_MANIFEST_SHA256="$MANIFEST_SHA256" \
        host python3 -I -B "$private_work/loader.py" "$entry_name" "$@"
)
entry_name=uninstall
start_log "$entry_name"
run_loader "$@"
status=$?
finish_log "$status"
exit "$status"
