import type { Recipe } from '../shared/types.js'
import { remoteScript } from '../shared/remote-script.js'

// The DLOR runner downloads the wrapper and gives it the original game process
// environment/argv; all setup, logging and override logic stays in launch.sh.
const launch = remoteScript('helixsr', 'launch', 'wrapper')

const recipe = {
    name: 'HelixSR',
    launchOptions: [
        {
            id: 'helixsr',
            group: 'HelixSR',
            name: 'HelixSR (OptiScaler DX12)',
            on: `DLOR_HELIXSR_ACTION="on" ${launch}`,
            off: `DLOR_HELIXSR_ACTION="off" ${launch}`,
            enableGlobally: false,
            priority: -2,
        },
    ],
} satisfies Recipe

export default recipe
