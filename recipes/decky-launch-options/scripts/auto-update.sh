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
readonly RECIPE_NAME="decky-launch-options"
readonly SCRIPT_NAME="auto-update"
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
    printf 'Usage: ~/.dlor/run decky-launch-options auto-update [commit] -- <game command...>\n'
    printf 'DLO_UPDATE_VARIANT=regular|with-store chooses the latest stable DLO build (default: regular).\n'
    exit 0
fi
command -v python3 >/dev/null || { printf 'Error: python3 is required.\n' >&2; exit 1; }
python3 - <<'PYTHON'
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import socket
import stat
import struct
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile


PLUGIN = 'Launch Options'
ASSETS = {
    'regular': 'decky-launch-options.zip',
    'with-store': 'decky-launch-options-with-store.zip',
}
RELEASE_URL = 'https://api.github.com/repos/Wurielle/decky-launch-options/releases/latest'
MAX_PACKAGE = 64 * 1024 * 1024
MAX_MESSAGE = 8 * 1024 * 1024


class Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not req.full_url.startswith('https://') or not newurl.startswith('https://'):
            raise ValueError('Refusing a non-HTTPS redirect.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def request(url, timeout=15):
    # Loopback CEF traffic must not be sent to an HTTP proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), Redirects())
    return opener.open(urllib.request.Request(url, headers={
        'User-Agent': 'DLOR-DLO-Auto-Update', 'Accept': 'application/vnd.github+json',
    }), timeout=timeout)


def read_json(url):
    with request(url) as response:
        data = response.read(2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024:
        raise ValueError('Metadata response is too large.')
    return json.loads(data)


class CDP:
    """Small RFC 6455 text client for the already running loopback CEF endpoint."""
    def __init__(self, url):
        target = urllib.parse.urlsplit(url)
        if (target.scheme != 'ws' or target.hostname not in {'127.0.0.1', 'localhost', '::1'}
                or target.port != 8080 or target.username or target.password or target.fragment):
            raise ValueError('CEF returned a non-loopback debugging socket.')
        self.sock = socket.create_connection((target.hostname, target.port), timeout=15)
        self.sock.settimeout(125)
        self.stream = self.sock.makefile('rb')
        self.sequence = 0
        try:
            key = base64.b64encode(os.urandom(16)).decode('ascii')
            path = urllib.parse.urlunsplit(('', '', target.path or '/', target.query, ''))
            if any(c in path for c in '\r\n'):
                raise ValueError('Invalid debugging socket path.')
            self.sock.sendall((f'GET {path} HTTP/1.1\r\nHost: {target.netloc}\r\n'
                               'Upgrade: websocket\r\nConnection: Upgrade\r\n'
                               f'Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n').encode('ascii'))
            status_line = self.stream.readline(4096)
            if status_line.split()[1:2] != [b'101']:
                raise RuntimeError('CEF refused the debugging WebSocket.')
            headers = {}
            size = len(status_line)
            while True:
                line = self.stream.readline(4096)
                size += len(line)
                if size > 16384 or not line:
                    raise ValueError('Invalid WebSocket upgrade headers.')
                if line == b'\r\n':
                    break
                name, value = line.decode('ascii').split(':', 1)
                headers[name.lower()] = value.strip()
            expected = base64.b64encode(hashlib.sha1(
                (key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode('ascii')).digest()).decode('ascii')
            if (headers.get('sec-websocket-accept') != expected
                    or headers.get('upgrade', '').lower() != 'websocket'
                    or 'upgrade' not in [part.strip().lower() for part in headers.get('connection', '').split(',')]):
                raise ValueError('Invalid WebSocket upgrade response.')
        except BaseException:
            self.close()
            raise

    def close(self):
        self.stream.close()
        self.sock.close()

    def read(self, size):
        result = bytearray()
        while len(result) < size:
            chunk = self.stream.read(size - len(result))
            if not chunk:
                raise ConnectionError('CEF closed the debugging connection.')
            result.extend(chunk)
        return bytes(result)

    def send(self, opcode, payload):
        mask = os.urandom(4)
        size = len(payload)
        header = bytes([0x80 | opcode])
        if size < 126:
            header += bytes([0x80 | size])
        elif size < 65536:
            header += bytes([0x80 | 126]) + struct.pack('!H', size)
        else:
            header += bytes([0x80 | 127]) + struct.pack('!Q', size)
        self.sock.sendall(header + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def receive(self):
        message = bytearray()
        started = False
        while True:
            first, second = self.read(2)
            opcode = first & 15
            if first & 0x70 or second & 0x80:
                raise ValueError('Unsupported WebSocket frame.')
            size = second & 127
            if size == 126:
                size = struct.unpack('!H', self.read(2))[0]
            elif size == 127:
                size = struct.unpack('!Q', self.read(8))[0]
            if size > MAX_MESSAGE or len(message) + size > MAX_MESSAGE:
                raise ValueError('CEF message is too large.')
            if opcode >= 8 and (size > 125 or not first & 0x80):
                raise ValueError('Invalid WebSocket control frame.')
            payload = self.read(size)
            if opcode == 8:
                raise ConnectionError('CEF closed the debugging connection.')
            if opcode == 9:
                self.send(10, payload)
                continue
            if opcode == 10:
                continue
            if opcode == 1 and not started:
                started = True
            elif opcode != 0 or not started:
                raise ValueError('Expected a WebSocket text message.')
            message.extend(payload)
            if first & 0x80:
                return json.loads(message.decode('utf-8'))

    def evaluate(self, code):
        self.sequence += 1
        deadline = time.monotonic() + 125
        self.send(1, json.dumps({'id': self.sequence, 'method': 'Runtime.evaluate', 'params': {
            'expression': code, 'awaitPromise': True, 'returnByValue': True,
        }}).encode('utf-8'))
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Steam frontend operation timed out.')
            self.sock.settimeout(remaining)
            data = self.receive()
            if data.get('id') != self.sequence:
                continue
            if 'error' in data or 'exceptionDetails' in data.get('result', {}):
                raise RuntimeError('Steam frontend operation failed: ' + json.dumps(data))
            return data['result']['result'].get('value')


def connect_frontend():
    pages = read_json('http://127.0.0.1:8080/json/list')
    targets = [p for p in pages if p.get('title') == 'SharedJSContext']
    if len(targets) != 1 or not targets[0].get('webSocketDebuggerUrl'):
        raise RuntimeError('Steam SharedJSContext is unavailable; enable local CEF debugging first.')
    return CDP(targets[0]['webSocketDebuggerUrl'])


def version(value):
    # The store suffix denotes a build variant, not a prerelease channel.
    value = value.removesuffix('-with-store')
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?', value)
    if not match:
        raise ValueError(f'Unrecognized DLO version: {value!r}.')
    return (*map(int, match.group(1, 2, 3)), 0 if match.group(4) else 1)


def latest_release(variant='regular'):
    if variant not in ASSETS:
        raise ValueError(f'Unknown DLO update variant: {variant!r}.')
    asset_name = ASSETS[variant]
    release = read_json(RELEASE_URL)
    tag = release.get('tag_name', '')
    if release.get('draft') or release.get('prerelease') or not re.fullmatch(r'v?\d+\.\d+\.\d+', tag):
        raise ValueError('Latest DLO release is not a stable version.')
    assets = [a for a in release.get('assets', []) if a.get('name') == asset_name]
    if len(assets) != 1:
        raise ValueError(f'Latest DLO release has no unique {variant} plugin ZIP.')
    asset = assets[0]
    digest = asset.get('digest') or ''
    expected_url = f'https://github.com/Wurielle/decky-launch-options/releases/download/{tag}/{asset_name}'
    if (not re.fullmatch(r'sha256:[a-fA-F0-9]{64}', digest)
            or asset.get('browser_download_url') != expected_url
            or type(asset.get('size')) is not int or not 0 < asset['size'] <= MAX_PACKAGE):
        raise ValueError('DLO release URL, size, or SHA-256 metadata is invalid.')
    package_version = tag.removeprefix('v') + ('-with-store' if variant == 'with-store' else '')
    return {'version': package_version, 'asset': asset_name, 'url': expected_url,
            'sha256': digest[7:].lower(), 'size': asset['size']}


def private_directory(path):
    if path.is_symlink():
        raise ValueError(f'Refusing a symlinked updater directory: {path}')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not path.is_dir() or path.stat().st_uid != os.getuid():
        raise ValueError(f'Updater directory must belong to the current user: {path}')
    path.chmod(0o700)
    return path


def validate_package(path, release):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Plugin cache entry is not a regular file.')
    if path.stat().st_size != release['size']:
        raise ValueError('Plugin ZIP size mismatch.')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    digest = digest.hexdigest()
    if digest != release['sha256']:
        raise ValueError('Plugin ZIP SHA-256 mismatch.')
    with zipfile.ZipFile(path) as archive:
        seen = set()
        expanded = 0
        for entry in archive.infolist():
            member = PurePosixPath(entry.filename)
            mode = entry.external_attr >> 16
            expanded += entry.file_size
            if (not member.parts or member.parts[0] != PLUGIN or member.is_absolute()
                    or '..' in member.parts or '\\' in entry.filename or '\x00' in entry.filename
                    or entry.filename.rstrip('/') != member.as_posix()
                    or (not entry.is_dir() and len(member.parts) < 2)
                    or entry.filename in seen or stat.S_ISLNK(mode)
                    or (stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR})
                    or expanded > 128 * 1024 * 1024):
                raise ValueError('Unexpected plugin ZIP layout.')
            seen.add(entry.filename)
        required = {f'{PLUGIN}/{name}' for name in ['plugin.json', 'package.json', 'main.py', 'dist/index.js']}
        if not required <= seen:
            raise ValueError('Plugin ZIP is missing required files.')
        for name in ['plugin.json', 'package.json']:
            if archive.getinfo(f'{PLUGIN}/{name}').file_size > 1024 * 1024:
                raise ValueError('Plugin ZIP metadata is too large.')
        plugin = json.loads(archive.read(f'{PLUGIN}/plugin.json'))
        package = json.loads(archive.read(f'{PLUGIN}/package.json'))
        if plugin.get('name') != PLUGIN or package.get('version') != release['version']:
            raise ValueError('Plugin ZIP name/version mismatch.')
        if archive.testzip() is not None:
            raise ValueError('Plugin ZIP contains corrupt members.')


def cached_package(cache, release):
    directory = private_directory(cache / release['version'])
    package = directory / release['asset']
    if package.exists() or package.is_symlink():
        if package.is_symlink():
            raise ValueError('Refusing a symlinked cached package.')
        try:
            validate_package(package, release)
            print(f'Reusing verified DLO {release["version"]} package.', flush=True)
            return package
        except (ValueError, zipfile.BadZipFile):
            print('Cached package is invalid; downloading a replacement.', flush=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, prefix='.download-', delete=False) as stream:
            temporary = Path(stream.name)
            with request(release['url'], timeout=30) as response:
                size = 0
                deadline = time.monotonic() + 60
                while True:
                    chunk = response.read(1024 * 1024)
                    if time.monotonic() > deadline:
                        raise TimeoutError('Plugin download exceeded 60 seconds.')
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > release['size']:
                        raise ValueError('Downloaded plugin exceeds its declared size.')
                    stream.write(chunk)
        validate_package(temporary, release)
        temporary.replace(package)
        return package
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def unique_installation():
    # Decky's native installer selects the first matching folder, which can be
    # different from the loaded copy. Do not leave an older duplicate on restart.
    root = Path.home() / 'homebrew/plugins'
    if not root.is_dir():
        return
    matches = []
    for folder in root.iterdir():
        metadata = folder / 'plugin.json'
        if metadata.is_file():
            try:
                if json.loads(metadata.read_text()).get('name') == PLUGIN:
                    matches.append(folder)
            except (ValueError, OSError):
                continue
    if len(matches) > 1:
        raise RuntimeError('Multiple DLO plugin folders found; keep one installation before enabling auto update.')


def install_code(package, release, installed_version):
    parameters = json.dumps({'name': PLUGIN, 'version': release['version'],
                             'hash': release['sha256'], 'artifact': 'file://' + str(package),
                             'previousVersion': installed_version})
    # No new Decky backend socket: all calls use the frontend's existing router.
    # Suppress only our exact install prompt while automatically confirming it.
    return r'''(async () => {
const p = PARAMETERS;
const backend = window.DeckyBackend, loader = window.DeckyPluginLoader;
if (!backend?.call || !backend?.eventListeners?.get || !backend?.addEventListener ||
    !backend?.removeEventListener || !loader?.importPlugin || !Array.isArray(loader.plugins))
    throw Error('Unsupported Decky frontend APIs.');
if (window.dlorDloAutoUpdateRunning) throw Error('A DLO update is already running.');
window.dlorDloAutoUpdateRunning = true;
const timed = (promise, ms) => {
    let timer;
    return Promise.race([promise, new Promise((_, reject) => {
        timer = setTimeout(() => reject(Error('DLO installer timed out; check Decky before retrying.')), ms);
    })]).finally(() => clearTimeout(timer));
};
const event = 'loader/add_plugin_install_prompt';
const matches = args => args[0] === p.name && args[1] === p.version && args[3] === p.hash;
const original = [...(backend.eventListeners.get(event) || [])];
const wrappers = original.map(handler => (...args) => { if (!matches(args)) return handler(...args); });
let listener, order, nativePromise, nativePending = false, requested = false;
try {
    const before = await timed(backend.call('loader/get_plugins'), 10000);
    const current = before.find(plugin => plugin.name === p.name);
    if (!current || current.disabled) return {status: 'skipped'};
    if (current.version === p.version) return {status: 'current', version: p.version};
    if (current.version !== p.previousVersion) return {status: 'skipped', reason: 'DLO changed during download'};
    order = await timed(backend.call('utilities/settings/get', 'pluginOrder', []), 10000);
    original.forEach(handler => backend.removeEventListener(event, handler));
    wrappers.forEach(handler => backend.addEventListener(event, handler));
    let requestId;
    const confirmation = new Promise((resolve, reject) => {
        listener = (...args) => {
            if (!matches(args) || requestId) return;
            requestId = args[2];
            nativePending = true;
            nativePromise = backend.call('utilities/confirm_plugin_install', requestId);
            nativePromise.then(value => { nativePending = false; resolve(value); },
                               error => { nativePending = false; reject(error); });
        };
        backend.addEventListener(event, listener);
    });
    requested = true;
    await Promise.all([
        timed(backend.call('utilities/install_plugin', p.artifact, p.name, p.version, p.hash, 2), 15000),
        timed(confirmation, 90000),
    ]);
    const after = await timed(backend.call('loader/get_plugins'), 10000);
    const updated = after.find(plugin => plugin.name === p.name && plugin.version === p.version && !plugin.disabled);
    if (!updated) throw Error('DLO installation did not load the expected backend version.');
    // Native import notifications normally handle this; refresh explicitly if
    // the frontend is still old, and wait for any existing reload queue.
    if (!loader.plugins.some(plugin => plugin.name === p.name && plugin.version === p.version))
        await timed(loader.importPlugin(p.name, p.version, updated.load_type, true, 15000), 20000);
    for (let i = 0; i < 150; i++) {
        const frontend = loader.plugins.find(plugin => plugin.name === p.name && plugin.version === p.version);
        if (frontend && typeof frontend.onDismount === 'function')
            return {status: 'updated', version: p.version};
        await new Promise(resolve => setTimeout(resolve, 100));
    }
    throw Error('DLO frontend did not load successfully.');
} finally {
    if (listener) backend.removeEventListener(event, listener);
    wrappers.forEach(handler => backend.removeEventListener(event, handler));
    original.forEach(handler => backend.addEventListener(event, handler));
    const finish = async () => {
        try {
            if (order && requested) await timed(backend.call('utilities/settings/set', 'pluginOrder', order), 10000);
        } finally {
            window.dlorDloAutoUpdateRunning = false;
        }
    };
    if (nativePending) {
        // A timed-out native install can still be running. Keep the frontend
        // guard until it actually settles so another launch cannot reinstall.
        nativePromise.then(finish, finish).catch(error => console.warn('DLO updater cleanup failed:', error));
    } else {
        await finish();
    }
}
})()'''.replace('PARAMETERS', parameters, 1)


def update(cache, frontend, variant='regular'):
    if variant not in ASSETS:
        raise ValueError(f'Unknown DLO update variant: {variant!r}.')
    installed = frontend.evaluate("""(async () => {
        if (!window.DeckyBackend?.call) throw Error('Decky frontend is unavailable.');
        const plugins = await window.DeckyBackend.call('loader/get_plugins');
        return plugins.find(plugin => plugin.name === 'Launch Options') || null;
    })()""")
    if not installed or installed.get('disabled'):
        print('DLO is absent or disabled; skipping.', flush=True)
        return
    current = version(installed['version'])
    release = latest_release(variant)
    selected = version(release['version'])
    current_variant = 'with-store' if installed['version'].endswith('-with-store') else 'regular'
    if selected < current or (selected == current and current_variant == variant):
        print(f'DLO {installed["version"]} is current; no update needed.', flush=True)
        return
    unique_installation()
    package = cached_package(cache, release)
    print(f'Updating only DLO ({variant}): {installed["version"]} -> {release["version"]}.', flush=True)
    result = frontend.evaluate(install_code(package, release, installed['version']))
    if not isinstance(result, dict) or result.get('status') not in {'updated', 'current', 'skipped'}:
        raise RuntimeError('Unexpected result from the DLO installer.')
    print(f'DLO updater result: {result}.', flush=True)


def main():
    variant = os.environ.get('DLO_UPDATE_VARIANT', 'regular')
    if variant not in ASSETS:
        raise ValueError(f'Unknown DLO update variant: {variant!r}.')
    cache = private_directory(Path(os.environ.get(
        'DLO_UPDATE_CACHE_DIR', Path.home() / '.dlor/cache/decky-launch-options')).expanduser())
    lock_path = cache / 'update.lock'
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('Another DLO update is running; skipping.', flush=True)
            return
        frontend = connect_frontend()
        try:
            update(cache, frontend, variant)
        finally:
            frontend.close()


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'Error: DLO auto update failed: {error}', file=sys.stderr, flush=True)
        sys.exit(1)
PYTHON
