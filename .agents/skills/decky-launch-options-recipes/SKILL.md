---
name: decky-launch-options-recipes
description: Create or update Decky Launch Options recipe sources for the Wurielle/decky-launch-options plugin. Use when asked to add launch options, recipe entries, dropdown launch options, recipe environment variable merges, or generated recipes.json output, especially in repositories with TypeScript sources under recipes/ and a Recipe type.
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
   - Choose explicit, stable IDs using the semantic hierarchy rules below. Do not recompute IDs from labels at runtime; later wording changes must not silently change saved identities.
   - Declare `environmentVariableMerges` for list-valued environment variables that must combine across active controls or recipes. Follow the merge rules and variable-based IDs below; launch option ID namespacing does not apply to shared merge rules.
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
- `priority`: Prefix order, highest first; omitted priority is `0`. Give another launch option's plugin/add-on Install a **negative** priority lower than its main installer so it runs afterward, including on first launch. Use `-2` when a host update already uses `-1`; use lower values for further dependencies. Apply this to standalone and copied controls, and verify through the actual consumer with reversed import/source order rather than relying on equal-priority tie order. Choose Uninstall ordering separately: if add-on removal needs the host's files/configuration, use a higher priority so removal precedes host uninstall. Keep None/deselection inert.
- `valueId`: Shared dropdown identifier.
- `valueName`: Dropdown choice label.
- `fallbackValue`: Mark the default dropdown choice.

## Environment Variable Merges

The optional recipe-level `environmentVariableMerges` attribute is a list of
`EnvironmentVariableMerge` objects alongside `launchOptions`. Each entry has:

- `id`: Stable identity of the variable's merge rule. Include an explicit ID in maintained recipes even though the type permits omission and Decky Launch Options can generate one.
- `name`: Exact, case-sensitive environment variable name, such as `TOOL_CONFIG`.
- `delimiter`: Literal separator expected by the program reading the variable. `''` concatenates values directly; it does not disable merging.

Add a rule when independently active options contribute values to the same
list-valued variable, including options supplied by other recipes or the user's
launch command. A recipe with only one assignment may still need a rule for
cross-recipe composition. For example, `WINEDLLOVERRIDES` entries join with `;`,
and `MANGOHUD_CONFIG` settings join with `,`. Check the consumer's syntax before
choosing a delimiter; the `,` inside a Wine value such as `dxgi=n,b` separates
load modes, not DLL override entries.

Repeated assignments alone do not imply merging. Scalar switches, scale factors,
file paths, and alternative values of one dropdown must retain replacement
semantics. For example, do not merge `PROTON_USE_XALIA`, `QT_SCALE_FACTOR`, or
individual `OptiScaler_*` settings. Merge rules join whole values; they do not
resolve conflicting settings or deduplicate entries.

```ts
import type { Recipe } from './shared/types.js'

const recipe = {
    name: 'Example Tool',
    launchOptions: [
        {id: 'example-tool-overlay', on: 'TOOL_CONFIG="overlay=1"'},
        {id: 'example-tool-fps-limit', on: 'TOOL_CONFIG="fps_limit=60"'},
    ],
    environmentVariableMerges: [
        {id: 'tool-config', name: 'TOOL_CONFIG', delimiter: ','},
    ],
} satisfies Recipe

export default recipe
```

With both controls active in this order, the rule combines the values as
`TOOL_CONFIG="overlay=1,fps_limit=60"`. The generator preserves the list in
`recipes.json` and resolves `{{env:VARIABLE_NAME}}` placeholders in its string
fields. Omit the attribute when no rule is needed. Publishing the attribute
requires consumer support to apply it; check the importer before claiming that
recipe rules are installed, and keep consumer changes within the requested scope.

### Merge Rule IDs

Merge rules identify environment variables globally, unlike launch option IDs,
which identify controls within a recipe's namespace.

