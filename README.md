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
automatically, so there is no registry file to maintain.

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

### Build-time environment variables

Recipe string fields can use `{{env:VARIABLE_NAME}}` placeholders. The recipe generator replaces each placeholder with
the matching environment variable and fails when a required variable is missing.

The GitHub workflow provides the source repository owner, repository name, and commit as
`RECIPE_REPOSITORY_OWNER`, `RECIPE_REPOSITORY_NAME`, and `RECIPE_COMMIT_SHA`. This allows recipes to reference files
from the exact repository revision that generated `recipes.json`. Pull requests generate the file for validation; the
push workflow commits the final generated file because its contents depend on the source commit SHA.
