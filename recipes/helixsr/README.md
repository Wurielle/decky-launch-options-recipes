# HelixSR through OptiScaler (experimental)

Opt-in **DX12 upscaling only**, using an existing OptiScaler installation and
locally prepared [HelixSR 1.9.0](https://github.com/lonewolf0622/HelixSR/releases/tag/v1.9.0)
DLLs. This recipe does not install OptiScaler, build HelixSR, download NVIDIA
components, replace a game's original FSR DLLs, or configure frame generation.
It requires Python 3 on the host, as does the existing fgmod setup.

## Prepare once

1. Follow HelixSR's official setup and license prompts to build its network locally.
   Keep the complete upstream installation and license files. Do not distribute
   the resulting network-containing DLLs. The recipe neither accepts licenses
   on your behalf nor changes or executes upstream's scripts.
2. Put that installation at `~/.local/share/helixsr`, or add a custom DLO launch
   option containing `HELIXSR_DIR="/absolute/path/to/HelixSR-1.9.0"`. This is a
   recipe-specific input, not a native HelixSR setting. Point to the directory
   containing `fsr3-drop-in`, not to the DLL itself. Both locally prepared files
   must exist and be nonempty:
   - `fsr3-drop-in/amd_fidelityfx_dx12.dll`
   - `fsr3-drop-in/amd_fidelityfx_upscaler_dx12.dll`
3. Enable the existing **OptiScaler** option for a compatible single-player DX12
   game. This recipe runs after OptiScaler and its optional nightly updater.
4. Import the **HelixSR** recipe, enable **HelixSR (OptiScaler DX12)** for that
   game, and launch. It is disabled globally by default.

Use only the OptiScaler injection route for this test; do not also install
HelixSR's native FSR replacement into the game. Do not assume DLL injection is
safe with anti-cheat. Steam Deck performance and gameplay compatibility still
need on-device testing.

## What activation changes

The helper finds one `OptiScaler.ini` under the selected game's install directory.
If there are multiple configurations, set a custom DLO option such as
`HELIXSR_CONFIG="Binaries/Win64/OptiScaler.ini"` to select one explicitly. Absolute
paths are also accepted, but the file must remain inside this game. Symlinked
configuration files are refused.

It saves the original values and sets:

```ini
[Upscalers]
Dx12Upscaler=fsr31

[Libraries]
FfxDx12Path=<mapped drive>:/.../fsr3-drop-in/amd_fidelityfx_dx12.dll
FfxDx12SRPath=<mapped drive>:/.../fsr3-drop-in/amd_fidelityfx_upscaler_dx12.dll
```

If `[FSR] UpscalerIndex` exists, it is temporarily set to `0` as well. Missing or
ambiguous required INI keys are reported rather than silently ignored. The
`fsr31` backend value is supported by stable OptiScaler 0.9.4 and remains an
explicit alias for `ffx` in the inspected nightly-20261015 source. New upstream
versions may require retesting.

The helper derives Windows-visible paths from the actual prefix's drive mappings,
using `STEAM_COMPAT_DATA_PATH/pfx/dosdevices` (or `WINEPREFIX/dosdevices` outside
Steam). It does not assume that `Z:` maps to `/`. The files must also be visible
inside the game's Steam runtime/container.

Avoid simultaneously setting other OptiScaler backend/library overrides or
`PRESERVE_INI=false`: another updater can replace the managed values. Explicit
conflicts on a later activation are reported; disable HelixSR to release its
saved settings before selecting another backend.

## Verify on the Deck

- Look for **FSR HelixSR** in OptiScaler's backend menu.
- Check `OptiScaler.log` for the two library override paths and successful loading
  from those paths. A successful game launch alone is not proof: OptiScaler can
  fall back to its normal libraries after a loading failure.
- Recipe diagnostics are in `~/.dlor/logs/helixsr/configure/`; launcher/download
  diagnostics are in `~/.dlor/logs/run/`. Each folder retains its latest 10 logs.
- If configuration or downloads fail, DLOR still launches the game. Read the log
  rather than assuming that HelixSR was activated.

## Disable and restore

Turn **HelixSR (OptiScaler DX12)** off and launch once while OptiScaler is still
installed. The disabled command restores only settings that still match what
this recipe wrote. Unrelated INI edits, changed managed values and deleted keys
are preserved. Turning it off does not delete DLLs, models, or OptiScaler.

The per-game original settings are stored under `~/.dlor/state/helixsr/`. Keep
this state until restoration completes. Removing the imported option without
launching its disabled command does **not** run restoration. If necessary, run:

```sh
STEAM_COMPAT_INSTALL_PATH="/absolute/path/to/game" \
DLOR_HELIXSR_ACTION=off ~/.dlor/run helixsr configure <commit-sha> -- /bin/true
```

Use the pinned commit from the imported option in place of `<commit-sha>`.
Restoration does not require the source DLLs or the Proton prefix. Disable this
recipe before uninstalling OptiScaler or deleting/moving the game's configuration.

## Offline verification

```sh
python3 scripts/test-helixsr.py
```

These tests use explicit nonfunctional DLL fixtures. They validate configuration,
restoration, paths and launch behavior, not shader execution or game compatibility.

## Configuration references

- [HelixSR release setup](https://github.com/lonewolf0622/HelixSR/releases/tag/v1.9.0):
  `setup/helixsr_install.py` documents the manual OptiScaler configuration.
- [OptiScaler 0.9.4 configuration](https://github.com/optiscaler/OptiScaler/blob/7534ad00bf9e590eedb99e8dd9fd8c89dae3654f/OptiScaler.ini)
- [Nightly legacy backend aliases](https://github.com/optiscaler/OptiScaler/blob/fd6c2870ec420c74bd47a067a7a0b5ba2358e677/OptiScaler/OptiTypes.cpp)

The `OptiScaler_Section_Key` environment variables used by the existing recipe
are consumed by fgmod's INI updater, not by OptiScaler itself. They persist on
disk, which is why this recipe uses explicit setting ownership and restoration.