- First reuse the ID already used for that exact variable by Decky Launch Options or another recipe. Its defaults include `winedlloverrides` for `WINEDLLOVERRIDES` and `mangohud-config` for `MANGOHUD_CONFIG`.
- For a new variable, choose an explicit lowercase hyphen-case ID from its technical name: lowercase it and replace underscores with hyphens. For example, `TOOL_CONFIG` becomes `tool-config` and `TOOL_SEARCH_PATH` becomes `tool-search-path`. Keep conventional tokens intact; `WINEDLLOVERRIDES` remains `winedlloverrides`.
- Do not add the recipe name, option/feature name, dropdown value, delimiter, version, or an `env-merge` prefix. `reframework-winedlloverrides`, `wine-dll-override-dxgi`, and `tool-config-comma` identify incidental context rather than the shared variable rule.
- Keep IDs stable when labels or recipe contents change. Write the ID explicitly instead of generating it from display text. Do not reuse an existing ID for a different case-sensitive variable name; check for collisions after normalization and choose a distinct explicit technical qualifier if necessary.
- All recipes declaring the same variable must use the same ID and delimiter. Declare the variable only once per recipe, and check that unrelated variables do not share an ID. Reuse a shared typed constant under `recipes/shared/` when several recipes need the same rule, as with `wineDllOverridesMerge`.
- When copying controls into another recipe, namespace the launch option's `id` and `valueId` as described below, but preserve a shared merge rule's identity. Include the rules required by the copied controls; do not create a new merge ID per destination recipe.

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
- Whenever a script creates a log, keep at most the 10 newest logs in that script's log folder, including the new log. Delete all excess logs oldest first by filename timestamp. Apply the limit separately to each folder, including the shared launcher's `~/.dlor/logs/run/`. Only remove regular `.log` files in that folder; leave symlinks, subdirectories, unrelated files, and other log folders untouched.
- Logging must be best-effort: failure to create, write, or prune a log must not stop the script or later launch commands. Report retention cleanup failures as warnings. Keep console diagnostics available; when using GNU `tee`, use `--output-error=warn` so it keeps consuming output if a destination fails.
- Stop dependent installation steps when their prerequisites fail and preserve a nonzero script exit status. Keep cleanup steps independent. The launch wrapper must still run subsequent commands and the game's `%command%` after an auxiliary script fails (for example, `script; exec "$@"`, rather than joining the game launch with `&&`).
- Keep logging and retention cleanup self-contained in scripts downloaded individually. Test successful and failed runs, cache reuse, unavailable logging, and game-launch continuation with offline fixtures. For retention, cover the 10-log boundary, an existing backlog, preservation of unrelated files and folders, and continued execution after deletion failures.

Use this retention block immediately after creating the log and redirecting output
through `tee`, inside the successful logging-setup branch and before enabling
`set -Eeuo pipefail`. `log_dir` must be the current script's log folder. The
subshell keeps the locale, glob settings, and temporary variables local to cleanup.

```bash
# Timestamped filenames sort oldest first; keep the latest 10 per folder.
(
    export LC_ALL=C
    shopt -s nullglob
    logs=()
    for candidate in "$log_dir/"*.log; do
        if [[ -f "$candidate" && ! -L "$candidate" ]]; then
            logs+=("$candidate")
        fi
    done
    excess=$(( ${#logs[@]} - 10 ))
    if (( excess > 0 )); then
        rm -f -- "${logs[@]:0:excess}" ||
            printf 'Warning: could not remove old logs in %s; continuing.\n' "$log_dir" >&2
    fi
)
```

## Updating Existing Installations

- Inspect the downloaded archive, the installed files, and the application's dependency search paths. Preserving a DLL in its old location does not ensure a new version loads it.
- Establish which source should supply each class of file. When the requested policy is to retain an existing tool's supporting DLLs while updating its main component, overlay those supporting DLLs generally (including subfolders), then install the updated main component last. Avoid narrowing a general overwrite policy to the files involved in one reported failure. Preserve configuration and keep the download cache unchanged.
- Keep alternative variant bundles and renamed copies of the main component out of dependency overlays. Resolve the selected variant from the tool's configuration or manifest. Match Windows dependency paths case-insensitively when installing on Linux.
- Track files copied by the updater. Remove stale copies only when their hashes still match that record; retain replacements supplied by the update and files changed by the user or another mod.
- Test copy precedence, subfolders, variant selection, cache reuse, logging, parser compatibility, and launch continuation. Include an arbitrary supporting DLL to check that the policy is general, and update fixtures when archive layouts change.
- For on-device validation, use temporary game folders with the installed Launch Options parser and real runtime/dependencies. Distinguish verified file hashes and test-command continuation from actual gameplay or confirmation that a feature works in-game.

## ID Convention

Define IDs as stable paths through a control's logical scope:

`<namespace>[-<feature-or-operation>][-<subsystem-or-target>][-<setting>]`

