# DLOR OptiScaler

A self-contained OptiScaler installer recipe. No OptiScaler, driver, SDK, or plugin binaries are stored in this repository. Enabling the main option downloads and verifies the selected components, discovers the selected game's rendering directory, installs the files, and merges the necessary Wine override for that launch. Disabling it restores originals and removes only unchanged recipe-owned files.

## Options

- **DLOR OptiScaler:** install/manage when enabled; uninstall when disabled.
- **Core:** always the official nightly from `optiscaler/OptiScaler-nightly`, using its newer supporting-DLL directory layout. There is no stable-core selector or flat 0.9 package fallback; stale release-channel environment settings cannot select stable.
- **Injection proxy:** automatic selection by default, or an explicit supported proxy. Existing renamed OptiScaler injectors are identified from their bounded PE version resource, not by their filename alone. Other mods' occupied proxies are not silently replaced.
- **OptiPatcher:** optional, separately updated from `optiscaler/OptiPatcher`. Installs into the resolved ASI plugin directory and enables its owned INI setting. OptiPatcher only supports the games/versions documented upstream; it does not universally add DLSS inputs.
- **FSR4 compatibility (third-party):** the bundled official SDK is the default. Explicit alternatives use the Framegen author's `xXJSONDeruloXx/OptiScaler-Bleeding-Edge` mirror:
  - `rdna23-int8`: the mirror's FSR4.0.2c compatibility upscaler.
  - `rdna34-official-411`: the mirror's FSR4.1.1 driver override. The source is still a third-party mirror, despite the profile's historical identifier.
  - `rdna2-valve-411`: experimental Valve/RDNA2 driver pair. Uses the nightly injector and current INI controls rather than replacing it with Framegen's older injector.

Every dropdown's **None** entry leaves explicit user environment policy untouched. All optional features are disabled unless selected. Do not run multiple independent OptiScaler installers against the same game; remove the legacy fgmod installation option when replacing it with this recipe.

## Downloads and integrity

Release metadata is resolved independently of Decky Framegen plugin releases. An artifact must have a full `sha256:` digest in its GitHub release metadata. Missing, unsupported, or mismatched digests abort preparation before game files are changed. Each archive, raw optional DLL/ASI, cached archive, and cached extracted package is verified before use. Release provenance and file ownership are kept in the private per-game journal.

GitHub-provided hashes establish agreement with the GitHub-hosted release. They are **not publisher signatures, a malware scan, proof of AMD endorsement, or a guarantee that an experimental driver works on a particular GPU**. Third-party profiles are opt-in. Never use graphics injection mods in an anti-cheat-protected online game without that game's explicit permission.

Caches live under `~/.dlor/cache/dlor-optiscaler/`; journals/backups under `~/.dlor/state/dlor-optiscaler/`. Metadata is reused for six hours. A transient outage can reuse metadata up to seven days old only when its cached archive still verifies. Valid extracted files are reused; corrupted/incomplete preparation is rebuilt. Uninstall does not resolve release metadata or download mod payloads, and reusable download caches remain.

ZIP, supported tar formats, and 7z/BCJ2 are handled without running upstream setup scripts. If no compatible native 7zip console exists, an official `ip7z/7zip` console is downloaded, SHA-verified, and cached privately. No sudo, global pip installation, desktop dialogs, or system package changes are used. Archive traversal, links, devices, privileged modes, ambiguous Windows paths, and size/count overflows are rejected.

## Placement and restoration

Discovery stays inside `STEAM_COMPAT_INSTALL_PATH`. It searches case-insensitively for existing `OptiScaler.ini` anchors, then uses launch context, bounded AMD64 PE imports, and generic shipping-executable evidence. It does not maintain a list of game names or fixed candidate directories. Ambiguous cases fail without guessing; `DLOR_OPTISCALER_EXECUTABLE` is an optional advanced disambiguation override.

The archive's directory structure and INI contract determine placement. In the v10 nightly the injector/INI remain beside the renderer, while supporting DLLs remain under `OptiScaler/`, including its D3D12 subtree. Existing `Libraries.OptiDllPath`, supported per-library overrides, and `Plugins.Path` are respected within the selected game. Unresolvable drives or paths outside that game are refused. Optional owned plugin paths are made explicit for Wine when needed, avoiding process-working-directory ambiguity. Existing unrelated INI content is preserved; owned settings are restored without discarding other subsequent user edits.

