---
name: decky-launch-options-recipes
description: Create or update Decky Launch Options recipe sources for the Wurielle/decky-launch-options plugin. Use when asked to add launch options, recipe entries, dropdown launch options, or generated recipes.json output, especially in repositories with TypeScript sources under recipes/ and a Recipe type.
---

# Decky Launch Options Recipes

Use this skill to add or update recipes for the Decky Launch Options plugin.

## Workflow

1. Inspect the repository before editing:
   - Read `README.md`, `recipes/shared/types.ts`, `package.json`, and similar existing recipe files.
   - Read recipe-specific instructions in comments in the target source and its supporting scripts before editing them.
   - Read `recipes/shared/host-runtime.ts` when a recipe downloads a script or invokes another host-system command from Steam.
   - Treat `recipes.json` as generated output. Do not edit it by hand.
   - Inspect an existing implementation of the same kind of option before choosing a pattern.

2. Create or update one recipe source under `recipes/`.
   - Use either `recipes/<name>.ts` or `recipes/<name>/index.ts`. Use the directory form when the recipe has supporting files such as scripts.
   - Use a hyphen-case file or directory name, such as `tool-name.ts` or `tool-name/index.ts`.
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
   - Keep recipe-specific instructions beside the relevant code as comments, not in this skill. Add or update comments when an implementation depends on non-obvious command ordering, overwrite rules, archive layout, or variant selection. Explain the constraint and its reason; point to supporting script comments from the recipe source when needed instead of duplicating them.

3. Build or check recipes using the repo script, usually `pnpm recipes:build` or `pnpm recipes:check`.
   - The build type-checks recipe entries before writing generated recipe output.
   - If the build generates `recipes.json`, include that generated diff.
   - Do not manually reorder or patch generated recipes.

## Generated Recipes File

Never manually update `recipes.json`. Add or change entries only in `recipes/<name>.ts` or `recipes/<name>/index.ts`, then run the repo's recipe build/check command so TypeScript validates the recipe before `recipes.json` is generated. This keeps invalid launch option entries from being copied directly into the generated file.

Downloaded scripts use commit-pinned URLs generated from `RECIPE_COMMIT_SHA`. Changing a supporting script or deploying the plugin does not update already imported launch options. When diagnosing a Deck failure, check the saved option's URL and parsed command. After publishing script changes, confirm the generated recipes reference the new revision; refetching and re-importing updates the saved options.

## Launch Option Fields

Use these fields according to the local `LaunchOption` type:

- `id`: Stable identifier used to update an imported option. Always include it.
- `group`: UI grouping/tab label. Use for related options.
- `name`: Display name. Dropdown choices with the same `valueId` should share the same `name`.
- `on`: Launch option string applied when enabled.
- `off`: Launch option string applied when disabled. Use `''` when no disabled command is needed.
- `enableGlobally`: Whether the option is enabled by default for all games.
- `priority`: Prefix order, highest first. Order dependent wrappers so installation runs before an update that relies on its files.
- `valueId`: Shared dropdown identifier.
- `valueName`: Dropdown choice label.
- `fallbackValue`: Mark the default dropdown choice.

## Command Rules

- Include `%command%` when an option wraps or modifies the game launch command.
- Put environment variables before `%command%`, for example `TOOL_CONFIG="preset=1"`.
- Put wrapper commands before `%command%`, for example `tool-wrapper %command%`.
- Put game arguments after `%command%` when the option is a game argument.
- Keep `on` and `off` shell-safe for Steam launch options. Preserve quotes where values contain `=` or spaces.
- Any launch option that uses `curl` to fetch a script or other host resource from inside Steam must prefix at least the `curl` command with the shared `hostRuntime` value. This escapes Steam's legacy library environment for the host downloader:

```ts
import { hostRuntime } from './shared/host-runtime.js'

const download = `${hostRuntime} curl -fsSL "https://example.com/script.sh"`
```

- From a directory recipe such as `recipes/<name>/index.ts`, import it from `../shared/host-runtime.js` instead.
- When piping a downloaded script into a shell, also prefix the receiving shell with `hostRuntime`: `${hostRuntime} curl ... | ${hostRuntime} bash -s -- ...`. Each side of a pipeline inherits its environment separately; wrapping only the downloader leaves the script’s internal `curl` and other host tools in Steam’s incompatible library environment.
- Apply `hostRuntime` only to the auxiliary host commands that need it. Do not wrap the game's `%command%`, which must remain in Steam's intended runtime environment.
- Clear `LD_PRELOAD` for auxiliary host commands inside a subshell: `bash -c '(unset LD_PRELOAD; <host downloader> | <host shell>); exec "$@"' -- %command%`. Steam's runtime switch does not clear the overlay preload. The subshell preserves the game's original environment. Do not start the quoted shell body with `LD_PRELOAD=...`: Decky Launch Options' parser can misclassify the entire body as an environment assignment and remove it from `bash -c`. Validate generated wrappers through the actual Launch Options parser as well as Bash, including game continuation after helper failure.
- Downloaded host scripts must also clean their own environment with shell builtins before logging or other subprocesses: unset `LD_PRELOAD`, and when `STEAM_RUNTIME` is an absolute path, restore `LD_LIBRARY_PATH` from `SYSTEM_LD_LIBRARY_PATH` (or empty), restore `PATH` from `SYSTEM_PATH` (or the standard host paths), and unset `STEAM_RUNTIME`. Keep this bootstrap self-contained and compatible with `bash -s`. Test direct execution under Steam's environment as well as the generated wrapper.
- Check metadata downloads for success before parsing JSON, so a network or loader failure reports its actual cause without a secondary empty-input parser traceback.

