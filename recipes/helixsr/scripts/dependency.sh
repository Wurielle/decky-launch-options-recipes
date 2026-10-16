#!/usr/bin/env bash
# Host-only helper: never leak Steam's injected libraries into download/tools.
unset LD_PRELOAD
if [[ "${STEAM_RUNTIME:-}" == /* ]]; then
    export LD_LIBRARY_PATH="${SYSTEM_LD_LIBRARY_PATH:-}"
    export PATH="${SYSTEM_PATH:-/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin}"
    unset STEAM_RUNTIME
fi
readonly RECIPE_NAME="helixsr"
readonly SCRIPT_NAME="dependency"
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
trap 'status=$?; printf "helixsr/dependency finished with exit status %s.\n" "$status"; exit "$status"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'printf "Error: helixsr/dependency line %s (exit %s)\n" "$LINENO" "$?" >&2' ERR
if [[ "${1:-}" == --help || "${1:-}" == -h ]]; then
    printf 'Usage: dependency.sh /path/to/installed/game\nSet DLOR_HELIXSR_ACTION=on or off.\n'
    exit 0
fi
# The runner fetches only this file; keep all Python embedded, not in a sibling.
python3 - "$@" <<'PY'
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import platform

RELEASE = "v0.9.4"
ASSET = "Optiscaler_0.9.4-final.20260718._MM.7z"
URL = "https://github.com/optiscaler/OptiScaler/releases/download/" + RELEASE + "/" + ASSET
DIGEST = "575cb4df866116093df75af607e37fd70e10f5163e0f23fd5c804142e80ef0ad"
PROXIES = ("dxgi", "winmm", "version")


def fail(message):
    raise ValueError(message)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write(path, data):
    fd, name = tempfile.mkstemp(prefix=".helixsr-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_dir(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def save(path, state):
    atomic_write(path, (json.dumps(state, indent=2) + "\n").encode())


def download(destination, url=URL, expected=DIGEST):
    if destination.is_file() and not destination.is_symlink() and digest(destination) == expected:
        return
    fd, name = tempfile.mkstemp(prefix=".download-", dir=destination.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        subprocess.run(["curl", "-fL", "--proto", "=https", "--proto-redir", "=https",
                        "--connect-timeout", "20", "--max-time", "600", "--output", str(temporary), url], check=True)
        if digest(temporary) != expected:
            fail("OptiScaler archive checksum mismatch")
        os.replace(temporary, destination)
        sync_dir(destination.parent)
    finally:
        temporary.unlink(missing_ok=True)


def validate_entries(entries):
    names = set()
    total = 0
    if not entries or len(entries) > 4096:
        fail("Invalid OptiScaler archive entry count")
    for entry in entries:
        name = entry["name"]
        parts = name.split("/")
        if (not name or any(part in ("", ".", "..") or part.endswith((" ", ".")) for part in parts)
                or any(ord(char) < 32 or char in "\\\\:" for char in name)
                or entry.get("link") or name.casefold() in names):
            fail("Unsafe or duplicate OptiScaler archive entry")
        names.add(name.casefold())
        total += int(entry["size"])
        if total > 2 * 1024 ** 3 or int(entry["size"]) < 0:
            fail("OptiScaler archive exceeds extraction limits")
    for required in ("OptiScaler.dll", "OptiScaler.ini"):
        if not any(entry["name"] == required and not entry.get("directory") and int(entry["size"]) > 0 for entry in entries):
            fail("OptiScaler archive is missing its root DLL/config")


PY7ZR_WORKER = r'''
import json, stat, sys
import py7zr
assert py7zr.__version__ == "1.0.0", "Unexpected py7zr version"
if sys.argv[-1] != "probe":
    with py7zr.SevenZipFile(sys.argv[1]) as archive:
        if sys.argv[-1] == "list":
            print(json.dumps([dict(name=f.filename, size=f.uncompressed,
                                  directory=f.is_directory,
                                  link=f.is_symlink or f.is_junction or f.is_socket
                                  or f.st_fmt not in (None, 0, stat.S_IFREG, stat.S_IFDIR))
                              for f in archive.files]))
        else:
            archive.extractall(sys.argv[2])
'''


def extract_py7zr(archive, destination):
    base = Path(os.environ.get("HELIXSR_CACHE_DIR", str(Path.home() / ".dlor/cache/helixsr"))).expanduser().resolve()
    prepared = base / "1.9.0/python/bin/python3"
    python = str(prepared) if prepared.is_file() else sys.executable
    identity = hashlib.sha256(python.encode()).hexdigest()[:12]
    target = archive.parent / ("py7zr-1.0.0-" + identity)
    environment = {key: value for key, value in os.environ.items() if not key.startswith("PYTHON")}
    environment.update(PYTHONPATH=str(target), PYTHONNOUSERSITE="1")
    command = [python, "-S", "-c", PY7ZR_WORKER]
    probe = subprocess.run([*command, "probe"], env=environment, capture_output=True, text=True)
    if probe.returncode:
        with tempfile.TemporaryDirectory(prefix=".py7zr-", dir=archive.parent) as staging:
            site = Path(staging) / "site"
            subprocess.run([python, "-m", "pip", "install", "--disable-pip-version-check", "--only-binary=:all:",
                            "--cache-dir", str(base / "pip"), "--target", str(site), "py7zr==1.0.0"],
                           check=True, env={key: value for key, value in environment.items() if key != "PYTHONPATH"})
            if target.exists():
                shutil.rmtree(target)
            os.replace(site, target)
            sync_dir(target.parent)
    listing = subprocess.run([*command, str(archive), "list"], env=environment,
                             check=True, capture_output=True, text=True)
    entries = json.loads(listing.stdout)
    validate_entries(entries)
    subprocess.run([*command, str(archive), str(destination), "extract"], env=environment,
                   check=True, capture_output=True, text=True)
    validate_extracted(entries, destination)


def validate_extracted(entries, destination):
    for path in destination.rglob("*"):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            fail("Unsafe extracted dependency entry")
    for entry in entries:
        if not entry["directory"]:
            path = destination / entry["name"]
            if not path.is_file() or path.stat().st_size != int(entry["size"]):
                fail("Incomplete OptiScaler extraction")


def portable_7zip(cache):
    # Official OptiScaler releases contain BCJ2, unsupported even by py7zr 1.0.
    # Keep an official checksum-pinned console extractor private, not an installer.
    if platform.machine().lower() not in ("x86_64", "amd64"):
        fail("BCJ2 extraction needs host 7-Zip on this architecture")
    tool_dir = cache / "7zip-26.04"
    tool = tool_dir / "7zz"
    tool_digest = "d1bc79f00e9815b24048ab167690bdd1dbc387de7dbc47e8d75d68689e49cf4f"
    if tool.is_file() and not tool.is_symlink() and digest(tool) == tool_digest:
        return str(tool)
    archive = cache / "7z2604-linux-x64.tar.xz"
    download(archive, "https://github.com/ip7z/7zip/releases/download/26.04/7z2604-linux-x64.tar.xz",
             "fc0327ba27e89bd086cf426dff17d77de582953cdbbc10a6576540a06853ffcd")
    with tempfile.TemporaryDirectory(prefix=".7zip-", dir=cache) as staging:
        source = Path(staging)
        with tarfile.open(archive) as bundle:
            members = bundle.getmembers()
            for member in members:
                name = member.name
                if (not name or PurePosixPath(name).is_absolute() or ".." in name.split("/")
                        or any(ord(char) < 32 or char in "\\\\:" for char in name)
                        or not (member.isfile() or member.isdir())):
                    fail("Unsafe console extractor archive")
            bundle.extractall(source, filter="data")
        if digest(source / "7zz") != tool_digest:
            fail("Console extractor checksum mismatch")
        (source / "7zz").chmod(0o700)
        if tool_dir.exists():
            shutil.rmtree(tool_dir)
        # TemporaryDirectory's context tolerates a renamed directory.
        os.replace(source, tool_dir)
        sync_dir(cache)
    return str(tool)


def extract(archive, destination):
    tool = shutil.which("7zz") or shutil.which("7z")
    if not tool:
        try:
            return extract_py7zr(archive, destination)
        except subprocess.CalledProcessError:
            # Binary wheels may be absent for a new host Python, or decoding may
            # require BCJ2. Neither case warrants installing system packages.
            print("Private py7zr unavailable for this archive; using pinned 7-Zip.")
            shutil.rmtree(destination)
            destination.mkdir()
            tool = portable_7zip(archive.parent)
    listing = subprocess.run([tool, "l", "-slt", "-sccUTF-8", str(archive)],
                             check=True, capture_output=True, text=True).stdout
    if "\n----------\n" not in listing:
        fail("Unrecognized 7-Zip archive listing")
    entries = []
    for block in listing.split("\n----------\n", 1)[1].strip().split("\n\n"):
        fields = dict(line.split(" = ", 1) for line in block.splitlines() if " = " in line)
        if "Path" not in fields or "Size" not in fields:
            fail("Incomplete 7-Zip archive listing")
        attrs = fields.get("Attributes", "")
        entries.append(dict(name=fields["Path"], size=int(fields["Size"]),
                            directory=attrs.startswith("D") or fields.get("Folder") == "+",
                            link=any("link" in key.casefold() for key in fields)
                            or bool(re.search(r"(?:^| )[bclps][rwx-]{9}", attrs))))
    validate_entries(entries)
    subprocess.run([tool, "x", "-y", "-o" + str(destination), str(archive)], check=True)
    validate_extracted(entries, destination)


def argument_executable(item, game):
    if not isinstance(item, str) or not item.lower().endswith(".exe"):
        return None
    windows = re.match(r"^([a-zA-Z]):[/\\\\](.*)$", item)
    if windows:
        compat = os.environ.get("STEAM_COMPAT_DATA_PATH")
        prefix = Path(compat) / "pfx" if compat else Path(os.environ.get("WINEPREFIX", "/nonexistent"))
        drive = prefix / "dosdevices" / (windows[1].lower() + ":")
        if not drive.exists():
            return None
        root = drive.resolve()
        item = str(child_path(root, windows[2].replace("\\", "/")))
    candidate = Path(item)
    if not candidate.is_absolute():
        candidate = game / candidate
    if not candidate.is_relative_to(game):
        return None
    candidate = child_path(game, candidate.relative_to(game).as_posix())
    return candidate if candidate.is_file() else None


def game_files(game):
    for directory, dirs, files in os.walk(game, followlinks=False):
        dirs[:] = sorted(name for name in dirs if not (Path(directory) / name).is_symlink())
        for name in sorted(files):
            path = Path(directory) / name
            if not path.is_symlink() and path.is_file():
                yield path


def credible_executable(path):
    lowered = path.name.casefold()
    excluded = ("crash", "report", "unins", "setup", "install", "redist", "launcher", "anticheat", "benchmark")
    return lowered.endswith(".exe") and not any(word in lowered for word in excluded)


def target_directory(game):
    args = json.loads(os.environ.get("DLOR_HELIXSR_ARGS", "[]"))
    if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
        fail("DLOR_HELIXSR_ARGS must be a JSON array of argument strings")
    direct = list(dict.fromkeys(path for item in args if (path := argument_executable(item, game))))
    executables = [path for path in game_files(game) if credible_executable(path)]
    shipping = [path for path in executables if path.name.casefold().endswith("-shipping.exe")
                and "binaries" in [part.casefold() for part in path.relative_to(game).parts]]
    if len(direct) == 1 and credible_executable(direct[0]) and (direct[0].parent != game or not shipping):
        candidates = direct
    elif shipping:
        candidates = shipping
    else:
        candidates = [path for path in direct if credible_executable(path)] or executables
    if not candidates:
        fail("No credible rendering executable found in this game")
    if len(candidates) > 1:
        labels = {path.relative_to(game).as_posix(): path for path in candidates}
        if any("\n" in label or "\r" in label for label in labels):
            fail("Executable paths cannot contain line breaks")
        if tool := shutil.which("zenity"):
            command = [tool, "--list", "--title=HelixSR: select game executable", "--text=Select the rendering executable, not a launcher.",
                       "--column=Executable", "--width=850", "--height=420", *labels]
        elif tool := shutil.which("kdialog"):
            command = [tool, "--title", "HelixSR", "--menu", "Select the rendering executable, not a launcher."]
            for label in labels:
                command.extend([label, label])
        else:
            fail("Several rendering executables found, but no Zenity/KDialog picker is available")
        result = subprocess.run(command, capture_output=True, text=True, timeout=300)
        selection = result.stdout.rstrip("\n")
        if result.returncode or selection not in labels:
            fail("Executable selection cancelled or invalid; no game files changed")
        return labels[selection].parent
    return candidates[0].parent


def child_path(root, relative):
    # Wine is case-insensitive even when the underlying Linux filesystem is not.
    current = root
    for part in PurePosixPath(relative).parts:
        if part in (".", "..") or part.startswith("/"):
            fail("Unsafe installation path")
        matches = [path for path in current.iterdir() if path.name.casefold() == part.casefold()] if current.is_dir() else []
        if len(matches) > 1:
            fail("Ambiguous case-insensitive game path")
        current = matches[0] if matches else current / part
        if current.is_symlink():
            fail("Refusing symlink in dependency path")
        if not current.resolve().is_relative_to(root):
            fail("Dependency path escaped target directory")
    return current


def install_new(path, data):
    # A no-clobber link commits a complete file without replacing a raced mod.
    fd, name = tempfile.mkstemp(prefix=".helixsr-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        sync_dir(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def load_state(manifest, game):
    if not manifest.exists():
        return None
    if manifest.is_symlink():
        fail("Refusing symlink dependency state")
    state = json.loads(manifest.read_text())
    if (not isinstance(state, dict) or state.get("version") != 1
            or state.get("game") != str(game) or state.get("proxy") not in PROXIES
            or not isinstance(state.get("target"), str) or not isinstance(state.get("files"), dict)):
        fail("Unrecognized OptiScaler dependency state")
    target = Path(state["target"])
    if not target.is_absolute() or not target.resolve().is_relative_to(game) or target.resolve() != target:
        fail("Unsafe dependency target in state")
    for name, value in state["files"].items():
        if not name or PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts or "\\" in name:
            fail("Unsafe owned file in state")
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            fail("Invalid owned hash in state")
    return state


def deactivate(game, manifest):
    state = load_state(manifest, game)
    if not state:
        print("No HelixSR-owned OptiScaler dependency to remove.")
        return
    config_state = manifest.with_name(manifest.name.replace(".dependency.json", ".json"))
    if config_state.exists():
        fail("HelixSR settings restoration is still pending; retaining the dependency")
    if os.environ.get("DLOR_OPTISCALER_REQUESTED") == "1":
        manifest.unlink()
        sync_dir(manifest.parent)
        print("Retained OptiScaler for its independent toggle; released HelixSR file ownership.")
        return
    target = Path(state["target"])
    for name, expected in state["files"].items():
        try:
            path = child_path(target, name)
        except ValueError:
            print(f"Keeping redirected dependency file: {name}")
            continue
        if path.is_file() and digest(path) == expected:
            path.unlink()
            sync_dir(path.parent)
        elif path.exists():
            print(f"Keeping changed dependency file: {name}")
    manifest.unlink()
    sync_dir(manifest.parent)
    print("Removed unchanged HelixSR-owned OptiScaler files.")


def verified_existing(target):
    ini = child_path(target, "OptiScaler.ini")
    if not ini.is_file() or not ini.stat().st_size:
        return None
    sources = [child_path(target, "OptiScaler.dll"), Path.home() / "fgmod/OptiScaler.dll"]
    known = {digest(path) for path in sources if path.is_file() and not path.is_symlink() and path.stat().st_size}
    matches = [name for name in PROXIES if (path := child_path(target, name + ".dll")).is_file()
               and path.stat().st_size and digest(path) in known]
    if len(matches) > 1:
        fail("Multiple verified OptiScaler proxies; refusing ambiguous Wine override")
    return (matches[0], ini) if matches else None


def publish(runtime, target, proxy, config):
    verified = verified_existing(target)
    if not verified or verified != (proxy, config):
        fail("OptiScaler proxy/config verification failed before runtime publication")
    atomic_write(Path(str(runtime) + ".config"), (str(config) + "\n").encode())
    atomic_write(runtime, (proxy + "\n").encode())


def activate(game, manifest):
    # Select the renderer before considering reuse; a launcher install or stale
    # journal must never redirect this launch's configuration and Wine override.
    target = target_directory(game)
    previous = load_state(manifest, game)
    if previous and Path(previous["target"]) != target:
        fail("Rendering executable directory changed; disable HelixSR to restore and remove its previous dependency before enabling again")
    if any(ord(char) < 32 for char in str(target)):
        fail("Dependency directory paths cannot contain control characters")
    runtime = Path(os.environ["DLOR_HELIXSR_RUNTIME_FILE"])
    existing = verified_existing(target)
    if existing and (not previous or previous.get("complete")):
        publish(runtime, target, *existing)
        print("Reusing verified OptiScaler dependency; existing ownership is unchanged.")
        return
    base = Path(os.environ.get("HELIXSR_CACHE_DIR", str(Path.home() / ".dlor/cache/helixsr"))).expanduser().resolve()
    cache = base / "optiscaler" / RELEASE
    cache.mkdir(parents=True, exist_ok=True)
    with (cache / ".lock").open("a") as cache_lock:
        fcntl.flock(cache_lock, fcntl.LOCK_EX)
        install_release(game, manifest, previous, target, runtime, cache)


def install_release(game, manifest, previous, target, runtime, cache):
    archive = cache / ASSET
    download(archive)
    with tempfile.TemporaryDirectory(prefix=".extract-", dir=cache) as staging:
        source = Path(staging)
        extract(archive, source)
        proxy = previous["proxy"] if previous else next((name for name in PROXIES if not child_path(target, name + ".dll").exists()), None)
        if not proxy:
            fail("No unused OptiScaler proxy filename")
        files = {str(path.relative_to(source)): path for path in source.rglob("*") if path.is_file()
                 and path.suffix.lower() not in (".sh", ".bat")}
        files[proxy + ".dll"] = source / "OptiScaler.dll"
        state = previous or dict(version=1, game=str(game), target=str(target), proxy=proxy,
                                 config=str(child_path(target, "OptiScaler.ini")), files={})
        state["complete"] = False
        plan = []
        for name, path in files.items():
            destination = child_path(target, name)
            expected = digest(path)
            if destination.exists():
                if not destination.is_file() or digest(destination) != expected:
                    fail(f"Refusing existing dependency file: {destination}")
                continue  # Identical files are borrowed, never acquired for removal.
            state["files"][str(destination.relative_to(target))] = expected
            plan.append((destination, path))
        save(manifest, state)
        for destination, path in plan:
            directory = target
            for part in destination.parent.relative_to(target).parts:
                directory = directory / part
                directory.mkdir(exist_ok=True)
                sync_dir(directory.parent)
            install_new(destination, path.read_bytes())
        release_dir = cache / "release"
        if release_dir.exists():
            shutil.rmtree(release_dir)
        os.replace(source, release_dir)
        sync_dir(cache)
        state["complete"] = True
        save(manifest, state)
        # Publish the strict override last, after files, journal and cache commit.
        publish(runtime, target, proxy, Path(state["config"]))
    print("OptiScaler dependency installed; game compatibility is not verified.")


def report_error(message):
    log = os.environ.get("DLOR_HELIXSR_DEPENDENCY_LOG", "~/.dlor/logs/helixsr/dependency/")
    text = "HelixSR could not prepare OptiScaler.\n" + message + "\nLog: " + log
    try:
        if tool := shutil.which("zenity"):
            subprocess.run([tool, "--error", "--no-markup", "--title=HelixSR", "--text=" + text],
                           timeout=20, capture_output=True)
        elif tool := shutil.which("kdialog"):
            subprocess.run([tool, "--title", "HelixSR", "--error", text], timeout=20, capture_output=True)
    except (OSError, subprocess.SubprocessError):
        pass  # Desktop reporting must never conceal the helper's original error.


def prepare_runtime():
    runtime = Path(os.environ["DLOR_HELIXSR_RUNTIME_FILE"])
    if not runtime.is_absolute() or runtime.parent.resolve() != runtime.parent or any(char in str(runtime) for char in "\r\n"):
        fail("Runtime output must be an absolute private path without symlink parents")
    output = Path(str(runtime) + ".config")
    for path in (runtime, output):
        if path == output and not os.path.lexists(path):
            continue
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) & 0o077):
            fail("Runtime output must be a private owned regular file")
    atomic_write(runtime, b"")
    output.unlink(missing_ok=True)
    sync_dir(runtime.parent)


try:
    if len(sys.argv) != 2:
        fail("Usage: dependency.sh /path/to/installed/game")
    game = Path(sys.argv[1]).resolve(strict=True)
    if not game.is_dir():
        fail("Game path must be a directory")
    action = os.environ.get("DLOR_HELIXSR_ACTION", "on")
    if action not in ("on", "off"):
        fail("DLOR_HELIXSR_ACTION must be on or off")
    if action == "on":
        prepare_runtime()
    identity = hashlib.sha256(str(game).encode()).hexdigest()
    state_dir = Path.home() / ".dlor/state/helixsr"
    for directory in (state_dir.parent.parent, state_dir.parent, state_dir):
        if directory.is_symlink():
            fail("Refusing symlink in HelixSR state directory")
        directory.mkdir(exist_ok=True)
        sync_dir(directory.parent)
    with (state_dir / (identity + ".lock")).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        manifest = state_dir / (identity + ".dependency.json")
        if action == "off":
            deactivate(game, manifest)
        else:
            activate(game, manifest)
except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
    print(f"Error: {error}", file=sys.stderr)
    report_error(str(error))
    sys.exit(1)
PY
