# Decky Launch Options Recipes

Decky Launch Options Recipes is a collection of launch options recipes for
the [Decky Launch Options](https://github.com/Wurielle/decky-launch-options) plugin.

This plugin is mainly made for debugging purposes but can be used to allow easy installation of launch options in
coordination with [Decky Launch Options](https://github.com/Wurielle/decky-launch-options).

By default, the source of the recipes is the generated `recipes.json` file in this repo. You can point the recipes
source to a different file hosted anywhere so you can easily create your own set of launch options recipes.

> Make sure you **TRUST** the source of the recipes if you point to a different file. Decky Launch Options will ask you
> to review any launch option added but to be safe, only point to a `recipes.json` file you trust or that you can host
> and
> review yourself.

Recipe sources live in either `recipes/<name>.ts` or `recipes/<name>/index.ts`, and each source exports exactly one typed
recipe. The directory form can keep supporting files beside the recipe. `recipes.json` is generated from those sources
automatically, so there is no registry file to maintain. Shared recipe code and types live in `recipes/shared/`, which
the generator never treats as a recipe source.

The [Non-Steam recipe](recipes/non-steam/README.md) provides app scaling and
app-size dropdowns using native toolkit settings and a window sizing helper.

Here's what the generated recipes look like:

```json
[
  {
    "name": "OptiScaler",
    "launchOptions": [
      {
        "id": "optiscaler",
        "group": "OptiScaler",
        "name": "OptiScaler",
        "on": "~/fgmod/fgmod %command%",
        "off": "~/fgmod/fgmod-uninstaller.sh %command%",
        "enableGlobally": false
      },
      {
        "id": "optiscaler-dx11-upscaler",
        "group": "OptiScaler",
        "name": "OptiScaler Dx11 FSR4",
        "on": "OptiScaler_Upscalers_Dx11Upscaler=fsr31_12",
        "off": "",
        "enableGlobally": true
      },
      {
        "id": "optiscaler-dx12-upscaler",
        "group": "OptiScaler",
        "name": "OptiScaler Dx12 FSR4",
        "on": "OptiScaler_Upscalers_Dx12Upscaler=fsr31",
        "off": "",
        "enableGlobally": true
      }
    ]
  },
  {
    "name": "Lossless Scaling",
    "launchOptions": [
      {
        "id": "lossless-scaling",
        "name": "Lossless Scaling",
        "on": "~/lsfg %command%",
        "off": "",
        "enableGlobally": false
      }
    ]
  }
]
```

Where the collection is an array of recipes containing an array of launch options.

I reserve the right to update the recipes at any time for my own testing. I recommend cloning this repo or adding the
example above to a gist and point the recipes source to it inside the plugin.

## Installation

* [Download](https://github.com/Wurielle/decky-launch-options-recipes/releases) `decky-launch-options-recipes.zip` and
  import it
  in Decky Loader
* Or copy the link to `decky-launch-options-recipes.zip` and import it in Decky Loader

> **Note:** You might need to enable `Developer mode` in the Decky Loader settings

## Contributing

I welcome contributions!

If you want to create a recipe, add either `recipes/<my-recipe-name>.ts` or `recipes/<my-recipe-name>/index.ts`. Export a
single object that satisfies the `Recipe` type. Use the directory form when the recipe has supporting files such as
scripts.

### Remote script launcher

The plugin installs `~/.dlor/run`, a utility for downloading and running remote scripts
hosted in the same repository as `recipes.json`. Use it in launch options:

```sh
~/.dlor/run <recipe-name> <script-name> [commit-sha] -- %command%
```

The script lives at `recipes/<recipe-name>/scripts/<script-name>.sh`; omit `.sh`
from the command. A full commit SHA pins the version and enables command caching
under `~/.dlor/cache/commands/`. Cache keys include the exact repository, full SHA,
recipe, and script. Warm pinned commands run without a network request, including
offline. Before execution the runner checks SHA-256 on a private copy; missing or
corrupt entries are downloaded again. Failed, empty, or invalid-shell downloads
are never executed or published. Per-key locks serialize acquisition, and complete
script/checksum pairs are published by an atomic directory rename.

The checksum is recorded from the first successful HTTPS download. It detects
later cache corruption, but is **not independent authentication** of that first
download and does not protect against someone able to replace both the script and
its checksum. Cache directories must belong to the current user; cache-internal
symlinks are not followed. The runner uses Bash, curl, GNU coreutils, and `flock`.

Omitting the SHA always downloads from the mutable `dev` branch, without cache
reuse or stale/offline fallback. In both modes the game starts even if acquisition
or the helper fails, with its original arguments and Steam environment.

This behavior requires updating the plugin that installs `~/.dlor/run`; merely
refetching/importing recipes does not update an already installed runner. Existing
pinned launch options work unchanged once the updated runner is installed. Cached
commands have no expiry; removing `~/.dlor/cache/commands/` between launches clears
them without changing recipe payload caches.

In recipe sources, use `remoteScript(recipe, script)` from
`recipes/shared/remote-script.ts` to generate a pinned command.
For forks, prefix the command with `DLOR_REPOSITORY="owner/repository"`;
the generator does this automatically for builds from another repository.

Runner logs are saved to `~/.dlor/logs/run/`.

### Remote Steam UI testing

With SSH access to the test device and Steam's CEF debugging endpoint available
on its loopback port 8080, install dependencies and use Playwright to control the
running Steam UI:

```sh
CONSOLE_SSH_HOST=<ssh-alias> pnpm console:ui pages
CONSOLE_SSH_HOST=<ssh-alias> pnpm console:ui snapshot
CONSOLE_SSH_HOST=<ssh-alias> pnpm console:ui screenshot
CONSOLE_SSH_HOST=<ssh-alias> pnpm console:ui click-text "Manage recipes source"
```

The helper opens a temporary SSH tunnel and disconnects after each command without
closing Steam. Screenshots default to `.generated/console-ui/latest.png`.
Set `CONSOLE_UI_PAGE` to another title from `pages`, or `CONSOLE_CDP_PORT` if needed.
Run `pnpm console:ui help` for mouse, keyboard, text entry, and diagnostic commands.
Keep screenshots and device credentials out of commits. Run offline frontend
regression checks with `pnpm test:frontend`.

For a real paste regression check, open **Manage recipes source** and copy a recipe
URL on the test device, then run `pnpm test:console-clipboard` with the same SSH
host setting. It clears the field, clicks the installed plugin's Paste button,
checks non-empty saved text, captures the result, and restores the original source.

### Build-time environment variables

Recipe string fields can use `{{env:VARIABLE_NAME}}` placeholders. The recipe generator replaces each placeholder with
the matching environment variable and fails when a required variable is missing.

The GitHub workflow provides the source repository owner, repository name, and commit as
`RECIPE_REPOSITORY_OWNER`, `RECIPE_REPOSITORY_NAME`, and `RECIPE_COMMIT_SHA`. This allows recipes to reference files
from the exact repository revision that generated `recipes.json`. Pull requests generate the file for validation; the
push workflow commits the final generated file because its contents depend on the source commit SHA.
