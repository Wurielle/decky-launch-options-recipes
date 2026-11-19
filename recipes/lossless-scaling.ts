import type { Recipe } from './shared/types.js'

const recipe = {
    id: 'lossless-scaling',
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
