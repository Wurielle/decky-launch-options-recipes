# OptiScaler versioned settings

The **OptiScaler** recipe targets the legacy fgmod **v0.9** configuration, checked against upstream v0.9.5. **DLOR OptiScaler** bundles its own **v10 nightly** settings; import that recipe for the managed installer and its configuration controls. The two recipes generate an explicit versioned settings contract rather than copying the stable recipe into the nightly installer. Do not combine conflicting controls from both recipes for one game. Configuration controls are ordinary environment assignments.

The legacy fgmod dropdown offers **None**, **Install** and **Uninstall**, defaulting to None. All disabled action commands are empty; only an explicitly selected action runs fgmod. The original option ID is retained on None so re-importing replaces the old automatic OFF uninstaller. Nightly Upgrade remains available with the same ID/name/priority and is compatible with DLOR-managed games; do not select the separate legacy Install/Uninstall actions against a DLOR-managed game. Upgrading a legacy installation to v10 does not change the selected settings dialect: use the v10 controls from DLOR and remove conflicting legacy selections after upgrading.

Every dropdown defaults to **None**, which emits nothing and preserves the current INI. **Auto** is an explicit request to write `auto`, not an inactive/default choice. New settings do not automatically activate FG, change models, or download additional libraries. DLOR's physical environment updater applies selected overrides transactionally and restores still-owned values when an override is removed on a subsequent Install, or when Uninstall is selected. Existing FrameGen/HUDFix toggles retain their explicit ON/OFF semantics.

## Nightly Upgrade and pinned downloads

**DLOR OptiScaler** installs the exact core, OptiPatcher, compatibility profiles and conditional official 7zip downloads pinned in its [JSON manifest](../dlor-optiscaler/scripts/downloads.json). Enable **OptiScaler Nightly Upgrade** alongside DLOR to explicitly override only the core pin: every enabled launch requests fresh official nightly metadata and a complete upstream SHA256, without metadata TTL or stale/offline fallback. Metadata or checksum failure preserves the managed installation and the stock runner still continues the game. Disabling the option returns the next ordinary DLOR Install to the pinned core.

DLOR Install prepares the pinned installation; the priority `-1` Nightly helper then upgrades it through the existing journal. If the later latest lookup fails, the already prepared pinned installation remains. Neither command needs action, latest-policy, repository or revision environment assignments in its launch field. DLOR Uninstall leaves an empty journal, so the later Nightly helper cannot reinstall; unchanged owned-proxy checks also refuse a partially removed installation. Nightly alone can transactionally upgrade a valid existing owned installation, preserving the installed compatibility profile; an empty DLOR journal remains disabled. Only games with no DLOR journal use the SHA-verified physical legacy fgmod updater, preserving selected variants, supporting-DLL overlays, case layout and legacy cache override. It never overlays `~/fgmod` into DLOR-owned files. See the [installer contract and pin-maintenance instructions](../dlor-optiscaler/README.md).

## Stable v0.9 selectors

- FrameGen inputs are Auto, No FG, DLSSG via Streamline, FSR 3.1 FG, OptiFG, FSR 3.0 FG and Nukem FG. Outputs are Auto, No FG, FSR FG, XeFG and Nukem FG. Native v0.9 treats the `nukems` input as a coupled Nukem input/output route; it is not an alias for v10's independent `nvngxfg` input and `dlssg` output.
- FidelityFX routes emit `fsr31` / `fsr31_12`, which v0.9 understands. Native DX11 `fsr31` remains distinct from DX11on12 `fsr31_12`. Existing choice IDs and labels are retained while correcting their commands.
- FSR4 quality presets and the ordinary XeFG 2×–4× multiplier are available. v10-only FSR4 GPU/model, XeFG dynamic MFG and DLSSG MFG controls are absent, not silently mapped onto differently defined older settings.
- VSync emits shell-safe `VSync_OverrideVsync` / `VSync_ForceVsync` assignments. The legacy updater normalizes `[V-Sync]` only for this unprefixed section/key form; its `OptiScaler_VSync_*` branch does not apply those settings.

## DLOR v10 nightly selectors

