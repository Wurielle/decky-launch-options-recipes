---
name: decky-launch-options-recipes
description: Create or update Decky Launch Options recipe sources for the Wurielle/decky-launch-options plugin. Use when asked to add launch options, recipe entries, dropdown launch options, or generated recipes.json output, especially in repositories with recipes/<name>.ts or recipes/<name>/index.ts and a Recipe type.
---

# Decky Launch Options Recipes

Use this skill to add or update recipes for the Decky Launch Options plugin.

## Workflow

1. Inspect the repository before editing:
   - Read `README.md`, `recipes/shared/types.ts`, `package.json`, and similar existing recipe files.
   - Read `recipes/shared/host-runtime.ts` when a recipe downloads a script or invokes another host-system command from Steam.
   - Treat `recipes.json` as generated output. Do not edit it by hand.
   - Prefer matching the best existing local example. In `decky-launch-options-recipes`, `recipes/mangohud.ts` is the model for dropdowns.

2. Create or update one recipe source under `recipes/`.
   - Use either `recipes/<name>.ts` or `recipes/<name>/index.ts`. Use the directory form when the recipe has supporting files such as scripts.
   - Use a hyphen-case file or directory name, for example `mangohud.ts`, `lossless-scaling.ts`, or `reframework/index.ts`.
   - Export exactly one default object satisfying `Recipe`.
   - Import the type with the existing repo style, commonly:

```ts
import type { Recipe } from './shared/types.js'

const recipe = {
    name: 'Tool Name',
    launchOptions: [
        {
            id: 'tool-name',
            group: 'Tool Name',
            name: 'Tool Name',
            on: 'tool-wrapper %command%',
            off: '',
            enableGlobally: false,
        },
    ],
} satisfies Recipe

export default recipe
```

   - In a directory index, import the shared type from `../shared/types.js` instead.
   - `recipes/shared/` is reserved for reusable recipe modules and is never loaded as a recipe source.

   - Prefer programmatic generation for repeated or patterned launch options, especially dropdowns with numeric values, DLL lists, presets, backends, or other structured choices.
   - Import `LaunchOption` along with `Recipe` when building `launchOptions` from arrays or helper functions.
   - Keep source arrays compact and ordered the same way the UI should display values, then use `map` or `flatMap` to produce `LaunchOption[]`.
   - Use small helper functions for repeated command fragments, such as quoted environment-variable assignments.
   - Do not generate IDs from user-facing labels when values need stable compatibility; define explicit `id` values for non-trivial choices.
   - Add a top-of-file dropdown fallback policy comment when a recipe intentionally uses a default other than `None`.

3. Build or check recipes using the repo script, usually `pnpm recipes:build` or `pnpm recipes:check`.
   - The build type-checks recipe entries before writing generated recipe output.
   - If the build generates `recipes.json`, include that generated diff.
   - Do not manually reorder or patch generated recipes.

## Generated Recipes File

Never manually update `recipes.json`. Add or change entries only in `recipes/<name>.ts` or `recipes/<name>/index.ts`, then run the repo's recipe build/check command so TypeScript validates the recipe before `recipes.json` is generated. This keeps invalid launch option entries from being copied directly into the generated file.

## Launch Option Fields

Use these fields according to the local `LaunchOption` type:

- `id`: Stable identifier used to update an imported option. Always include it.
- `group`: UI grouping/tab label. Use for related options.
- `name`: Display name. Dropdown choices with the same `valueId` should share the same `name`.
- `on`: Launch option string applied when enabled.
- `off`: Launch option string applied when disabled. Use `''` when no disabled command is needed.
- `enableGlobally`: Whether the option is enabled by default for all games.
- `valueId`: Shared dropdown identifier.
- `valueName`: Dropdown choice label.
- `fallbackValue`: Mark the default dropdown choice.

## Command Rules

