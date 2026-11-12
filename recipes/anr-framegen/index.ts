import type { Recipe } from '../shared/types.js'
import { remoteScript } from '../shared/remote-script.js'

const install = remoteScript('anr-framegen', 'install')
const uninstall = remoteScript('anr-framegen', 'uninstall')

// Addon only: the existing custom-provider-capable OptiScaler stays untouched.
// Physical scripts discover its INI, verify/cache ANR, and own two FG settings.
const recipe = {
    name: 'OptiScaler FrameGen ANR',
    launchOptions: [
        {
            id: 'anr-framegen',
            group: 'OptiScaler',
            name: 'OptiScaler FrameGen ANR',
            on: install,
            off: uninstall,
            enableGlobally: false,
        },
    ],
} satisfies Recipe

export default recipe
