# Decky Launch Options Recipes

Decky Launch Options Recipes is a collection of launch options recipes for
the [Decky Launch Options](https://github.com/Wurielle/decky-launch-options) plugin.

This plugin is mainly made for debugging purposes but can be used to allow easy installation of launch options in coordination with [Decky Launch Options](https://github.com/Wurielle/decky-launch-options).

By default, the source of the recipes is the `recipes.json` file in this repo. You can point the recipes source to a
different file hosted anywhere so you can easily create your own set of launch options recipes.

> Make sure you **TRUST** the source of the recipes if you point to a different file. Decky Launch Options will ask you
> to review any launch option added but to be safe, only point to a `recipes.json` file you trust or that you can host
> and
> review yourself.

Here's what recipes look like:

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
