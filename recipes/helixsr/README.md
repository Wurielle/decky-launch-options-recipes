# HelixSR through OptiScaler (experimental)

**Enable HelixSR (OptiScaler DX12), then launch the game.** The toggle performs
its own first-run setup, dependency installation and configuration. There are no
terminal commands, manually built DLLs, edited paths, or separate OptiScaler
toggles required for ordinary use. It is disabled globally by default.

Refetch and re-import the updated PR recipes, including any existing OptiScaler
entry: its updated disabled command must not uninstall a dependency HelixSR needs.

## First launch

The recipe downloads the complete, checksum-verified HelixSR 1.9.0 release and
prepares its network locally using the unmodified upstream Python builder. A
first-run GUI asks for explicit consent before acquiring NVIDIA's DLSS component
under NVIDIA's license. Canceling leaves the feature inactive and launches the
game normally. It does not accept license terms silently.

Python/numpy and Microsoft's shader compiler are prepared in a per-user cache
when needed. Shader compilation uses Proton/Wine and an isolated build prefix,
not the game's existing prefix. No sudo, system package installation or global
pip changes are made. The initial build can take several minutes; later launches
reuse validated cached outputs.

The selected game's original launch arguments identify its executable. If target
selection is genuinely ambiguous, the helper asks through the GUI rather than
patching every executable. A compatible existing OptiScaler installation is
reused; otherwise the recipe installs its own verified dependency without
replacing unknown mods or injectors.

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
continue the original game command after setup cancellation or failure; check
the stage log rather than assuming HelixSR was enabled.

Offline tests exercise orchestration, fixture-backed builds, cache integrity,
dependency ownership, restoration, interruptions and parser compatibility. They
do not demonstrate neural-network execution, Steam Deck GUI behavior or gameplay
performance. Those remain on-device verification requirements.

## References

- [HelixSR 1.9.0](https://github.com/lonewolf0622/HelixSR/releases/tag/v1.9.0)
- [NVIDIA DLSS license](https://github.com/NVIDIA/DLSS/blob/v310.7.0/LICENSE.txt)
- [OptiScaler manual installation](https://github.com/optiscaler/OptiScaler/wiki/Manual-Installation)
- [OptiScaler stable configuration](https://github.com/optiscaler/OptiScaler/blob/7534ad00bf9e590eedb99e8dd9fd8c89dae3654f/OptiScaler.ini)
- [Nightly legacy backend aliases](https://github.com/optiscaler/OptiScaler/blob/fd6c2870ec420c74bd47a067a7a0b5ba2358e677/OptiScaler/OptiTypes.cpp)
