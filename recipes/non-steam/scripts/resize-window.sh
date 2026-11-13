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
readonly RECIPE_NAME="non-steam"
readonly SCRIPT_NAME="resize-window"
log_dir="${HOME}/.dlor/logs/$RECIPE_NAME/$SCRIPT_NAME"
printf -v log_timestamp '%(%Y-%m-%dT%H-%M-%S)T' -1
log_timestamp+=".${EPOCHREALTIME##*.}"
log_file="$log_dir/$log_timestamp.log"
if mkdir -p -- "$log_dir" && command -v tee >/dev/null 2>&1 && : >> "$log_file"; then
    # Keep draining output even if a log write or the console fails.
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

if [[ "${1:-}" == --help || "${1:-}" == -h ]]; then
    printf 'Usage: DLOR_NON_STEAM_APP_SIZE=fullscreen|WIDTHxHEIGHT ~/.dlor/run non-steam resize-window [commit] -- <app command...>\n'
    exit 0
fi
for tool in python3 xwininfo xprop; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        printf 'Error: required host command not found: %s\n' "$tool" >&2
        exit 1
    fi
done

# The runner calls helpers before launching the app. Fork a bounded monitor and
# close its inherited output pipes so neither helper completion nor game launch
# waits for a window. It writes diagnostics into this invocation's existing log.
python3 - "$log_file" <<'PY'
import ctypes
import ctypes.util
import fcntl
import hashlib
import io
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request


# Debian's small, older-glibc builds run on SteamOS and other Linux hosts without
# installing a system package. Pin both package and binary; never extract paths
# from the archive wholesale. Keep copyright alongside the downloaded binary.
WMCTRL_VERSION = '1.07-7+b1'
WMCTRL_PACKAGES = {
    'x86_64': ('amd64', '72188c2d0bca19ecfa98382685163c8176a0390a229f8584672b32229114c54f',
               '568efc486349f64ddf2e2bbced9a2d79090c009edf602a0d6cdc78a7bf93f028'),
    'aarch64': ('arm64', '281b4ac63f623d62039d7001ddefe0e8681284918d7d665e0fe5b8aa0d90c047',
                '78fc2cc154518a9b615b14baee7b9ed525c74891b5046899f38b1937c220ad43'),
}


def valid_file(path, digest):
    return (path.is_file() and not path.is_symlink()
            and hashlib.sha256(path.read_bytes()).hexdigest() == digest)


def wmctrl_payload(package):
    if package[:8] != b'!<arch>\n':
        raise ValueError('Invalid wmctrl Debian archive.')
    offset = 8
    while offset + 60 <= len(package):
        header = package[offset:offset + 60]
        size = int(header[48:58])
        start = offset + 60
        if header[58:60] != b'`\n' or size < 0 or start + size > len(package):
            raise ValueError('Invalid wmctrl archive member.')
        name = header[:16].decode('ascii').strip().rstrip('/')
        if name == 'data.tar.xz':
            with tarfile.open(fileobj=io.BytesIO(package[start:start + size]), mode='r:xz') as archive:
                result = []
                for name in ['./usr/bin/wmctrl', './usr/share/doc/wmctrl/copyright']:
                    member = archive.getmember(name)
                    if not member.isfile() or member.size > 1024 * 1024:
                        raise ValueError('Invalid wmctrl payload file.')
                    result.append(archive.extractfile(member).read())
                return result
        offset = start + size + size % 2
    raise ValueError('wmctrl archive has no supported data payload.')