- FrameGen output: Auto, No FG, FSR FG, XeFG, DLSSG and experimental Reprojection. Deprecated `nvngxfg`/`dlssgwithnvngx` outputs are removed; `nvngxfg` remains a valid input. XeFG input is available.
- Nvngx replacement, native-game MFG overrides, FSR backend indexes, XeFG Allow 1× and VSync sync interval are left to OptiScaler's in-game menu rather than exposed as launch options.
- Upscalers use `ffx`/`ffx_12` rather than compatibility aliases. Native DX11 `fsr31` is retained. Native Vulkan FidelityFX capability depends on the available backend/driver.
- FSR4 GPU-support override and model are separate selectors with distinct numbering. GPU support: 0 no override, 1 FP8, 2 INT8, 3 INT8-2, 4 INT8 Lite. Model: 0 FP8, 1 INT8, 2 INT8 RDNA2, 3 INT8 Lite. Neither substitutes for compatible libraries/hardware. The quality-preset control remains separate.
- VSync uses the updater's normalized `VSync` section alias, so settings stay shell-safe assignments rather than `env` wrappers.
- Reprojection is WIP, not MFG. Upstream requires DLSSG via Streamline input, mouse input rather than controller, and first-person perspective. Do not assume it works in an arbitrary Steam Deck game.

## Multi-frame generation in v10

The multiplier includes the original frame: **2× writes 1**, **3× writes 2**, and so on. Output count Auto defaults to one interpolated frame/2×; it does not mean “follow the game's multiplier.” Runtime library/GPU capabilities can lower the available maximum.

- **XeFG:** 2×–4× output multiplier.
- **XeFG Dynamic MFG:** enable/disable, target FPS, target rounding, and use target as FPS limit. The output multiplier becomes the dynamic maximum. Targets are at least 10 FPS; Auto follows the framerate cap or a value just below display refresh. Target-as-cap applies above 2×. Requires the relevant XeFG APIs and is inactive while following the game's count.
- **DLSSG:** 2×–6× output multiplier, forced Dynamic MFG for OptiScaler output, and target FPS. A target of zero uses display refresh.
- **Warning:** explicit `[DLSSG] ForceDMFG=true` also forces FG enabled, even if `[FrameGen] Enabled=false`. Select Off/Auto for that control as well when turning FG off.
- DLSSG Dynamic MFG requires appropriate runtime support, including Streamline 2.11 and supported NVIDIA Blackwell or AMD/Intel Nvngx-replacement paths. Merely exposing these settings does not establish compatibility or supply those libraries.
- Target-FPS dropdowns are convenient presets, not engine limits; other valid values can be supplied through explicit environment overrides.
- Direct FSR FG has no MFG count/dynamic keys in this nightly. Enabler/Combo MFG goes through the DLSSG/Nvngx path. No fictional `FSRFG_InterpolationCount` setting is emitted.

## Updating saved options

Setting IDs and dropdown `valueId`s follow the full display-name hierarchy, such as `optiscaler-framegen-optifg-hudfix` and `optiscaler-framegen-xefg-mfg-multiplier`. DLOR copies add `dlor-` to both IDs. Replace previously imported controls that used shorter IDs when importing this catalog; changed IDs create separate saved controls rather than updating the old ones.

Refetch/re-import this branch's catalog to obtain the updated commands. Obsolete saved aliases/output choices must be removed or replaced in existing profiles; removing catalog entries does not guarantee that the host deletes previously imported options. Select replacement routes deliberately rather than silently converting saved settings. The named Bleeding Edge profiles remain pinned to their selected artifacts; Nightly Upgrade changes only official core release selection.

For an existing **OptiScaler v0.9** import, remove saved `nvngxfg`/`xefg` input choices, `dlssg`/`reprojection` output choices, FSR4 GPU/model controls, XeFG dynamic MFG controls and DLSSG MFG controls. These are no longer offered in the stable recipe. Re-import updates surviving upscaler and VSync commands in place; it cannot delete the retired saved entries. DLOR's v10 choices and IDs are unchanged.

## Verification

```sh
python3 -I -B -m unittest discover -s recipes/optiscaler/tests -p 'test_*.py' -v
```

Requires the repository's Node/pnpm dependencies on PATH. Tests compile both recipe contracts, validate settings/defaults/ranges, round-trip emitted settings against real versioned upstream INI fixtures, and apply stable VSync through the original legacy updater. Synthetic formatting/restoration checks remain separate. This is configuration verification, not a game/GPU/MFG benchmark.

Reference contracts: [stable v0.9.5](https://github.com/optiscaler/OptiScaler/releases/tag/v0.9.5) and [nightly-20261025](https://github.com/optiscaler/OptiScaler-nightly/releases/tag/nightly-20261025), with their matching native parser/backend/menu implementations. Fixture sources and licenses are documented [beside the fixtures](tests/fixtures/README.md). Library and hardware capabilities remain runtime-dependent.