- Include `%command%` when an option wraps or modifies the game launch command.
- Put environment variables before `%command%`, for example `MANGOHUD_CONFIG="preset=1"`.
- Put wrapper commands before `%command%`, for example `mangohud %command%`.
- Put game arguments after `%command%` when the option is a game argument.
- Keep `on` and `off` shell-safe for Steam launch options. Preserve quotes where values contain `=` or spaces.
- Any launch option that uses `curl` to fetch a script or other host resource from inside Steam must prefix at least the `curl` command with the shared `hostRuntime` value. This escapes Steam's legacy library environment for the host downloader:

```ts
import { hostRuntime } from './shared/host-runtime.js'

const download = `${hostRuntime} curl -fsSL "https://example.com/script.sh"`
```

- From a directory recipe such as `recipes/<name>/index.ts`, import it from `../shared/host-runtime.js` instead.
- Apply `hostRuntime` only to the auxiliary host commands that need it. Do not wrap the game's `%command%`, which must remain in Steam's intended runtime environment.

## ID Convention

Use predictable, hyphen-case IDs.

- Regular launch option: include the feature/tool name only, for example `mangohud`, `lossless-scaling`, or `proton-ge`.
- Dropdown option: include the feature/tool name, the modified option/config name, and the value.
  - Pattern: `<tool>-<option-or-config-name>-<value>`
  - MangoHud examples:
    - `mangohud-config-preset-none`
    - `mangohud-config-preset-0`
    - `mangohud-fps-limit-60`
- Keep all options in a dropdown on the same `valueId`.

## Dropdown Defaults

Every dropdown should include one fallback/default choice.

- Default to a `None` option with empty `on`, empty `off`, and `fallbackValue: true`.
- Use a non-`None` fallback only when that label corresponds to a tool-specific reset/default mechanism.
- A non-`None` fallback must emit the reset/default launch option in `on` or `off`; do not rename `None` while leaving both `on` and `off` empty.
- When using a non-`None` fallback, add this comment template at the top of the recipe file before imports:

```ts
// Dropdown fallback policy: use "<Fallback label>" instead of "None" because
// <specific launch option mechanism> resets <tool state>, while empty launch
// options would leave <existing tool/config state> unchanged.
```

Use `recipes/optiscaler.ts` as the model: its dropdown fallbacks use `Auto` because `OptiScaler_<Section>_<Option>="auto"` actively resets values that may otherwise persist in `OptiScaler.ini`.

## Dropdown Pattern

For mutually exclusive choices, prefer a compact value array plus a typed `map`:

```ts
import type { LaunchOption, Recipe } from './shared/types.js'

const toolModeValues = [
    {
        id: 'none',
        name: 'None',
        value: null,
        fallbackValue: true,
    },
    {
        id: 'fast',
        name: 'Fast',
        value: 'fast',
    },
] as const

const toolModeOptions: LaunchOption[] = toolModeValues.map((mode): LaunchOption => ({
    id: `tool-config-mode-${mode.id}`,
    group: 'Tool',
    name: 'Tool Mode',
    on: mode.value === null ? '' : `TOOL_MODE="${mode.value}"`,
    off: '',
    enableGlobally: false,
    valueId: 'tool-config-mode',
    valueName: mode.name,
    ...('fallbackValue' in mode && mode.fallbackValue === true ? {fallbackValue: true} : {}),
}))
```

For one-off dropdowns with only a couple of values, inline entries are acceptable. Once the third or fourth nearly identical option appears, switch to arrays and helpers like `recipes/wine.ts`, `recipes/mangohud.ts`, or `recipes/optiscaler.ts`.

## Review Checklist

Before finishing:

- Confirm the recipe compiles against `Recipe`.
- Confirm every launch option has a stable `id`.
- Confirm dropdown IDs include tool, option/config name, and value.
- Confirm each dropdown has one fallback/default choice when appropriate.
- Confirm `%command%` is present for wrappers and absent for pure environment-variable options.
- Confirm every `curl` command used by a Steam launch option is prefixed with the shared `hostRuntime` value.
- Confirm `recipes.json` was generated by the repo command, not edited manually.
- Run the repo's recipe build/check command and report any failure clearly.
