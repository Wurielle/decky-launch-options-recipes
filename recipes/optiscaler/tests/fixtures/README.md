# Versioned OptiScaler configuration fixtures

These are upstream configuration contracts, not synthetic game files or evidence of native GPU execution. INI line endings are normalized to LF; setting content is unchanged.

- `stable-0.9.5.ini`: [`OptiScaler.ini` at v0.9.5](https://github.com/optiscaler/OptiScaler/blob/90d9568d576d93ebb2d6c1c207596d21e9900651/OptiScaler.ini).
- `nightly-10.ini`: [`OptiScaler.ini` at the DLOR-pinned nightly-20261025 source](https://github.com/optiscaler/OptiScaler/blob/539c9a1ecd2c37bee1980d0f0645919cab837855/OptiScaler.ini).
- Both INIs are from OptiScaler, licensed under GPL-3.0; the upstream license is retained in `OptiScaler-LICENSE`.
- `legacy_config.py`: the unchanged implementation of [`defaults/assets/update-optiscaler-config.py`](https://github.com/xXJSONDeruloXx/Decky-Framegen/blob/96eb17b0a9f2cfd2b00ad082bef893f4efc229f7/defaults/assets/update-optiscaler-config.py), with an attribution/license header added. This is the legacy environment-to-INI consumer, not DLOR's newer resolver. Its BSD-3-Clause notice is retained in the file.

The stable FG value assertions follow the native `Config.cpp` whitelist at the stable revision. Stable upscaler values follow `upscalers/FeatureProvider_Dx11.cpp`, `FeatureProvider_Dx12.cpp` and `FeatureProvider_Vk.cpp`; accepting arbitrary strings in the INI reader does not establish backend selection. Nightly selector assertions in `test_settings.py` follow `State.h` and `OptiTypes.cpp` at the nightly revision. These version-specific checks deliberately complement, rather than replace, the INI-key and updater round trips.
