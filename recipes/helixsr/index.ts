import type { Recipe } from '../shared/types.js'
import { remoteScript } from '../shared/remote-script.js'

const configure = remoteScript('helixsr', 'configure')

// fgmod persists OptiScaler settings into the game's INI; disabling must restore
// owned settings rather than merely remove environment variables. Run after
// OptiScaler (default priority) and its nightly upgrade (priority -1).
const recipe = {
    name: 'HelixSR',
    launchOptions: [
        {
            id: 'helixsr',
            group: 'HelixSR',
            name: 'HelixSR (OptiScaler DX12)',
            on: `DLOR_HELIXSR_ACTION="on" ${configure}`,
            off: `DLOR_HELIXSR_ACTION="off" ${configure}`,
            enableGlobally: false,
            priority: -2,
        },
    ],
} satisfies Recipe

export default recipe