- Start with the owning tool or recipe namespace, then order the applicable parts from broad to specific. Include the feature or operation, any backend/subsystem/target that distinguishes the control, and the setting being changed. A main tool toggle can use its namespace alone. Use the same component order throughout a related family of controls.
- Include each meaningful concept once. An operation can be a compound such as `library-override`; its target follows it. Omit redundant context, including a file extension already identified by the operation. Examples: `tool-library-override-module` and `tool-renderer-backend-preset` are complete control bases.
- Use lowercase hyphen-case and explicit technical tokens. Preserve conventional acronyms and version-number tokens that identify a single concept. Derive the structure from what the control does, using its label, configuration assignment, and neighboring controls as evidence. Labels can reorder words or omit context supplied by the UI; IDs do not need to reproduce label word order, punctuation, or spacing.
- A regular option uses the control base as its `id`, with no `valueId`. A dropdown uses the control base as its shared `valueId`, and `<control-base>-<value-id>` as each choice's `id`, including `none`. For example, `tool-renderer-backend-preset` has choices `tool-renderer-backend-preset-none` and `tool-renderer-backend-preset-high`. Define stable value suffixes explicitly; they identify choices independently of cosmetic label changes.
- Keep the complete base identical in a dropdown's `valueId` and choice IDs. Put only choice-specific information in the suffix. Check that the resulting IDs are unique and that unrelated controls do not share a `valueId`.
- When importing options into another recipe as independent controls, copy them with the destination `group` and a destination namespace on **both** `id` and any existing `valueId`, for example `<destination>-<source-id>`. Changing only `group` leaves identities shared and can overwrite controls or link dropdowns. Preserve source objects and leave `valueId` absent on regular options.
- Preserve existing IDs that meet these rules. Flag missing logical scope, ambiguous or colliding identities, inconsistent family structure, and mismatched dropdown bases. Label differences alone do not justify renaming. Honor explicit user-requested naming changes; when correcting existing IDs, regenerate the catalog and explain that saved controls with old IDs need replacement because re-importing a new ID does not update or delete the old one.
- Model installation/removal as an ordered **None / Install / Uninstall** dropdown, not a Boolean toggle with uninstall in `off`. None is inert and the only fallback; all choices have empty `off` and `enableGlobally: false`. Put each action's runner call only in its own `on` field. Deselecting an action must not uninstall anything.
- OptiScaler ANR FrameGen uses `valueId: 'optiscaler-framegen-anr'` and exactly `optiscaler-framegen-anr-none`, `optiscaler-framegen-anr-install`, and `optiscaler-framegen-anr-uninstall`. Verify exact IDs, ordering, defaults and selected/deselected behavior through the real consumer; retain this user-defined hierarchy when refreshing shared guidance.

## Dropdown Defaults

Every dropdown must include a `None` option as its only fallback/default choice.

- Give `None` empty `on`, empty `off`, and `fallbackValue: true` so it preserves user-defined application settings.
- Other choices, including `Auto` or tool-specific reset/default mechanisms, may be available for explicit selection but must not be the fallback/default. Their launch options can override user-defined application settings.

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
    name: 'Tool Config Mode',
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
- Confirm list-valued variables that combine across independent controls or recipes have merge declarations with the consumer's delimiter, and scalar or mutually exclusive values remain unmerged.
- Confirm merge IDs identify variables, reuse existing identities, and have consistent names and delimiters across recipes, with no duplicate variable rules within a recipe or ID collisions between different variables.
- Confirm control IDs follow a complete, consistent namespace-to-setting hierarchy, with no missing or redundant scope. Check their meaning against labels and configuration behavior rather than requiring literal label-slug equality.
- Confirm dropdown IDs append explicit, stable value suffixes to their exact shared `valueId`, with unique IDs and no unrelated dropdowns sharing a base.
- For independently imported controls, confirm the destination group and namespace are applied to both ID fields, and that source/destination IDs and dropdown `valueId`s do not overlap.
- Confirm every dropdown includes `None` with empty `on` and `off` as its only fallback/default choice.
- Confirm `%command%` is present for wrappers and absent for pure environment-variable options.
- Confirm every `curl` command used by a Steam launch option is prefixed with the shared `hostRuntime` value.
- Confirm artifact downloads reuse a versioned cache and recover from invalid archives.
- Confirm every recipe script logs to the required per-recipe, per-script timestamped path, captures errors, and leaves later launch commands runnable on failure.
- Confirm `recipes.json` was generated by the repo command, not edited manually.
- Run the repo's recipe build/check command and report any failure clearly.