## Artifact Caching and Script Logging

- Every recipe or skill that downloads release artifacts must cache them.
- Key the cache by release/version and asset name. Reuse valid extracted files first, then cached archives; only download missing or invalid artifacts. Download and extract through temporary paths, validate required files before promoting them into the cache, and clean up temporary files on failure. Preserve existing cache-directory overrides.
- Every recipe script, including uninstallers, must create a separate log per invocation at `~/.dlor/logs/<recipe-name>/<script-name>/<timestamp>.log`. Use the recipe directory name and script filename without its extension, and a timestamp with subsecond precision. Define these names explicitly rather than deriving them from `$0`: Steam runs downloaded scripts through `bash -s`.
- Start logging before argument validation or other work. Capture stdout and stderr, including subprocess diagnostics, unexpected shell errors, cleanup errors, and the final exit status. Do not discard tool output that may contain error details.
- Logging must be best-effort: failure to create or write a log must not stop the script or later launch commands. Keep console diagnostics available; when using GNU `tee`, use `--output-error=warn` so it keeps consuming output if a destination fails.
- Stop dependent installation steps when their prerequisites fail and preserve a nonzero script exit status. Keep cleanup steps independent. The launch wrapper must still run subsequent commands and the game's `%command%` after an auxiliary script fails (for example, `script; exec "$@"`, rather than joining the game launch with `&&`).
- Keep logging self-contained in scripts downloaded individually. Test successful and failed runs, cache reuse, unavailable logging, and game-launch continuation with offline fixtures.

## Updating Existing Installations

- Inspect the downloaded archive, the installed files, and the application's dependency search paths. Preserving a DLL in its old location does not ensure a new version loads it.
- Establish which source should supply each class of file. When the requested policy is to retain an existing tool's supporting DLLs while updating its main component, overlay those supporting DLLs generally (including subfolders), then install the updated main component last. Avoid narrowing a general overwrite policy to the files involved in one reported failure. Preserve configuration and keep the download cache unchanged.
- Keep alternative variant bundles and renamed copies of the main component out of dependency overlays. Resolve the selected variant from the tool's configuration or manifest. Match Windows dependency paths case-insensitively when installing on Linux.
- Track files copied by the updater. Remove stale copies only when their hashes still match that record; retain replacements supplied by the update and files changed by the user or another mod.
- Test copy precedence, subfolders, variant selection, cache reuse, logging, parser compatibility, and launch continuation. Include an arbitrary supporting DLL to check that the policy is general, and update fixtures when archive layouts change.
- For on-device validation, use temporary game folders with the installed Launch Options parser and real runtime/dependencies. Distinguish verified file hashes and test-command continuation from actual gameplay or confirmation that a feature works in-game.

## ID Convention

Use predictable, hyphen-case IDs.

- Regular launch option: include the feature/tool name only, for example `tool-name`.
- Dropdown option: include the feature/tool name, the modified option/config name, and the value.
  - Pattern: `<tool>-<option-or-config-name>-<value>`
  - Examples: `tool-config-preset-none`, `tool-config-preset-fast`, `tool-fps-limit-60`.
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

For example, an `Auto` fallback is appropriate when `TOOL_SETTING="auto"` actively resets a persisted setting; an empty command would leave that setting unchanged.

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

For one-off dropdowns with only a couple of values, inline entries are acceptable. Once the third or fourth nearly identical option appears, switch to arrays and helpers.

## Review Checklist

Before finishing:

- Confirm the recipe compiles against `Recipe`.
- Confirm every launch option has a stable `id`.
- Confirm dropdown IDs include tool, option/config name, and value.
- Confirm each dropdown has one fallback/default choice when appropriate.
- Confirm `%command%` is present for wrappers and absent for pure environment-variable options.
- Confirm every `curl` command used by a Steam launch option is prefixed with the shared `hostRuntime` value.
- Confirm artifact downloads reuse a versioned cache and recover from invalid archives.
- Confirm every recipe script logs to the required per-recipe, per-script timestamped path, captures errors, and leaves later launch commands runnable on failure.
- Confirm `recipes.json` was generated by the repo command, not edited manually.
- Run the repo's recipe build/check command and report any failure clearly.
