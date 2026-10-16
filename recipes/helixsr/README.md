# HelixSR through OptiScaler (experimental)

**Enable HelixSR (OptiScaler DX12), then launch the game.** The toggle performs
its own first-run setup, dependency installation and configuration. There are no
terminal commands, manually built DLLs, edited paths, or separate OptiScaler
toggles required for ordinary use. It is disabled globally by default.

Refetch and re-import the updated PR recipes, including any existing OptiScaler
entry: its updated disabled command must not uninstall a dependency HelixSR needs.

## First launch

The recipe downloads the complete, checksum-verified HelixSR 1.9.0 release and
prepares its network locally using the unmodified upstream Python builder's
unattended mode. NVIDIA's DLSS component is acquired under its
[license](https://github.com/NVIDIA/DLSS/blob/v310.7.0/LICENSE.txt); the license
notice is included in setup logs. No desktop prompts or progress windows open.

Python/numpy and Microsoft's shader compiler are prepared in a per-user cache
when needed. Shader compilation uses Proton/Wine and an isolated build prefix,
not the game's existing prefix. No sudo, system package installation or global
pip changes are made. The initial build can take several minutes; later launches
reuse validated cached outputs.

The helper searches recursively from the game's install root for
`OptiScaler.ini`, matching its name case-insensitively. A unique existing INI
anchors the installation; original launch arguments only disambiguate multiple
installations or select a renderer when no INI exists. No game/project path is
hardcoded. Ambiguous matches are logged without opening a picker or changing
unknown files.

Existing renamed OptiScaler proxies are recognized by their PE version-resource
`OriginalFilename=OptiScaler.dll`, or equality with an available original copy.
This identifies an existing installation; it is not an authenticity check or
permission to remove its files. Unrecognized/conflicting existing proxies are
left untouched rather than replaced with the recipe's stable dependency. A new
dependency is installed only when needed, without replacing unknown mods.

OptiScaler 0.9 and newer v10 use different supporting-library layouts. v10 keeps
the main proxy and INI beside each other but defaults supporting DLLs to the
`OptiScaler/` subfolder through `[Libraries] OptiDllPath`. The recipe preserves
that setting, custom paths, and existing supporting DLLs. Both HelixSR libraries
stay in the validated per-user build cache and are selected through the explicit
absolute FFX overrides below; it does not flatten either installation's layout.

This is **DX12 upscaling only**: it does not enable HelixSR frame generation,
replace the game's native FSR DLLs, or build NVIDIA frame-generation components.
Use single-player games; do not assume DLL injection is safe with anti-cheat.

## Enabling and disabling

On enable, the helpers prepare HelixSR, install/reuse OptiScaler, save the
previous INI values, then set:

```ini
[Upscalers]
Dx12Upscaler=fsr31

[Libraries]
FfxDx12Path=<mapped drive>:/.../fsr3-drop-in/amd_fidelityfx_dx12.dll
FfxDx12SRPath=<mapped drive>:/.../fsr3-drop-in/amd_fidelityfx_upscaler_dx12.dll
```

An existing `[FSR] UpscalerIndex` is temporarily reset to `0`. Paths come from
the actual Wine drive mappings; on a game's first-ever launch, Proton's default
new-prefix root mapping is used. The launcher adds the selected native proxy to
`WINEDLLOVERRIDES` while preserving unrelated overrides, original arguments,
file descriptors and Steam's game environment.

**Disable the toggle and launch once to undo the feature.** This restores only
INI settings still owned by the recipe and removes only unchanged dependency
files it installed. Existing OptiScaler files and later user changes are not
removed. If the independent OptiScaler option remains enabled, its dependency
is retained. Disabling requires no download or build; reusable caches remain.

The ownership journal retains original, previous and pending values until INI
updates commit, so an interrupted source update can be retried or disabled.
Keep `~/.dlor/state/helixsr/` until restoration finishes. Deleting the imported
option without running its disabled command does not execute restoration.

## Cache and diagnostics

- HelixSR release, build tools and locally built output:
  `~/.dlor/cache/helixsr/1.9.0/`.
- Separate logs for launcher, setup, dependency and configuration:
  `~/.dlor/logs/helixsr/<stage>/`.
- Remote-helper download logs: `~/.dlor/logs/run/`.
- Each log folder retains its latest 10 logs. Game stdout/stderr is not captured
  in recipe logs, and the original launch arguments are not logged.

Generated network-containing DLLs belong on your own machine. Do not upload or
redistribute them. Upstream licenses and notices remain with cached releases.

An optional `HELIXSR_DIR` can select an already prepared installation, and
`HELIXSR_CACHE_DIR` changes the cache base. These are advanced recipe inputs,
not required setup steps or native HelixSR runtime variables.

## Device verification

Look for **FSR HelixSR** in OptiScaler's menu and successful loading of both
library override paths in `OptiScaler.log`. A game opening successfully alone is
not proof of activation: OptiScaler can fall back to stock libraries. Helpers
continue the original game command after setup failure; check
the stage log rather than assuming HelixSR was enabled.

Offline tests exercise orchestration, fixture-backed builds, cache integrity,
dependency ownership, restoration, interruptions and parser compatibility. They
do not demonstrate neural-network execution or gameplay performance. Those remain
on-device verification requirements. The helpers have no desktop-UI dependency.

## References

- [HelixSR 1.9.0](https://github.com/lonewolf0622/HelixSR/releases/tag/v1.9.0)
- [NVIDIA DLSS license](https://github.com/NVIDIA/DLSS/blob/v310.7.0/LICENSE.txt)
- [OptiScaler manual installation](https://github.com/optiscaler/OptiScaler/wiki/Manual-Installation)
- [OptiScaler stable configuration](https://github.com/optiscaler/OptiScaler/blob/7534ad00bf9e590eedb99e8dd9fd8c89dae3654f/OptiScaler.ini)
- [OptiScaler v10 supporting-library path configuration](https://github.com/optiscaler/OptiScaler/blob/0e42d5955405360157c22154b4a13fdf3fc196a6/OptiScaler.ini)
- [Nightly legacy backend aliases](https://github.com/optiscaler/OptiScaler/blob/fd6c2870ec420c74bd47a067a7a0b5ba2358e677/OptiScaler/OptiTypes.cpp)
