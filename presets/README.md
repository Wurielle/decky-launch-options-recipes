# App presets

Store each Steam preset at `presets/steam/<app-id>/<preset-id>.json`.
The directory supplies the Steam App ID; the filename matches the preset's
stable `id`. The `name` is the display label and `description` explains the
configuration.

`author` is required and contains the author's GitHub username, without an
`@` prefix or profile URL. It is attribution, not recipe-resolution context
or verified authorship. `notes` is optional and, when present, is an array
of strings for prerequisites or other usage guidance. Keep notes as literal
JSON strings; no TypeScript source or shared notes module is required.

Use the literal `*` app directory (`presets/steam/*/<preset-id>.json`) for
presets available to all Steam apps. Consumers should combine these with an
app's specific presets. Availability does not mean automatic or global
activation; the user still chooses a preset for the current app.

Each entry in `launchOptions` pairs a `recipeId` with a `launchOptionId` from
that recipe. Reference the specific choice ID for a dropdown, not its shared
`valueId`. Do not duplicate recipe commands or embed repository URLs,
owner usernames, or store identifiers for resolving references. The `author`
username is attribution only. The consumer retains the originating store
and uses it to resolve recipe references. Missing options can prompt a recipe
import or re-import; a still-missing reference must not be treated as a
complete preset application.

These are preset source files. Preset discovery, a generated preset catalog,
and application in DLO are not implemented by adding these files.

## Example: Clair Obscur: Expedition 33 — Steam Deck

This is a single worked example of the preset format, not a catalog of games
or presets. Keep this README focused on format and contribution guidance;
do not add a section or repeat the selected options here for every new game
or preset. Add new presets as JSON files in the appropriate app directory.

Steam App ID: [1903340](https://store.steampowered.com/app/1903340/).
Source: [`steam/1903340/steam-deck.json`](steam/1903340/steam-deck.json).

The preset references the following controls from `dlor-optiscaler`:

- OptiScaler Install.
- FSR Override: AMD SDK.
- DX11 upscaler: FidelityFX / FSR4 (`ffx_12`, DX11on12).
- DX12 upscaler: FidelityFX / FSR4 (`ffx`).
- Vulkan upscaler: FidelityFX / FSR4 (`ffx_12`, VKon12).
- FSR4 preset: Performance (`3`).
- VSync: On.
- FrameGen: On.
- FrameGen input: DLSSG via Streamline (`dlssg`).
- FrameGen output: XeFG (`xefg`).

The AMD SDK source supplies the files; the three upscaler selections configure
the requested API paths. This preset does not select a GPU/model override,
force an API, or install ANR. Native Vulkan FidelityFX (`ffx`) is a different
choice from the SDK's DX12 route through VKon12.

The preset records the requested configuration, not verified Steam Deck GPU
compatibility, successful in-game activation, or a performance recommendation.
Game-side DLSS/frame-generation settings and applicable library/hardware
requirements remain separate.
