# Decky Launch Options

**Auto Update Decky Launch Options** is an opt-in dropdown with **None** as its
only default. Select **Regular** or **With store** for a game (or globally in DLO)
to check the latest stable release of `Wurielle/decky-launch-options` before each
launch. Regular uses `decky-launch-options.zip`; With store uses
`decky-launch-options-with-store.zip`, whose package version ends in `-with-store`.
It updates only **Launch Options**, never Launch Options Recipes or Decky Loader.
None emits no command or environment assignment and does not uninstall DLO.

Changing between Regular and With store replaces the installed build even when
both belong to the same release. The store suffix is a build variant, not a
prerelease, and neither choice downgrades an installed newer release. Selecting a
build missing from the latest release fails without falling back to the other
build (for example, while the With store build is still being published).
Replace the old standalone toggle when re-importing: the new choice IDs are
`decky-launch-options-auto-update-none`, `-regular`, and `-with-store`, sharing
dropdown ID `decky-launch-options-auto-update`. Re-importing these choices does
not delete the old saved toggle automatically.

Requires Bash, Python 3.9+ with its standard library, a running Decky frontend, and
Steam's existing **local CEF remote debugging endpoint on port 8080**. The updater
does not enable debugging, install packages, use sudo, or restart Steam/Decky.
It reuses the frontend's existing `DeckyBackend` connection: Decky 3.3.1 accepts
only one backend WebSocket, so opening another would disconnect its frontend.
The native installer performs the installation and backend reload; the script
also checks/reloads the frontend and preserves the existing plugin order.

Only this explicitly enabled updater's matching name/version/checksum install
request is automatically confirmed. Other install prompts retain their normal
handlers. This uses Decky internal APIs verified against 3.3.1; unsupported APIs
fail before requesting installation. Duplicate DLO folders under
`~/homebrew/plugins` are refused because Decky's native installer would select an
arbitrary copy. Keep a single installed DLO copy before selecting automatic updates.
Disabled or missing DLO installations are left alone. Unrecognized installed
versions and missing upstream SHA-256 metadata also stop the helper.

Packages are cached by version and asset name under
`~/.dlor/cache/decky-launch-options/` (override with `DLO_UPDATE_CACHE_DIR`).
Both fresh and cached archives must match GitHub's complete SHA-256 and size and
contain the expected DLO metadata/version, backend, and frontend. Temporary
downloads are validated before publication. The native installer receives the
same checksum and a local ZIP path. Existing DLO settings are handled by its native
uninstall/startup migration; this recipe does not edit profiles or launch options.
An interrupted installation is checked rather than blindly retried in the same run.

Checks and downloads have timeouts, and concurrent game launches share a
nonblocking lock. Logging is best-effort under
`~/.dlor/logs/decky-launch-options/auto-update/`, keeping ten logs. Helper failures
remain nonzero in those logs; the shared runner still starts the game with its
original arguments and Steam environment. Updates run synchronously before the
game and can add download/installation time to that launch.

For local development, run
`DLO_UPDATE_VARIANT=regular bash recipes/decky-launch-options/scripts/auto-update.sh`
only when intentionally updating the local device; choose `with-store` for the
store build. Direct calls without `DLO_UPDATE_VARIANT` retain Regular for backward
compatibility. Unknown variants are rejected before connecting or downloading.
`--help` performs no update.
Generated catalog commands use the standard commit-pinned remote runner; an
unpublished local script is not available at that remote commit. This change can
be reviewed and tested locally without publishing or deploying it.

Offline validation:

```sh
python3 scripts/test-dlo-auto-update.py
python3 scripts/test-log-retention.py
```