def ensure_wmctrl():
    installed = shutil.which('wmctrl')
    if installed:
        return installed
    machine = platform.machine()
    if machine not in WMCTRL_PACKAGES:
        raise RuntimeError(f'Install wmctrl manually on unsupported architecture {machine}.')
    arch, package_hash, binary_hash = WMCTRL_PACKAGES[machine]
    asset = f'wmctrl_{WMCTRL_VERSION}_{arch}.deb'
    root = Path(os.environ.get('DLOR_NON_STEAM_CACHE_DIR', Path.home() / '.dlor/cache/non-steam'))
    cache = root / 'wmctrl' / WMCTRL_VERSION / arch
    cache.mkdir(parents=True, exist_ok=True)
    binary, package = cache / 'wmctrl', cache / asset
    # Concurrent launches share one download/extraction; atomic replacements keep
    # an interrupted installation from becoming a usable cache entry.
    with (cache / '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if valid_file(binary, binary_hash) and (cache / 'copyright').is_file():
            binary.chmod(0o755)
            print(f'Using cached wmctrl: {binary}', flush=True)
            return str(binary)
        with tempfile.TemporaryDirectory(prefix='.install-', dir=cache) as staging:
            staging = Path(staging)
            if not valid_file(package, package_hash):
                print(f'Downloading {asset} from deb.debian.org.', flush=True)
                url = f'https://deb.debian.org/debian/pool/main/w/wmctrl/{asset}'
                with urllib.request.urlopen(url, timeout=15) as response:
                    content = response.read(1024 * 1024 + 1)
                if len(content) > 1024 * 1024 or hashlib.sha256(content).hexdigest() != package_hash:
                    raise ValueError('wmctrl package SHA-256 verification failed.')
                download = staging / asset
                download.write_bytes(content)
                download.replace(package)
            executable, copyright = wmctrl_payload(package.read_bytes())
            if hashlib.sha256(executable).hexdigest() != binary_hash:
                raise ValueError('wmctrl binary SHA-256 verification failed.')
            for name, content, mode in [('copyright', copyright, 0o644), ('wmctrl', executable, 0o755)]:
                target = staging / name
                target.write_bytes(content)
                target.chmod(mode)
                target.replace(cache / name)
        print(f'Cached wmctrl: {binary}', flush=True)
        return str(binary)


def dimensions(value, screen):
    if value == 'fullscreen':
        return screen
    match = re.fullmatch(r'([1-9][0-9]{2,4})x([1-9][0-9]{2,4})', value)
    if not match:
        raise ValueError('Choose fullscreen or WIDTHxHEIGHT for DLOR_NON_STEAM_APP_SIZE.')
    width, height = map(int, match.groups())
    if width > 16384 or height > 16384:
        raise ValueError('App dimensions must not exceed 16384 pixels.')
    return width, height


def parent_pid(pid):
    for line in (Path('/proc') / str(pid) / 'status').read_text().splitlines():
        if line.startswith('PPid:'):
            return int(line.split()[1])
    return 0


def belongs_to_app(pid, appid):
    # XRes supplies the host PID even when Flatpak's _NET_WM_PID uses a sandbox
    # PID. Walk parents for applications which remove Steam's environment.
    seen = set()
    while pid > 1 and pid not in seen and len(seen) < 64:
        seen.add(pid)
        try:
            values = dict(part.split(b'=', 1) for part in
                          (Path('/proc') / str(pid) / 'environ').read_bytes().split(b'\0') if b'=' in part)
            value = values.get(b'SteamAppId', values.get(b'SteamAppID'))
            if value is not None:
                return value == appid.encode()
            pid = parent_pid(pid)
        except (OSError, ValueError):
            return False
    return False


class ClientSpec(ctypes.Structure):
    _fields_ = [('client', ctypes.c_ulong), ('mask', ctypes.c_ulong)]


class ClientValue(ctypes.Structure):
    _fields_ = [('spec', ClientSpec), ('length', ctypes.c_long), ('value', ctypes.c_void_p)]


class X11:
    def __init__(self):
        self.xlib = ctypes.CDLL(ctypes.util.find_library('X11') or 'libX11.so.6')
        self.xres = ctypes.CDLL(ctypes.util.find_library('XRes') or 'libXRes.so.1')
        self.xlib.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self.xlib.XOpenDisplay.restype = ctypes.c_void_p
        self.xlib.XCloseDisplay.argtypes = [ctypes.c_void_p]
        self.xlib.XDefaultScreen.argtypes = [ctypes.c_void_p]
        self.xlib.XDisplayWidth.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self.xlib.XDisplayHeight.argtypes = [ctypes.c_void_p, ctypes.c_int]
        # A window may disappear between enumeration and XRes lookup.
        handler = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
        self.error_handler = handler(lambda _display, _event: 0)
        self.xlib.XSetErrorHandler.argtypes = [handler]
        self.xlib.XSetErrorHandler(self.error_handler)
        self.xres.XResQueryClientIds.argtypes = [ctypes.c_void_p, ctypes.c_long,
                                               ctypes.POINTER(ClientSpec), ctypes.POINTER(ctypes.c_long),
                                               ctypes.POINTER(ctypes.POINTER(ClientValue))]
        self.xres.XResGetClientPid.argtypes = [ctypes.POINTER(ClientValue)]
        self.xres.XResGetClientPid.restype = ctypes.c_int
        self.xres.XResClientIdsDestroy.argtypes = [ctypes.c_long, ctypes.POINTER(ClientValue)]
        self.display = self.xlib.XOpenDisplay(None)
        if not self.display:
            raise RuntimeError('Cannot connect to the app X11 display.')

    def screen_size(self):
        screen = self.xlib.XDefaultScreen(self.display)
        return (self.xlib.XDisplayWidth(self.display, screen),
                self.xlib.XDisplayHeight(self.display, screen))

    def window_pid(self, window):
        spec = ClientSpec(int(window, 16), 2)  # XRES_CLIENT_ID_PID_MASK
        count = ctypes.c_long()
        values = ctypes.POINTER(ClientValue)()
        self.xres.XResQueryClientIds(self.display, 1, ctypes.byref(spec), ctypes.byref(count), ctypes.byref(values))
        try:
            for index in range(count.value):
                pid = self.xres.XResGetClientPid(ctypes.byref(values[index]))
                if pid > 0:
                    return pid
            return 0
        finally:
            self.xres.XResClientIdsDestroy(count, values)

    def close(self):
        self.xlib.XCloseDisplay(self.display)


def windows():
    result = subprocess.run(['xwininfo', '-root', '-children'], capture_output=True, text=True, timeout=3, check=True)
    for line in result.stdout.splitlines():
        match = re.match(r'\s*(0x[0-9a-fA-F]+)\s+.*\s([0-9]+)x([0-9]+)[+-]', line)
        if match and int(match[2]) >= 200 and int(match[3]) >= 100:
            yield match[1]


def main_window(window):
    result = subprocess.run(['xprop', '-id', window, '_NET_WM_WINDOW_TYPE', 'WM_TRANSIENT_FOR'],
                            capture_output=True, text=True, timeout=3, check=True)
    # Do not resize menus, tooltips, splash screens, or child dialogs.
    excluded = ('_DIALOG', '_MENU', '_TOOLTIP', '_SPLASH', '_POPUP', '_DROPDOWN', '_NOTIFICATION')
    return not any(kind in result.stdout for kind in excluded) and 'window id #' not in result.stdout


def monitor(x11, appid, size, deadline, wmctrl='wmctrl'):
    while time.monotonic() < deadline:
        for window in windows():
            if not belongs_to_app(x11.window_pid(window), appid) or not main_window(window):
                continue
            width, height = dimensions(size, x11.screen_size())
            # Flatpak launchers can reparent the app outside Steam's reaper.
            # Tag only the verified app window so Gaming Mode can focus it.
            subprocess.run(['xprop', '-id', window, '-f', 'STEAM_GAME', '32c',
                            '-set', 'STEAM_GAME', appid], check=True, timeout=3)
            # Retry during startup because a restored session can resize its main
            # window after it appears. Stop afterward so manual resizing works.
            subprocess.run([wmctrl, '-ir', window, '-b', 'remove,fullscreen,maximized_vert'], check=True, timeout=3)
            subprocess.run([wmctrl, '-ir', window, '-b', 'remove,maximized_horz'], check=True, timeout=3)
            for _ in range(6):
                subprocess.run([wmctrl, '-ir', window, '-e', f'0,0,0,{width},{height}'], check=True, timeout=3)
                time.sleep(.5)
            print(f'Resized app {appid} window {window} to {width}x{height}.', flush=True)
            return
        time.sleep(.25)
    raise RuntimeError('No matching app window appeared within 30 seconds; leaving other windows unchanged.')


def main():
    size = os.environ.get('DLOR_NON_STEAM_APP_SIZE', '')
    dimensions(size, (1, 1))  # Validate before detaching.
    appid = os.environ.get('SteamAppId', os.environ.get('SteamAppID', ''))
    if not appid.isascii() or not appid.isdecimal() or not 0 < int(appid) < 2 ** 32:
        raise ValueError('A valid SteamAppId is required to identify this app safely.')
    if not os.environ.get('DISPLAY'):
        raise ValueError('App Size requires an X11/XWayland display.')
    # Check libraries/display before reporting successful monitor startup.
    connection = X11()
    connection.close()
    pid = os.fork()
    if pid:
        print(f'Waiting for app {appid} in background (monitor {pid}).', flush=True)
        return
    os.setsid()
    status = 0
    try:
        # Avoid keeping the runner's tee/output pipes alive. Logging is best effort.
        try:
            output = os.open(sys.argv[1], os.O_WRONLY | os.O_APPEND)
        except OSError:
            output = os.open(os.devnull, os.O_WRONLY)
        source = os.open(os.devnull, os.O_RDONLY)
        os.dup2(source, 0)
        os.dup2(output, 1)
        os.dup2(output, 2)
        os.close(source)
        os.close(output)
        wmctrl = ensure_wmctrl()
        x11 = X11()
        try:
            monitor(x11, appid, size, time.monotonic() + 30, wmctrl)
        finally:
            x11.close()
    except Exception as error:
        print(f'Error: resize-window monitor: {error}', file=sys.stderr, flush=True)
        status = 1
    finally:
        print(f'resize-window monitor finished with exit status {status}.', flush=True)
        os._exit(status)


if __name__ == '__main__':
    main()
PY
