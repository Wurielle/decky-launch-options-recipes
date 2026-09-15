#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CLI_LOCATION="$PROJECT_DIR/cli/decky"

if [[ ! -x "$CLI_LOCATION" ]]; then
    echo "Decky CLI is missing. Run 'just depsetup' first." >&2
    exit 1
fi

cd "$PROJECT_DIR"
BUILD_OPTIONS=()
if command -v docker >/dev/null && docker info >/dev/null 2>&1; then
    CONTAINER_ENGINE=docker
elif command -v podman >/dev/null && podman info >/dev/null 2>&1; then
    CONTAINER_ENGINE=podman
    # Root in a rootless Podman container maps to the current host user.
    if [[ "$(podman info --format '{{.Host.Security.Rootless}}')" == true ]]; then
        BUILD_OPTIONS+=(--build-as-root)
    fi
else
    echo "No accessible container engine. Start Docker or configure rootless Podman, then retry." >&2
    exit 1
fi

echo "Building plugin in $PROJECT_DIR"
BUILD_TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/decky-build.XXXXXXXX")"
trap 'rm -rf -- "$BUILD_TEMP_DIR"' EXIT

# The CLI relabels its Podman mounts. Stage current source (including uncommitted
# files) without old root-owned caches, build outputs, or local credentials.
BUILD_SOURCE_DIR="$BUILD_TEMP_DIR/source"
mkdir -p -- "$BUILD_SOURCE_DIR"
git ls-files --cached --others --exclude-standard -z |
    rsync -rlt --from0 --files-from=- --ignore-missing-args "$PROJECT_DIR/" "$BUILD_SOURCE_DIR/"

"$CLI_LOCATION" plugin build --engine "$CONTAINER_ENGINE" \
    "${BUILD_OPTIONS[@]}" --tmp-output-path "$BUILD_TEMP_DIR/build" \
    --output-path "$BUILD_TEMP_DIR/artifacts" "$BUILD_SOURCE_DIR"

shopt -s nullglob
BUILD_ARCHIVES=("$BUILD_TEMP_DIR/artifacts/"*.zip)
if (( ${#BUILD_ARCHIVES[@]} == 0 )); then
    echo "Build did not produce a plugin ZIP." >&2
    exit 1
fi

# Older builds may have left a root-owned output directory. Preserve it before
# replacing it with a writable directory; this requires no elevated permissions.
if [[ -d "$PROJECT_DIR/out" && ! -w "$PROJECT_DIR/out" ]]; then
    # Rename within the same parent: moving a root-owned directory into another
    # parent would also require permission to update its '..' entry.
    BACKUP_DIR="$(mktemp -d "$PROJECT_DIR/.out-backup.XXXXXXXX")"
    rmdir -- "$BACKUP_DIR"
    mv -- "$PROJECT_DIR/out" "$BACKUP_DIR"
    echo "Preserved previous build output in $BACKUP_DIR"
fi
mkdir -p -- "$PROJECT_DIR/out"
cp -f -- "${BUILD_ARCHIVES[@]}" "$PROJECT_DIR/out/"
printf 'Built: %s\n' "${BUILD_ARCHIVES[@]##*/}"
