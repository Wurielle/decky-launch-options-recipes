# OptiScaler FrameGen ANR

**Addon only.** This toggle adds the official ANR FG V.B14 custom provider to an
**already installed and working OptiScaler with custom FG provider support**.
It never installs, upgrades, replaces, or removes OptiScaler, its injection proxy,
Wine overrides, ASI settings, upscaler settings, or game environment.

## Use in Decky Launch Options

Import **OptiScaler FrameGen ANR** in the **OptiScaler** group. Its dropdown has
**None / Install / Uninstall**, with **None** as the inert default. Select **Install**
for the game and launch normally. Preparation runs unattended before the game,
using the stock `remoteScript` / `~/.dlor/run` helper contract. No executable picker,
desktop dialog, running process, manual addon build, or separately enabled
dependency is required. Select **Uninstall** and launch again to remove unchanged
owned files and restore still-owned settings. Selecting **None**, deselecting an
action, or disabling the dropdown does nothing; it does **not** uninstall ANR.
Close an already running game before changing installation actions.

The shared dropdown ID is `optiscaler-framegen-anr`; its choice IDs are
`optiscaler-framegen-anr-none`, `optiscaler-framegen-anr-install`, and
`optiscaler-framegen-anr-uninstall`.

If you imported the earlier Boolean option (`anr-framegen`), remove that saved
option before importing this dropdown: recipe re-import does not delete retired
saved IDs. Removal of the saved option is not the uninstall action; select the new
**Uninstall** choice if you want to remove an existing managed ANR installation.

**Turn on DLSS/NVIDIA frame generation in the game's own settings.** This selects
ANR as that provider; it does not add native DLSSG input support to games without
it. It does not force FG enable/output, multipliers, GPU spoofing, or presets.
The shipped ANR defaults remain unchanged, including `model_size=large` and
`max_generated=5`; those defaults are not proof of a selected or working 6X mode.
Restart the game after changing provider settings.

### Existing OptiScaler capability prerequisite

