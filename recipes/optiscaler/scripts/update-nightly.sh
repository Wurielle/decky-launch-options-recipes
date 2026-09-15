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
readonly RECIPE_NAME="optiscaler"
readonly SCRIPT_NAME="update-nightly"
log_dir="${HOME}/.dlor/logs/$RECIPE_NAME/$SCRIPT_NAME"
printf -v log_timestamp '%(%Y-%m-%dT%H-%M-%S)T' -1
log_timestamp+=".${EPOCHREALTIME##*.}"
log_file="$log_dir/$log_timestamp.log"
if mkdir -p -- "$log_dir" && : >> "$log_file" && command -v tee >/dev/null 2>&1; then
    # Keep draining output even if a log write or the console fails.
    exec > >(tee --output-error=warn -a -- "$log_file") 2>&1
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

readonly REPOSITORY="optiscaler/OptiScaler-nightly"
readonly RELEASES_URL="https://api.github.com/repos/${REPOSITORY}/releases?per_page=1"
readonly CACHE_ROOT="${OPTISCALER_CACHE_DIR:-${TMPDIR:-/tmp}/update-optiscaler}"

fail() {
    printf 'Error: %s\n' "$*" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

usage() {
    printf 'Usage: bash update-nightly.sh /path/to/steam-game-directory\n'
    printf 'Updates fgmod dxgi.dll installations beside OptiScaler.ini, including subfolders.\n'
    printf 'Preserves configuration. Override cache with OPTISCALER_CACHE_DIR (default: %s).\n' "$CACHE_ROOT"
    printf 'Overlays supporting DLLs from ~/fgmod; keeps the nightly OptiScaler injector.\n'
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
    exit 0
fi
if (( $# != 1 )); then
    usage >&2
    exit 2
fi
[[ -d "$1" ]] || fail "Game directory does not exist: $1"
target_dir="$(cd -- "$1" && pwd -P)"

# fgmod may install beside a nested executable rather than at the Steam root.
# Require its OptiScaler config so an unrelated dxgi.dll is not replaced.
install_dirs=()
while IFS= read -r -d '' config; do
    directory="${config%/*}"
    if [[ -f "$directory/dxgi.dll" ]]; then
        install_dirs+=("$directory")
    fi
done < <(find "$target_dir" -type f -iname 'OptiScaler.ini' -print0)
(( ${#install_dirs[@]} > 0 )) || fail "No fgmod OptiScaler installation found in: $target_dir"

require_command curl
require_command python3
require_command mktemp

mkdir -p -- "$CACHE_ROOT"
printf 'Checking the latest OptiScaler nightly release...\n'
# Nightlies are prereleases, which GitHub's /releases/latest endpoint excludes.
release_json="$(curl -fsSL --retry 3 --retry-delay 1 "$RELEASES_URL")" ||
    fail "Could not download the latest nightly release metadata"
release_info="$(python3 -c '
import json, re, sys
releases = json.load(sys.stdin)
release = next(r for r in releases if not r["draft"])
asset = next(a for a in release["assets"]
             if a["name"].startswith("OptiScaler_") and a["name"].endswith(".7z"))
version, name = release["tag_name"], asset["name"]
if any(not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", s) for s in (version, name)):
    sys.exit("Invalid release version or asset name")
print(version)
print(name)
' <<< "$release_json")" || fail "Could not determine the latest nightly release"
mapfile -t release_fields <<< "$release_info"
version="${release_fields[0]}"
asset_name="${release_fields[1]}"
version_dir="$CACHE_ROOT/$version"
archive="$version_dir/$asset_name"
cached_files="$version_dir/files"
asset_url="https://github.com/${REPOSITORY}/releases/download/${version}/${asset_name}"
mkdir -p -- "$version_dir"

download_tmp=""
extract_tmp=""
cleanup() {
    if [[ -n "$download_tmp" ]]; then
        rm -f -- "$download_tmp"
    fi
    if [[ -n "$extract_tmp" ]]; then
        rm -rf -- "$extract_tmp"
    fi
}

download_archive() {
    download_tmp="$(mktemp "$version_dir/.${asset_name}.XXXXXX")"
    printf 'Downloading %s...\n' "$version"
    curl -fsSL --retry 3 --retry-delay 1 "$asset_url" -o "$download_tmp"
    [[ -s "$download_tmp" ]] || fail "Downloaded archive is empty"
    mv -f -- "$download_tmp" "$archive"
    download_tmp=""
}

extract_files() {
    extract_tmp="$(mktemp -d "$version_dir/.files.XXXXXX")"
    if ! "$extractor" x -y "-o$extract_tmp" "$archive" ||
        [[ ! -s "$extract_tmp/OptiScaler.dll" ]]; then
        rm -rf -- "$extract_tmp"
        extract_tmp=""
        return 1
    fi
    rm -rf -- "$cached_files"
    mv -- "$extract_tmp" "$cached_files"
    extract_tmp=""
}

if [[ -s "$cached_files/OptiScaler.dll" ]]; then
    printf 'Using cached %s.\n' "$cached_files"
else
    extractor=""
    for candidate in 7zz 7z 7za; do
        if command -v "$candidate" >/dev/null 2>&1; then
            extractor="$candidate"
            break
        fi
    done
    [[ -n "$extractor" ]] || fail "Required command not found: 7zz, 7z, or 7za"
    if [[ -s "$archive" ]]; then
        printf 'Using cached archive %s.\n' "$archive"
    else
        download_archive
    fi
    if ! extract_files; then
        printf 'Cached archive is invalid; downloading it again.\n' >&2
        rm -f -- "$archive"
        download_archive
        extract_files || fail "The downloaded archive does not contain a valid OptiScaler.dll"
    fi
fi

# Overwrite policy: fgmod's supporting DLLs intentionally take precedence over
# nightly dependencies, including subfolders. Apply only the selected variant
# (FGMOD_FSR4_VARIANT or install-manifest.json); exclude alternate bundles and
# renames/ injector copies. Install the nightly OptiScaler injector last so
# Framegen's older injector cannot replace it. Keep cached downloads unchanged.
python3 - "$cached_files" "$HOME/fgmod" "${install_dirs[@]}" <<'PY'
import hashlib, json, os, pathlib, shutil, sys

cache, fgmod = map(pathlib.Path, sys.argv[1:3])

def checksum(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def dlls(root, excluded=()):
    return {
        str(path.relative_to(root)).casefold(): path
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.suffix.lower() == ".dll"
        and path.name.lower() != "optiscaler.dll"
        and not any(part.casefold() == "renames" or part.casefold().startswith("fsr4-")
                    or part in excluded for part in path.relative_to(root).parts[:-1])
    }

metadata_path = fgmod / "install-manifest.json"
metadata = json.loads(metadata_path.read_text()) if metadata_path.is_file() else {}
variants = metadata.get("fsr4_variants", {})
sources = dlls(fgmod, {v["dir_name"] for v in variants.values() if "dir_name" in v})
selected = os.environ.get("FGMOD_FSR4_VARIANT") or metadata.get("selected_default_variant")
variant_dir = variants.get(selected, {}).get("dir_name")
if variant_dir:
    variant = (fgmod / variant_dir).resolve()
    if not variant.is_relative_to(fgmod.resolve()):
        raise ValueError("Framegen variant directory must be inside ~/fgmod")
    sources.update(dlls(variant))

archive_files = dlls(cache)
modern_layout = (cache / "OptiScaler").is_dir()
for directory in map(pathlib.Path, sys.argv[3:]):
    for source in archive_files.values():
        destination = directory / source.relative_to(cache)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)

    target = directory / "OptiScaler" if modern_layout else directory
    target.mkdir(exist_ok=True)
    manifest = target / ".dlor-fgmod.json"
    legacy_manifest = target / ".dlor-fsr4.json"
    previous_file = manifest if manifest.is_file() else legacy_manifest
    previous = json.loads(previous_file.read_text()) if previous_file.is_file() else {}
    current = {}
    for relative, source in sources.items():
        # Match Windows paths case-insensitively (e.g. D3D12_Optiscaler).
        archive_key = "optiscaler/" + relative if modern_layout else relative
        bundled = archive_files.get(archive_key)
        source_root = variant if variant_dir and source.is_relative_to(variant) else fgmod
        destination = directory / bundled.relative_to(cache) if bundled else target / source.relative_to(source_root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        current[str(destination.relative_to(target))] = checksum(destination)
        print(f"Using fgmod DLL: {source} -> {destination}")

    # Remove only obsolete copies we still own; retain nightly replacements and
    # files that have since been changed by the user or another mod.
    for relative, digest in previous.items():
        destination = target / relative
        archive_key = "optiscaler/" + relative.casefold() if modern_layout else relative.casefold()
        if relative in current or archive_key in archive_files:
            continue
        if destination.resolve().is_relative_to(target.resolve()) and destination.is_file():
            if checksum(destination) == digest:
                destination.unlink()
                print(f"Removed previous fgmod DLL: {destination}")
    manifest.write_text(json.dumps(current))
    shutil.copyfile(cache / "OptiScaler.dll", directory / "dxgi.dll")
    print(f"Upgraded: {directory}")
PY
printf 'Version: %s\nCache: %s\n' "$version" "$version_dir"
