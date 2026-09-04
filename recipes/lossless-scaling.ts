import type { Recipe } from './shared/types.js'

const recipe = {
    "name": "Lossless Scaling",
    "launchOptions": [
        {
            "id": "lossless-scaling",
            "name": "Lossless Scaling",
            "on": "~/lsfg %command%",
            "off": "",
            "enableGlobally": false,
        },
    ],
} satisfies Recipe

export default recipe
