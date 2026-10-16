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
from the command. It is downloaded on every launch, then the game starts, even if
the script fails. A full commit SHA is recommended to pin the version;
leaving it out uses the `dev` branch.

In recipe sources, use `remoteScript(recipe, script)` from
`recipes/shared/remote-script.ts` to generate a pinned command.
For forks, prefix the command with `DLOR_REPOSITORY="owner/repository"`;
the generator does this automatically for builds from another repository.

Runner logs are saved to `~/.dlor/logs/run/`.

The default helper receives the game's install path as its only argument. It runs
in the host-tool environment; exporting a variable there does not change the
later game process.

For a script that must wrap the game itself, use the invocation-scoped option:

```sh
~/.dlor/run --wrapper <recipe-name> <script-name> <commit-sha> -- %command%
```

Generate this with `remoteScript(recipe, script, 'wrapper')`. The runner fully
downloads the script, removes its temporary download, and starts the wrapper with
the original game arguments and Steam environment. `DLOR_SCRIPT_REVISION` contains
the validated source revision. No wrapper source is embedded in the recipe fields
or cached for later launches. Download failures still launch the original game.

A wrapper is responsible for starting the original game with `exec "$@"`, keeping
its exit status, and continuing after its own auxiliary setup failures. Clean the
host environment only for auxiliary subprocesses, not the game. Use `--wrapper`
on the individual invocation, not an environment-wide mode flag that could affect
other recipes in the same launch chain.

Wrapper mode requires the updated DLOR plugin build, which installs the shared
runner on plugin startup. Refetching recipes alone does not update that runner.
The separate Decky Launch Options host plugin does not need modification.

### Build-time environment variables

Recipe string fields can use `{{env:VARIABLE_NAME}}` placeholders. The recipe generator replaces each placeholder with
the matching environment variable and fails when a required variable is missing.

The GitHub workflow provides the source repository owner, repository name, and commit as
`RECIPE_REPOSITORY_OWNER`, `RECIPE_REPOSITORY_NAME`, and `RECIPE_COMMIT_SHA`. This allows recipes to reference files
from the exact repository revision that generated `recipes.json`. Pull requests generate the file for validation; the
push workflow commits the final generated file because its contents depend on the source commit SHA.
