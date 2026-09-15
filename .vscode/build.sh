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
"$CLI_LOCATION" plugin build --engine "$CONTAINER_ENGINE" \
    "${BUILD_OPTIONS[@]}" --tmp-output-path "$BUILD_TEMP_DIR/build" "$PROJECT_DIR"
