#!/usr/bin/env bash
# Run host tools outside Steam's library environment; never change the game environment.
unset LD_PRELOAD
if [[ "${STEAM_RUNTIME:-}" == /* ]]; then
    export LD_LIBRARY_PATH="${SYSTEM_LD_LIBRARY_PATH:-}"
    export PATH="${SYSTEM_PATH:-/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin}"
    unset STEAM_RUNTIME
fi
readonly RECIPE_NAME="helixsr"
readonly SCRIPT_NAME="configure"
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
trap 'status=$?; printf "helixsr/configure finished with exit status %s.\n" "$status"; exit "$status"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'printf "Error: helixsr/configure line %s (exit %s)\n" "$LINENO" "$?" >&2' ERR

# Keep the configurator self-contained: the shared runner downloads only this file.
# No upstream script is modified or executed, and no DLL or model is downloaded/copied.
if [[ "${1:-}" == --help || "${1:-}" == -h ]]; then
    printf 'Usage: configure.sh /path/to/installed/game\nSet DLOR_HELIXSR_ACTION=on or off.\n'
    exit 0
fi
python3 - "$@" <<'PY'
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

SETTINGS = [("Upscalers", "Dx12Upscaler"), ("Libraries", "FfxDx12Path"),
            ("Libraries", "FfxDx12SRPath")]


def fail(message):
    raise ValueError(message)


def fsync_directory(path):
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
        if path.exists():
            temporary.chmod(stat.S_IMODE(path.stat().st_mode))
        os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def field(lines, section, key, optional=False):
    current = None
    matches = []
    for index, line in enumerate(lines):
        header = re.match(r"\s*\[([^\]]+)\]", line.lstrip("\ufeff"))
        if header:
            current = header[1].strip().casefold()
        elif current == section.casefold() and "=" in line and not line.lstrip().startswith((";", "#")):
            name, value = line.split("=", 1)
            if name.strip().casefold() == key.casefold():
                matches.append((index, value.strip()))
    if not matches and optional:
        return None
    if len(matches) != 1:
        fail(f"Expected one [{section}] {key} setting; found {len(matches)}")
    return matches[0]


def read_ini(path, game):
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(game):
        fail(f"Refusing config outside this game, a symlink, or missing file: {path}")
    return path.read_bytes().decode("utf-8").splitlines(keepends=True)


def windows_path(path):
    compat = os.environ.get("STEAM_COMPAT_DATA_PATH")
    prefix = Path(compat) / "pfx" if compat else Path(os.environ.get("WINEPREFIX", "/nonexistent"))
    mappings = []
    for drive in (prefix / "dosdevices").glob("[a-zA-Z]:"):
        root = drive.resolve()
        if drive.is_symlink() and path.is_relative_to(root):
            mappings.append((len(root.parts), drive.name[0].upper(), root))
    if not mappings:
        fail(f"No Wine drive maps {path}; check the game's Proton prefix")
    _, drive, root = max(mappings)
    value = f"{drive}:/" + path.relative_to(root).as_posix()
    if any(character in value for character in ("\n", "\r", "\\")):
        fail("HelixSR library paths cannot contain line breaks or literal backslashes")
    return value


def configure(game, state_path, action):
    state = json.loads(state_path.read_text()) if state_path.exists() else None
    if state and (state.get("version") != 1 or state.get("game") != str(game)):
        fail("Unrecognized HelixSR state; refusing to replace it")
    if action == "off":
        if not state:
            print("HelixSR has no owned settings to restore for this game.")
            return
        path = Path(state["config"])
        lines = read_ini(path, game)
        for item in state["settings"]:
            location = field(lines, item["section"], item["key"], optional=True)
            if location is None:
                print(f"Keeping deleted [{item['section']}] {item['key']}.")
                continue
            index, value = location
            if value in [item["value"], *item.get("previous_values", [])]:
                lines[index] = item["before"]
            else:
                print(f"Keeping changed [{item['section']}] {item['key']}; no longer owned by HelixSR.")
        atomic_write(path, "".join(lines).encode("utf-8"))
        state_path.unlink()
        fsync_directory(state_path.parent)
        print(f"Restored HelixSR-owned settings in {path}")
        return

    source = Path(os.environ.get("HELIXSR_DIR", str(Path.home() / ".local/share/helixsr"))).expanduser().resolve()
    libraries = [source / "fsr3-drop-in" / name for name in
                 ("amd_fidelityfx_dx12.dll", "amd_fidelityfx_upscaler_dx12.dll")]
    for library in libraries:
        if not library.is_file() or library.stat().st_size == 0:
            fail(f"Missing prepared HelixSR DLL: {library}. Complete upstream setup first; this recipe does not build/download it.")
    values = ["fsr31", *(windows_path(path) for path in libraries)]
    if state:
        path = Path(state["config"])
    elif os.environ.get("HELIXSR_CONFIG"):
        path = Path(os.environ["HELIXSR_CONFIG"]).expanduser()
        if not path.is_absolute():
            path = game / path
    else:
        candidates = []
        for directory, dirs, files in os.walk(game, followlinks=False):
            dirs[:] = [name for name in dirs if not (Path(directory) / name).is_symlink()]
            candidates.extend(Path(directory) / name for name in files if name.casefold() == "optiscaler.ini")
        if len(candidates) != 1:
            fail(f"Expected one installed OptiScaler.ini, found {len(candidates)}. Enable OptiScaler first or set HELIXSR_CONFIG inside this game.")
        path = candidates[0]
    lines = read_ini(path, game)
    requested = list(zip(SETTINGS, values))
    if field(lines, "FSR", "UpscalerIndex", optional=True):
        requested.append((("FSR", "UpscalerIndex"), "0"))
    settings = []
    pending_settings = []
    for (section, key), value in requested:
        index, current = field(lines, section, key)
        before = lines[index]
        owned = []
        if state:
            previous = next((item for item in state["settings"] if (item["section"], item["key"]) == (section, key)), None)
            if previous:
                owned = [previous["value"], *previous.get("previous_values", [])]
            if previous and current not in [*owned, previous["before"].split("=", 1)[1].strip()]:
                fail(f"[{section}] {key} changed after activation; disable HelixSR to release its saved settings first")
            if previous:
                before = previous["before"]
        ending = "\r\n" if lines[index].endswith("\r\n") else "\n" if lines[index].endswith("\n") else ""
        lines[index] = lines[index].split("=", 1)[0] + "=" + value + ending
        settings.append(dict(section=section, key=key, before=before, value=value))
        pending_settings.append(dict(settings[-1], previous_values=list(dict.fromkeys(owned))))
    # Own both the old and pending values until the INI replacement has committed.
    state = dict(version=1, game=str(game), config=str(path), settings=settings)
    pending_state = dict(state, settings=pending_settings)
    atomic_write(state_path, (json.dumps(pending_state, indent=2) + "\n").encode())
    atomic_write(path, "".join(lines).encode("utf-8"))
    atomic_write(state_path, (json.dumps(state, indent=2) + "\n").encode())
    print(f"Selected HelixSR in {path}. Verify FSR HelixSR and override paths in OptiScaler's menu/log.")


try:
    if len(sys.argv) != 2 or not sys.argv[1]:
        fail("Usage: configure.sh /path/to/installed/game (normally supplied by Steam)")
    game = Path(sys.argv[1]).resolve(strict=True)
    if not game.is_dir():
        fail("The game install path must be a directory")
    action = os.environ.get("DLOR_HELIXSR_ACTION", "on")
    if action not in ("on", "off"):
        fail("DLOR_HELIXSR_ACTION must be on or off")
    state_dir = Path.home() / ".dlor/state/helixsr"
    # Persist each path component even if an earlier interrupted run created it.
    for directory in (state_dir.parent.parent, state_dir.parent, state_dir):
        directory.mkdir(exist_ok=True)
        fsync_directory(directory.parent)
    identity = hashlib.sha256(str(game).encode()).hexdigest()
    state_path = state_dir / f"{identity}.json"
    with (state_dir / f"{identity}.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        configure(game, state_path, action)
except (OSError, ValueError, KeyError, StopIteration) as error:
    print(f"Error: {error}", file=sys.stderr)
    sys.exit(1)
PY
