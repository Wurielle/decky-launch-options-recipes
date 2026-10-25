# OptiScaler nightly settings

The settings in this recipe target the current OptiScaler v10 nightly configuration, not older stable builds. Use **DLOR OptiScaler** for independent installation, then import the wanted settings from **OptiScaler**. The original fgmod launcher/uninstaller and Nightly Upgrade option remain available for Framegen users; do not enable those against a DLOR-managed game. Configuration controls are ordinary environment assignments.

Every dropdown defaults to **None**, which emits nothing and preserves the current INI. **Auto** is an explicit request to write `auto`, not an inactive/default choice. New settings do not automatically activate FG, change models, or download additional libraries. DLOR's physical environment updater applies selected overrides transactionally and restores still-owned values when removed/OFF. Existing FrameGen/HUDFix toggles retain their explicit ON/OFF semantics.

## Current selectors

- FrameGen output: Auto, No FG, FSR FG, XeFG, DLSSG and experimental Reprojection. Deprecated `nvngxfg`/`dlssgwithnvngx` outputs are removed; `nvngxfg` remains a valid input. XeFG input is available.
- Nvngx replacement, native-game MFG overrides, FSR backend indexes, XeFG Allow 1× and VSync sync interval are left to OptiScaler's in-game menu rather than exposed as launch options.
- Upscalers use `ffx`/`ffx_12` rather than compatibility aliases. Native DX11 `fsr31` is retained. Native Vulkan FidelityFX capability depends on the available backend/driver.
- FSR4 GPU-support override and model are separate selectors with distinct numbering. GPU support: 0 no override, 1 FP8, 2 INT8, 3 INT8-2, 4 INT8 Lite. Model: 0 FP8, 1 INT8, 2 INT8 RDNA2, 3 INT8 Lite. Neither substitutes for compatible libraries/hardware. The quality-preset control remains separate.
- VSync uses the updater's normalized `VSync` section alias, so settings stay shell-safe assignments rather than `env` wrappers.
- Reprojection is WIP, not MFG. Upstream requires DLSSG via Streamline input, mouse input rather than controller, and first-person perspective. Do not assume it works in an arbitrary Steam Deck game.

## Multi-frame generation

The multiplier includes the original frame: **2× writes 1**, **3× writes 2**, and so on. Output count Auto defaults to one interpolated frame/2×; it does not mean “follow the game's multiplier.” Runtime library/GPU capabilities can lower the available maximum.

- **XeFG:** 2×–4× output multiplier.
- **XeFG Dynamic MFG:** enable/disable, target FPS, target rounding, and use target as FPS limit. The output multiplier becomes the dynamic maximum. Targets are at least 10 FPS; Auto follows the framerate cap or a value just below display refresh. Target-as-cap applies above 2×. Requires the relevant XeFG APIs and is inactive while following the game's count.
- **DLSSG:** 2×–6× output multiplier, forced Dynamic MFG for OptiScaler output, and target FPS. A target of zero uses display refresh.
- **Warning:** explicit `[DLSSG] ForceDMFG=true` also forces FG enabled, even if `[FrameGen] Enabled=false`. Select Off/Auto for that control as well when turning FG off.
- DLSSG Dynamic MFG requires appropriate runtime support, including Streamline 2.11 and supported NVIDIA Blackwell or AMD/Intel Nvngx-replacement paths. Merely exposing these settings does not establish compatibility or supply those libraries.
- Target-FPS dropdowns are convenient presets, not engine limits; other valid values can be supplied through explicit environment overrides.
- Direct FSR FG has no MFG count/dynamic keys in this nightly. Enabler/Combo MFG goes through the DLSSG/Nvngx path. No fictional `FSRFG_InterpolationCount` setting is emitted.

## Updating saved options

Refetch/re-import this branch's catalog to obtain the updated commands. Obsolete saved aliases/output choices must be removed or replaced in existing profiles; removing catalog entries does not guarantee that the host deletes previously imported options. Select replacement routes deliberately rather than silently converting saved settings. Bleeding Edge download sources and the DLOR install/uninstall implementation are unchanged by this settings update.

## Verification

```sh
python3 -I -B -m unittest discover -s recipes/optiscaler/tests -p 'test_*.py' -v
```

Requires the repository's Node/pnpm dependencies on PATH. Tests compile the TypeScript recipe, validate settings/defaults/ranges and round-trip every emitted setting through the physical DLOR updater against a synthetic INI. This is configuration verification, not a game/GPU/MFG benchmark.

Reference contract: [nightly-20261024](https://github.com/optiscaler/OptiScaler-nightly/releases/tag/nightly-20261024), [packaged-equivalent INI](https://github.com/optiscaler/OptiScaler/blob/fd3a45a6cac6d610a35c570479f80dae95ca4eac/OptiScaler.ini) and its matching native parser/menu implementation. Library and hardware capabilities remain runtime-dependent.
