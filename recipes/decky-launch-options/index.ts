import type { LaunchOption, Recipe } from '../shared/types.js'
import { remoteScript } from '../shared/remote-script.js'

const autoUpdate = remoteScript('decky-launch-options', 'auto-update')
const variants = [
    { id: 'none', name: 'None' },
    { id: 'regular', name: 'Regular' },
    { id: 'with-store', name: 'With store' },
] as const

const recipe = {
    name: 'Decky Launch Options',
    launchOptions: variants.map((variant): LaunchOption => ({
        id: `decky-launch-options-auto-update-${variant.id}`,
        group: '',
        name: 'Auto Update Decky Launch Options',
        on: variant.id === 'none' ? '' : `DLO_UPDATE_VARIANT="${variant.id}" ${autoUpdate}`,
        off: '',
        // One globally selected sibling makes the whole dropdown global.
        enableGlobally: variant.id === 'none',
        valueId: 'decky-launch-options-auto-update',
        valueName: variant.name,
        ...(variant.id === 'none' ? { fallbackValue: true } : {}),
        // Finish other recipe helpers before reloading their DLO host.
        priority: -100,
    })),
} satisfies Recipe

export default recipe
