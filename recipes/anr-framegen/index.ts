import type { LaunchOption, Recipe } from '../shared/types.js'
import { remoteScript } from '../shared/remote-script.js'

const install = remoteScript('anr-framegen', 'install')
const uninstall = remoteScript('anr-framegen', 'uninstall')

const actionValues = [
    {id: 'none', name: 'None', command: ''},
    {id: 'install', name: 'Install', command: install},
    {id: 'uninstall', name: 'Uninstall', command: uninstall},
] as const

// Addon only: the existing custom-provider-capable OptiScaler stays untouched.
// None/deselection is inert; only the explicit Uninstall action removes ANR.
const launchOptions: LaunchOption[] = actionValues.map((action): LaunchOption => ({
    id: `optiscaler-framegen-anr-${action.id}`,
    group: 'OptiScaler',
    name: 'OptiScaler FrameGen ANR',
    on: action.command,
    off: '',
    enableGlobally: false,
    // Core installers default to 0; nightly upgrades use -1. Install ANR last,
    // but remove it before the core can delete its required OptiScaler.ini.
    priority: action.id === 'uninstall' ? 1 : -2,
    valueId: 'optiscaler-framegen-anr',
    valueName: action.name,
    ...(action.id === 'none' ? {fallbackValue: true} : {}),
}))

const recipe = {
    id: 'optiscaler-framegen-anr',
    name: 'OptiScaler FrameGen ANR',
    launchOptions,
} satisfies Recipe

export default recipe