Original files are backed up before replacement, with a durable transaction journal for interrupted updates. Equal pre-existing files are not acquired as removal-owned files. Modified external files are preserved, and originals whose restoration is blocked retain retryable ownership. No broad-name upstream uninstaller is invoked. Preparation failures do not prevent the original game command from running.

## Entry points and runner contract

The main toggle uses a recipe-local, commit-pinned Bash bootstrap. It works with the existing helper-only DLOR runner; no HelixSR changes, updated plugin, shared runner modes, or recipe schema changes are required. Existing ordinary `~/.dlor/run` helper recipes can run before or after this wrapper.

The bootstrap downloads the **complete** `launch.sh`, checks its embedded SHA256 before execution (including trailing newlines), and supplies that invocation's full Git revision/repository context through `DLOR_OPTISCALER_SOURCE_REVISION` and `DLOR_OPTISCALER_SOURCE_REPOSITORY`. It leaves shared `DLOR_SCRIPT_REVISION` / `DLOR_REPOSITORY` values intact for other recipes, including nested helpers. It never pipes a partial download into a shell. Source acquisition or integrity failure continues the original command without adding Wine overrides. Host environment cleanup is confined to acquisition/preparation; original game stdin, inherited descriptors, argv, and unrelated environment remain available. The bootstrap fetches `launch.sh` each time; it does not duplicate the scripts' caches, installation logic, or logging.

`launch.sh` invokes the separately available `install.sh` or `uninstall.sh`. Helper sources are fetched at the bootstrap's full Git revision, cached, and checked against embedded SHA256 values before execution. Verified Python source bytes are compiled directly rather than trusting existing bytecode. Direct administrative invocation of install/uninstall requires the same `DLOR_SCRIPT_REVISION` context; ordinary toggling supplies it automatically.

Each entry logs separately under `~/.dlor/logs/dlor-optiscaler/<entry>/`, retaining ten regular log files per entry. Logging is best-effort. Game argv, unrelated environment, file descriptors, and exit status are preserved; auxiliary host cleanup and preparation logs do not apply to the eventual game process.

After changing a runtime module or the shell generator, run `python3 -I -B recipes/dlor-optiscaler/scripts/update-source-hashes.py`. It regenerates the three shell entrypoints, their module/entry checksums, and the `launchSha256` constant in `index.ts`. Generate `recipes.json` using the repository's normal pinned-source build; do not hand-edit it or change the recipe schema.

## Validation boundary

The actual official `nightly-20261024` archive (`OptiScaler_v10.0.0-pre1_20261024.7z`) was downloaded and matched to GitHub SHA256 `74f20189e0ec76288c86d69057b3feb4750f4680118a9852fb743b343274ac1d`. Filesystem tests installed, reinstalled, checked all 18 files, and uninstalled this real payload in a disposable nested game tree without executing its DLLs or setup scripts.

Offline tests also use explicitly synthetic PE/SDK fixtures for discovery, corruption, rollback, config ownership, source verification, and game-command handoff. Launcher tests execute the real DLO parser at commit `a3996e590b61f0a985a0182cb89278a4850e39f6` and the backend-installed, unchanged helper-only runner against harmless game/installer fixtures. To run them, set `DLO_CONSUMER_SOURCE` to a directory containing that revision's unmodified `run.py` and `shared.py`; their SHA256 values are checked. Run `python3 -I -B -m unittest discover -s recipes/dlor-optiscaler -p 'test_*.py' -v` with the repository's Node toolchain/dependencies available. Source transfers, including failed/partial responses, are local fixtures; no mod or game binary is executed by these tests.

These tests do not establish Steam Deck UI behavior, Wine DLL loading, GPU compatibility, image quality, frame generation, or performance. Real device/game validation remains necessary.

Upstream references: [OptiScaler installation](https://github.com/optiscaler/OptiScaler/wiki/Manual-Installation), [official nightly releases](https://github.com/optiscaler/OptiScaler-nightly/releases), [OptiPatcher](https://github.com/optiscaler/OptiPatcher), [Framegen source](https://github.com/xXJSONDeruloXx/Decky-Framegen), [third-party compatibility releases](https://github.com/xXJSONDeruloXx/OptiScaler-Bleeding-Edge/releases). Preserve the downloaded components' own license notices; this recipe does not relicense or redistribute their payloads.