The user's existing OptiScaler is assumed installed; no core download or upgrade
is performed, even on failure. The upstream addon requires custom FG providers
(`FGNvngxReplacement`), not merely a similar version label. Native source verified
at `2fff542e78e257a1e4ff5a1e21a69a166c78c335` identifies itself as **10.0.0-dev**, not
0.10.0. Custom DLSSG support was added in
[`941ce6a1c12f16fec5dfec2898a027fdce06dd2c`](https://github.com/optiscaler/OptiScaler/commit/941ce6a1c12f16fec5dfec2898a027fdce06dd2c).
This recipe does not inspect or execute installed binaries to certify that
capability, and does not claim blanket compatibility for everything called
“0.10+”. An older incompatible build remains a prerequisite failure, not permission
to upgrade it.

## Discovery, placement and configuration

The selected Steam installation directory is searched recursively, matching
`OptiScaler.ini` case-insensitively. Exactly one anchor must exist. Its containing
directory is treated as the existing OptiScaler proxy/config directory **P**.
No game EXE or running process is needed. Multiple anchors, case collisions,
symlinked game paths/tree entries, duplicate relevant INI sections/keys,
unsupported encoding, unsafe destinations, or a foreign addon directory are
refused without changing the game. This intentionally conservative policy may
refuse a game containing unrelated symlinks/case collisions too.

The effective library root **M** follows the inspected native loader:

- Missing/empty/`auto` `[Libraries] OptiDllPath`: use **P/OptiScaler** if a directory,
  otherwise **P**. Filesystem matching is case-insensitive.
- An explicit relative path resolves against **P**, not the launch working
  directory. A nonexistent/non-directory selected path falls back to **P**,
  matching native initialization rather than the bundled shell installer's
  approximation.
- Absolute POSIX and Wine `Z:` paths are supported only when contained in the
  selected game tree. Unknown Wine drive mappings, `..` traversal, paths outside
  the game, and redirected/ambiguous paths are refused. Paths are not rewritten.

All **19** provider files retain the complete upstream tree at
`M/custom/Apex Neural Rendering FG/dlssg/...`, including model packs, tables,
`nr_fg.ini`, and `nvngx_dlssg.dll`. The game's own `nvngx_dlssg.dll` is untouched.
The archive's unchanged `README.txt` and `nr_fg_package.json` are also retained in
the provider directory for upstream instructions and provenance. No installer
script is copied or executed. Existing manually/upstream-installed ANR directories
are **not adopted**, migrated, or overwritten.

Only these settings are written, without quotes or inline comments:

```ini
[FrameGen]
FGInput=nvngxfg
FGNvngxReplacement=Apex Neural Rendering FG
```

Native custom-provider discovery scans `M/custom/<name>/dlssg/nvngx_dlssg.dll`.
No registration file, ASI loader, `Plugins.Path`, or generic DLSS DLL override is
needed. The upstream installer record `nr_fg_install.json` is not registration
and is not fabricated here.

## Reversibility and failure handling

- Ownership and version/release/member provenance live in a private per-user
  cache keyed by the absolute game directory. Per-game advisory locks serialize
  this recipe's operations. No shared runner or other recipe is modified.
- A durable write-ahead transaction records original/desired bytes **before**
  game changes. Every operation is preflighted. Retry completes an interrupted
  plan only when files still match its recorded before/after state. Recovery
  enforces the same addon-only and two-key write policy as a new operation.
  Conflicting foreign changes fail closed, retain the journal, and require
  resolving that conflict; they are never silently overwritten.
- ON installs payloads before selecting ANR. OFF restores configuration before
  removing payloads. Atomic replacements are synced and preserve the current
  INI's ordinary permission bits even under a restrictive umask.
- With no intervening edit, OFF restores exact original INI bytes, including BOM,
  line endings, whitespace, missing keys/section, and final-newline state. With
  edits, it restores only still-identical owned setting lines and retains other
  current bytes. Repeated ON does not rebaseline or overwrite user edits.
- Changed owned files, changed payload permission bits, logs, and foreign additions
  survive OFF. Only known empty directories created by this recipe are pruned.
  Retained files make a later fresh ON a foreign-directory collision rather than
  silently reacquiring ownership. Existing modified provider/configuration files
  are not reset by repeated ON; the log reports preserved modified files on OFF.
- Changing `OptiDllPath` while owned makes ON refuse a move. OFF uses the recorded
  old destination and preserves the user's new path setting. Renaming the game
  directory/INI or deleting ownership records is not an automatic migration.
- OFF never downloads or unpacks the addon. Verified source/ZIP caches persist
  across OFF. Cold source acquisition may still be needed for OFF; the stock
  runner itself also fetches its physical shell entrypoint.
- Auxiliary failures return nonzero and are logged; the stock runner continues
  the game. Failure does not prove the game is compatible or that frame generation
  works. Locks protect cooperating recipe invocations, not a malicious same-user
  process racing filesystem operations. No gameplay/performance result is claimed.

Logs: `~/.dlor/logs/anr-framegen/{install,uninstall}/<timestamp>.log`, newest 10 per
action. Logging is best-effort; unavailable/unsafe log paths use the console.
ANR's own logs, when generated by the game, are beside its `dlssg/nr_fg.ini`.

## Acquisition and provenance

`./scripts/downloads.json` contains the official URL, version, size, full SHA256,
ANR code revision, and each installed member's size/digest/path. Normal ON fetches
only the official **FG-V.B14 addon**, size **3219169**, SHA256
`cf123530037b2f349d70f6e13331cd255bbb69a17b610d4bc7fc103559f20d7e`.
The archive and every selected member are verified; unsafe archive paths/types,
symlinks, privileged modes, encryption, and case-colliding entries are rejected.
This matches published release bytes; it is not a publisher signature or vendor
endorsement. No OptiScaler core, Python package, setup program, or additional model
is acquired.

The commit-pinned shell embeds an independent bundle repository/revision and one
manifest SHA256. It authenticates a private read-only JSON snapshot, extracts the
loader hash with Bash builtins, authenticates a private physical `loader.py`, and
runs `python3 -I -B` on that file. The loader rechecks manifest and runtime bytes.
No Python heredoc or `python -c` is part of the runtime chain. Host environment
cleanup is scoped to auxiliary processes; cache-creation `umask 077` is restored
before invoking the loader and never changes the game's inherited mask.

### Licensing boundary

The inspected addon supplies **no explicit ANR license/redistribution grant**.
OptiScaler's GPL license does not establish ANR's license. This recipe fetches
unchanged official release bytes directly to the user's machine, retains bundled
documentation/provenance, and does not bundle, mirror, modify, or redistribute the
ANR binaries or copy the upstream installer implementation. No consent or terms
acceptance is invented. This is a technical integration, not legal clearance for
repackaging. Obtain publisher clarification before redistributing ANR artifacts.

Upstream inspected contracts:
[release](https://github.com/apex-compute/ANR/releases/tag/FG-V.B14), addon
`README.txt`, `install.sh`, `install.ps1`, `nr_fg_package.json`; native
[Config.cpp](https://github.com/optiscaler/OptiScaler/blob/2fff542e78e257a1e4ff5a1e21a69a166c78c335/OptiScaler/Config.cpp#L836-L867),
[dllmain.cpp](https://github.com/optiscaler/OptiScaler/blob/2fff542e78e257a1e4ff5a1e21a69a166c78c335/OptiScaler/dllmain.cpp#L1703-L1723),
[CustomProviders.h](https://github.com/optiscaler/OptiScaler/blob/2fff542e78e257a1e4ff5a1e21a69a166c78c335/OptiScaler/misc/CustomProviders.h),
and [Nvngx_Custom.cpp](https://github.com/optiscaler/OptiScaler/blob/2fff542e78e257a1e4ff5a1e21a69a166c78c335/OptiScaler/framegen/nvngx/Nvngx_Custom.cpp).

## Maintainer verification and publication boundary

Tests are real file-preparation tests using the SHA-verified official archive;
local transport fixtures substitute only HTTPS acquisition. They never execute
upstream setup/DLLs or a game. The archive is not checked in. Set
`ANR_TEST_ARCHIVE` to an existing copy (default `$TMPDIR/anr-fg-V.B14-addon.zip`).

```sh
python3 -I -B -m unittest discover -s recipes/anr-framegen/tests -v
node_modules/.bin/tsc -p tsconfig.recipes.json --noEmit
```

Commit reviewed runtime changes before repinning physical entrypoints. The bundle
revision must contain the exact `loader.py` and `downloads.json` bytes authenticated
by the generated shell:

```sh
python3 -I -B recipes/anr-framegen/scripts/update-source-hashes.py --bundle-revision <full-runtime-bundle-commit>
```

An ordinary rerun retains the prior revision; the generator never commits,
fetches, or builds `recipes.json`. Verify published bundle availability and the
actual DLO consumer/stock-runner path, then generate the catalog against a source
commit containing the repinned entrypoints. File-preparation and launcher tests
do not establish native initialization, GPU compatibility or gameplay results.
