---
name: decky-launch-options-recipes
description: Create or update Decky Launch Options recipe source files for the Wurielle/decky-launch-options plugin. Use when asked to add launch options, recipe entries, dropdown launch options, or generated recipes.json output for Decky Launch Options, especially in repositories with recipes/*.ts and a Recipe type.
---

# Decky Launch Options Recipes

Use this skill to add or update recipes for the Decky Launch Options plugin.

## Workflow

1. Inspect the repository before editing:
   - Read `README.md`, `recipes/types.ts`, `package.json`, and similar existing recipe files.
   - Treat `recipes.json` as generated output. Do not edit it by hand.
   - Prefer matching the best existing local example. In `decky-launch-options-recipes`, `recipes/mangohud.ts` is the model for dropdowns.

2. Create or update one source recipe file under `recipes/`.
   - Use a hyphen-case file name, for example `mangohud.ts` or `lossless-scaling.ts`.
   - Export exactly one default object satisfying `Recipe`.
   - Import the type with the existing repo style, commonly:

```ts
import type { Recipe } from './types.js'

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

   - Prefer programmatic generation for repeated or patterned launch options, especially dropdowns with numeric values, DLL lists, presets, backends, or other structured choices.
   - Import `LaunchOption` along with `Recipe` when building `launchOptions` from arrays or helper functions.
   - Keep source arrays compact and ordered the same way the UI should display values, then use `map` or `flatMap` to produce `LaunchOption[]`.
   - Use small helper functions for repeated command fragments, such as quoted environment-variable assignments.
   - Do not generate IDs from user-facing labels when values need stable compatibility; define explicit `id` values for non-trivial choices.

3. Build or check recipes using the repo script, usually `pnpm recipes:build` or `pnpm recipes:check`.
   - The build type-checks recipe entries before writing generated recipe output.
   - If the build generates `recipes.json`, include that generated diff.
   - Do not manually reorder or patch generated recipes.

## Generated Recipes File

Never manually update `recipes.json`. Add or change entries only in `recipes/*.ts`, then run the repo's recipe build/check command so TypeScript validates the recipe before `recipes.json` is generated. This keeps invalid launch option entries from being copied directly into the generated file.

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
- Give the default dropdown entry an empty `on`, empty `off`, and `fallbackValue: true` when "None" or default behavior means no launch option should be applied.

## Dropdown Pattern

For mutually exclusive choices, prefer a compact value array plus a typed `map`:

```ts
import type { LaunchOption, Recipe } from './types.js'

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
- Confirm `recipes.json` was generated by the repo command, not edited manually.
- Run the repo's recipe build/check command and report any failure clearly.
