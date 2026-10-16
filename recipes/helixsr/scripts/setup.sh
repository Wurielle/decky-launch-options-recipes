#!/usr/bin/env bash
# All setup tools run on the host; the shared runner preserves the game's environment.
unset LD_PRELOAD
if [[ "${STEAM_RUNTIME:-}" == /* ]]; then
    export LD_LIBRARY_PATH="${SYSTEM_LD_LIBRARY_PATH:-}"
    export PATH="${SYSTEM_PATH:-/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin}"
    unset STEAM_RUNTIME
fi
readonly RECIPE_NAME="helixsr"
readonly SCRIPT_NAME="setup"
log_dir="$HOME/.dlor/logs/$RECIPE_NAME/$SCRIPT_NAME"
printf -v timestamp '%(%Y-%m-%dT%H-%M-%S)T' -1
log_file="$log_dir/$timestamp.${EPOCHREALTIME##*.}.$BASHPID.log"
if mkdir -p -- "$log_dir" && command -v tee >/dev/null 2>&1 && : >> "$log_file"; then
    exec > >(tee --output-error=warn -a -- "$log_file") 2>&1
    (
        export LC_ALL=C
        shopt -s nullglob
        logs=()
        for candidate in "$log_dir/"*.log; do
            if [[ -f "$candidate" && ! -L "$candidate" ]]; then logs+=("$candidate"); fi
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
trap 'status=$?; printf "helixsr/setup finished with exit status %s.\n" "$status"; exit "$status"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'printf "Error: helixsr/setup line %s (exit %s)\n" "$LINENO" "$?" >&2' ERR
if [[ "${1:-}" == --help || "${1:-}" == -h ]]; then
    printf 'Usage: setup.sh /path/to/installed/game\nAutomatically prepares the cached HelixSR installation.\n'
    exit 0
fi
python3 -I -B - "$@" <<'PY'
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import shutil
import stat
import zipfile
from pathlib import PurePosixPath
import json
import struct
import tarfile
import posixpath
import sys
import re
from contextlib import contextmanager


@contextmanager
def build_progress():
    """A closeable activity window; missing GUI/progress failures never fail a build."""
    window = None
    text = "Preparing HelixSR on this PC. Downloading tools and building shaders may take several minutes. Your game will continue afterwards."
    try:
        zenity, kdialog = shutil.which("zenity"), shutil.which("kdialog")
        command = ([zenity, "--progress", "--pulsate", "--no-cancel", "--title=HelixSR first-time setup", "--text=" + text]
                   if zenity else [kdialog, "--title", "HelixSR first-time setup", "--msgbox", text, "--ok-label", "Hide progress"] if kdialog else None)
        if command:
            window = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as error:
        print(f"HelixSR progress window unavailable: {error}")
    try:
        yield
    finally:
        if window:
            try:
                if window.poll() is None:
                    window.terminate()
                window.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    window.kill()
                    window.wait(timeout=5)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            if getattr(window, "stdin", None):
                window.stdin.close()

DXC_URL = "https://github.com/microsoft/DirectXShaderCompiler/releases/download/v1.9.2607/dxc_2026_07_29.zip"
DXC_SHA = "a1dfb116ba3eeae6a1582291b53a8e7bf65ad760676bd3194685c8f7367cd241"

PYTHON_URL = "https://github.com/astral-sh/python-build-standalone/releases/download/20261003/cpython-3.12.15%2B20261003-x86_64-unknown-linux-gnu-install_only.tar.gz"
PYTHON_SHA = "f937814031eab4698ca6d07ec606ede1825768f3f3e99af76d9db3900bee03c5"

VERSION = "1.9.0"
DLSS_SHA = "be6e434a94ca32499515eb62ca0e6c274526055d568d0426e4c652dcdfb6ee6e"
WEIGHTS_SIZE = 1903872
WEIGHTS_SHA = "762adfde720035f7ac43910846e0ce6826c239bcd41f863196f77c547ae57153"
DROP_NAMES = ("amd_fidelityfx_dx12.dll", "amd_fidelityfx_upscaler_dx12.dll")
RELEASE_URL = "https://github.com/lonewolf0622/HelixSR/releases/download/v1.9.0/HelixSR-1.9.0.zip"
RELEASE_SHA = "795268f60a1262cd7c8cb01a38f553751cc380fa0cbec63c8f466b6807468be4"
DLSS_URL = "https://raw.githubusercontent.com/NVIDIA/DLSS/v310.7.0/lib/Windows_x86_64/rel/nvngx_dlss.dll"
LICENSE_URL = "https://github.com/NVIDIA/DLSS/blob/v310.7.0/LICENSE.txt"


def source_identity():
    return dict(version=VERSION, release_sha256=RELEASE_SHA, dlss_sha256=DLSS_SHA,
                dlss_url=DLSS_URL, license_url=LICENSE_URL)


def read_json(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def atomic_json(path, value):
    fd, name = tempfile.mkstemp(prefix=".state-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, sort_keys=True)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def ensure_consent(cache):
    """Only a successful GUI acknowledgement grants consent; environment flags do not."""
    identity = source_identity()
    marker = cache / "consent.json"
    if read_json(marker) == identity:
        return
    message = ("HelixSR 1.9.0 first-time setup\n\n"
               "This downloads NVIDIA DLSS 310.7.0 and builds its network locally for your own PC. "
               "Do not share or upload the resulting DLLs. The first build may take several minutes.\n\n"
               "Review NVIDIA's license before accepting:\n" + LICENSE_URL +
               "\n\nBy choosing Accept and build, you accept that license and authorize the download and local build. "
               "Cancel leaves HelixSR disabled; your game can continue.")
    zenity, kdialog = shutil.which("zenity"), shutil.which("kdialog")
    if zenity:
        command = [zenity, "--question", "--title=HelixSR — NVIDIA license", "--width=650",
                   "--no-markup", "--text=" + message, "--ok-label=Accept and build", "--cancel-label=Cancel"]
    elif kdialog:
        command = [kdialog, "--title", "HelixSR — NVIDIA license", "--yesno", message,
                   "--yes-label", "Accept and build", "--no-label", "Cancel"]
    else:
        raise RuntimeError("HelixSR needs Zenity or KDialog for explicit NVIDIA license consent")
    if subprocess.run(command).returncode != 0:
        raise RuntimeError("HelixSR setup cancelled; no NVIDIA download authorized")
    atomic_json(marker, identity)



def validate_output(folder):
    """Validate the upstream embedded payload, not merely the DLL's PE signature."""
    try:
        data = (folder / DROP_NAMES[0]).read_bytes()
        if len(data) < 34 or data[:2] != b"MZ" or data[-32:-24] != b"HXSRNET1":
            raise ValueError("HelixSR DLL has no embedded network")
        weights_size, pak_size, version = struct.unpack("<QQQ", data[-24:])
        start = len(data) - 32 - weights_size - pak_size
        if version != 1 or weights_size != WEIGHTS_SIZE or pak_size < 16 or start < 2:
            raise ValueError("Invalid HelixSR network footer bounds")
        weights = data[start:start + weights_size]
        if hashlib.sha256(weights).hexdigest() != WEIGHTS_SHA:
            raise ValueError("Invalid HelixSR network weights")
        pak = data[start + weights_size:-32]
        magic, pak_version, count = struct.unpack("<8sII", pak[:16])
        table_end = 16 + count * 40
        if magic != b"HXSRKPAK" or pak_version != 2 or not count or table_end > len(pak):
            raise ValueError("Invalid HelixSR shader archive")
        names, ranges = set(), []
        for index in range(count):
            name, offset, length = struct.unpack_from("<32sII", pak, 16 + index * 40)
            name = name.rstrip(b"\0")
            if not name or name in names or not length or offset < table_end or offset + length > len(pak):
                raise ValueError("Invalid HelixSR shader entry")
            names.add(name)
            ranges.append((offset, offset + length))
        ranges.sort()
        if any(previous[1] > following[0] for previous, following in zip(ranges, ranges[1:])):
            raise ValueError("Overlapping HelixSR shaders")
        metadata = json.loads((folder / "helixsr_setup.json").read_text())
        if metadata.get("source_sha256") != DLSS_SHA or metadata.get("weights_sha256") != WEIGHTS_SHA:
            raise ValueError("HelixSR metadata does not match pinned source")
        for name in DROP_NAMES:
            if (folder / "fsr3-drop-in" / name).read_bytes() != data:
                raise ValueError("HelixSR drop-in differs from main DLL")
        return hashlib.sha256(data).hexdigest()
    except (OSError, struct.error, json.JSONDecodeError, AttributeError) as error:
        raise ValueError(f"Incomplete HelixSR output: {error}") from error


def archive_parts(name):
    name = name.replace("\\", "/")
    parts = PurePosixPath(name).parts
    if not parts or name.startswith("/") or ".." in parts or ":" in name:
        raise ValueError(f"Unsafe archive member: {name}")
    return parts


def safe_extract(archive, destination):
    """Extract into a fresh directory. TAR file links become regular files, never links."""
    destination.mkdir(parents=True, exist_ok=False)
    if not zipfile.is_zipfile(archive):
        with tarfile.open(archive, "r:*") as stream:
            entries = {}
            for entry in stream.getmembers():
                name = "/".join(archive_parts(entry.name))
                if name in entries or not (entry.isfile() or entry.isdir() or entry.issym() or entry.islnk()):
                    raise ValueError(f"Unsafe TAR member: {name}")
                entries[name] = entry
            def regular(name, seen):
                if name in seen or name not in entries:
                    raise ValueError("Cyclic or missing TAR link target")
                entry = entries[name]
                if entry.isfile():
                    return entry
                if not (entry.issym() or entry.islnk()):
                    raise ValueError("TAR links may only target regular files")
                target = entry.linkname.replace("\\", "/")
                if target.startswith("/") or ":" in target:
                    raise ValueError("Absolute TAR link target")
                target = posixpath.normpath(posixpath.join(posixpath.dirname(name), target) if entry.issym() else target)
                archive_parts(target)
                return regular(target, seen | {name})
            resolved = [(name, entry, None if entry.isdir() else regular(name, set())) for name, entry in entries.items()]
            for name, entry, source_entry in resolved:
                target = destination.joinpath(*archive_parts(name))
                if entry.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with stream.extractfile(source_entry) as source, target.open("xb") as output:
                        shutil.copyfileobj(source, output)
                    target.chmod(0o755 if source_entry.mode & 0o111 else 0o644)
        return
    with zipfile.ZipFile(archive) as stream:
        members = []
        for entry in stream.infolist():
            name = entry.filename.replace("\\", "/")
            parts = PurePosixPath(name).parts
            mode = entry.external_attr >> 16
            if (not parts or name.startswith("/") or ".." in parts or ":" in name
                    or stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR))):
                raise ValueError(f"Unsafe archive member: {name}")
            members.append((entry, destination.joinpath(*parts)))
        for entry, target in members:
            if entry.filename.replace("\\", "/").endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with stream.open(entry) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
                target.chmod(0o755 if (entry.external_attr >> 16) & 0o111 else 0o644)


def download_file(url, destination):
    subprocess.run(["curl", "-fL", "--proto", "=https", "--proto-redir", "=https",
                    "--connect-timeout", "20", "--max-time", "600", "--output", str(destination), url], check=True)


def cached_download(destination, url, digest):
    def valid(path):
        return path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest
    if valid(destination):
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".download-", dir=destination.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        download_file(url, temporary)
        if not valid(temporary):
            raise ValueError(f"Checksum mismatch for {destination.name}")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def python_compatible(python):
    try:
        return subprocess.run([str(python), "-I", "-B", "-c",
                               "import sys,numpy as n; assert sys.version_info >= (3,10); "
                               "assert tuple(map(int,n.__version__.split('.')[:2])) >= (1,24); "
                               "assert n.frombuffer(b'\\x00\\x00\\x80\\x3f', dtype='<f4')[0] == 1"],
                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def python_state(cache):
    # Bytecode is disposable; validate executable, source and shared-library bytes before reusing tools.
    files = {str(path.relative_to(cache / "python")): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in (cache / "python").rglob("*")
             if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"}
    return dict(archive_sha256=PYTHON_SHA, numpy="2.3.3", files=files)


def purge_python_bytecode(root):
    # -B prevents writes, not reads. Discard unvalidated bytecode only in our private runtime.
    for path in sorted(root.rglob("*"), reverse=True):
        if path.name == "__pycache__" and path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        elif path.name == "__pycache__" or path.suffix == ".pyc":
            path.unlink(missing_ok=True)


def ensure_python(cache):
    host = Path(sys.executable)
    if python_compatible(host):
        return host
    python = cache / "python/bin/python3"
    marker = cache / "python-ready.json"
    if python.is_file() and read_json(marker) == python_state(cache):
        purge_python_bytecode(cache / "python")
        if python_compatible(python):
            return python
    marker.unlink(missing_ok=True)
    archive = cached_download(cache / "downloads/python.tar.gz", PYTHON_URL, PYTHON_SHA)
    stage = Path(tempfile.mkdtemp(prefix=".python-", dir=cache))
    try:
        safe_extract(archive, stage / "unpacked")
        if not (stage / "unpacked/python/bin/python3").is_file():
            raise ValueError("Portable Python archive is incomplete")
        if (cache / "python").exists():
            shutil.rmtree(cache / "python")
        os.replace(stage / "unpacked/python", cache / "python")
    finally:
        shutil.rmtree(stage)
    purge_python_bytecode(cache / "python")
    subprocess.run([str(python), "-I", "-B", "-m", "pip", "--isolated", "install", "--no-input", "--no-compile",
                    "--disable-pip-version-check", "--only-binary=:all:", "--cache-dir", str(cache / "pip"),
                    "--index-url", "https://pypi.org/simple", "numpy==2.3.3"],
                   stdin=subprocess.DEVNULL, check=True)
    purge_python_bytecode(cache / "python")
    if not python_compatible(python):
        raise RuntimeError("Portable Python/numpy failed its compatibility check")
    atomic_json(marker, python_state(cache))
    return python


def find_wine():
    def candidate(root):
        for relative in ("files/bin/wine64", "files/bin/wine", "dist/bin/wine64", "dist/bin/wine", "bin/wine64", "bin/wine"):
            path = root / relative
            if path.is_file() and os.access(path, os.X_OK):
                return path.resolve()
        return None
    for value in os.environ.get("STEAM_COMPAT_TOOL_PATHS", "").split(":"):
        if value:
            found = candidate(Path(value))
            if found:
                return found
    home = Path.home()
    roots = [home / ".steam/root", home / ".steam/steam", home / ".local/share/Steam",
             home / ".var/app/com.valvesoftware.Steam/data/Steam"]
    if os.environ.get("STEAM_COMPAT_CLIENT_INSTALL_PATH"):
        roots.insert(0, Path(os.environ["STEAM_COMPAT_CLIENT_INSTALL_PATH"]))
    for root in list(roots):
        for vdf in (root / "steamapps/libraryfolders.vdf", root / "config/libraryfolders.vdf"):
            if vdf.is_file():
                roots.extend(Path(value.replace("\\\\", "\\")) for value in re.findall(r'"path"\s*"([^"]+)"', vdf.read_text()))
    seen = set()
    for root in roots:
        if root.resolve() in seen:
            continue
        seen.add(root.resolve())
        for directory in (root / "steamapps/common", root / "compatibilitytools.d"):
            for tool in sorted(directory.glob("*"), reverse=True):
                found = candidate(tool)
                if found:
                    return found
    fallback = shutil.which("wine64") or shutil.which("wine")
    if fallback:
        return Path(fallback).resolve()
    raise RuntimeError("No Proton or Wine compiler runtime found in Steam libraries")


def ensure_tools(cache):
    python = ensure_python(cache)
    wine = find_wine()
    archive = cached_download(cache / "downloads/dxc.zip", DXC_URL, DXC_SHA)
    stage = Path(tempfile.mkdtemp(prefix=".dxc-", dir=cache))
    try:
        safe_extract(archive, stage / "unpacked")
        for name in ("dxc.exe", "dxcompiler.dll", "dxil.dll"):
            if not (stage / "unpacked/bin/x64" / name).is_file():
                raise ValueError("DXC archive is missing its x64 compiler dependencies")
        if (cache / "dxc").exists():
            shutil.rmtree(cache / "dxc")
        os.replace(stage / "unpacked", cache / "dxc")
    finally:
        shutil.rmtree(stage)
    wrapper = cache / "dxc-wrapper"
    # Direct Wine, never Proton's game launcher or the game's prefix.
    wrapper.write_text("#!/usr/bin/env -S python3 -I -B\nimport os,sys\n"
                       "env = os.environ.copy()\n"
                       "for key in ('WINESERVER','WINELOADER','WINEDLLPATH'): env.pop(key, None)\n"
                       f"env.update(WINEPREFIX={str(cache / 'wineprefix')!r}, WINEDEBUG='-all', WINEARCH='win64', WINEDLLOVERRIDES='mscoree,mshtml=')\n"
                       "def windows(arg): return 'Z:' + arg.replace('/', '\\\\') if arg.startswith('/') else arg\n"
                       f"os.execve({str(wine)!r}, [{str(wine)!r}, windows({str(cache / 'dxc/bin/x64/dxc.exe')!r})] + [windows(arg) for arg in sys.argv[1:]], env)\n")
    wrapper.chmod(0o700)
    return python, wrapper


def provision(cache):
    override = os.environ.get("HELIXSR_DIR")
    if override:
        output = Path(override).expanduser().resolve()
        validate_output(output)
        return output
    output = cache / ("HelixSR-" + VERSION)
    marker = cache / "ready.json"
    ready = read_json(marker)
    try:
        digest = validate_output(output)
        if ready == dict(source_identity(), dll_sha256=digest):
            return output
    except ValueError:
        pass
    marker.unlink(missing_ok=True)
    ensure_consent(cache)
    with build_progress():
        return build_release(cache, output, marker)


def build_release(cache, output, marker):
    archive = cached_download(cache / "downloads" / ("HelixSR-" + VERSION + ".zip"), RELEASE_URL, RELEASE_SHA)
    stage = Path(tempfile.mkdtemp(prefix=".release-", dir=cache))
    try:
        safe_extract(archive, stage / "unpacked")
        release = stage / "unpacked" / ("HelixSR-" + VERSION)
        if not (release / "setup/helixsr_setup.py").is_file() or not (release / DROP_NAMES[0]).is_file():
            raise ValueError("Official release is incomplete")
        if output.exists():
            shutil.rmtree(output)
        os.replace(release, output)
    finally:
        shutil.rmtree(stage)
    synth = output / "setup/lib/model/launch_synth"
    if synth.is_file():
        synth.chmod(0o755)
    python, wrapper = ensure_tools(cache)
    dlss = cached_download(cache / "downloads/nvngx_dlss.dll", DLSS_URL, DLSS_SHA)
    # Upstream spawns Python children without -I; sanitize their inherited environment too.
    env = os.environ.copy()
    for key in ("PYTHONHOME", "PYTHONPATH"):
        env.pop(key, None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    subprocess.run([str(python), "-I", "-B", str(output / "setup/helixsr_setup.py"), str(output),
                    "--yes", "--no-fg", "--dxc", str(wrapper), "--dlss", str(dlss)],
                   check=True, cwd=output, env=env, stdin=subprocess.DEVNULL)
    digest = validate_output(output)
    atomic_json(marker, dict(source_identity(), dll_sha256=digest))
    return output


def run_setup():
    # HELIXSR_CACHE_DIR is a base directory; every dependency and output is version-local.
    cache = (Path(os.environ.get("HELIXSR_CACHE_DIR", str(Path.home() / ".dlor/cache/helixsr"))) / VERSION).expanduser().resolve()
    runtime = os.environ.get("DLOR_HELIXSR_RUNTIME_FILE")
    success = Path(runtime + ".setup") if runtime else None
    if success:
        success.unlink(missing_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    cache.chmod(0o700)
    (cache / "tmp").mkdir(exist_ok=True)
    os.environ["TMPDIR"] = str(cache / "tmp")
    import fcntl
    with (cache / "setup.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        output = provision(cache)
        if success:
            success.write_text("ready")
        return output


if __name__ == "__main__":
    try:
        import sys
        runtime = os.environ.get("DLOR_HELIXSR_RUNTIME_FILE")
        if runtime:
            Path(runtime + ".setup").unlink(missing_ok=True)
        if len(sys.argv) != 2 or not sys.argv[1]:
            raise ValueError("Usage: setup.sh /path/to/installed/game")
        target = Path(sys.argv[1]).resolve(strict=True)
        if not target.is_dir():
            raise ValueError(f"Game install path is not a directory: {target}")
        run_setup()
    except Exception as error:
        print(f"HelixSR setup failed: {error}", file=__import__("sys").stderr)
        raise SystemExit(1)
PY
