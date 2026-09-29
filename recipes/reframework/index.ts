import type { LaunchOption, Recipe } from '../shared/types.js'
import { remoteScript } from '../shared/remote-script.js'

const reframeworkGroup = 'REFramework'
const update = remoteScript('reframework', 'update')
const uninstall = remoteScript('reframework', 'uninstall')
const wineDllOverrides = 'WINEDLLOVERRIDES="dinput8.dll=n,b"'

const actionValues = [
    {
        id: 'none',
        name: 'None',
        command: '',
        fallbackValue: true,
    },
    {
        id: 'install-update',
        name: 'Install/Update',
        command: `${wineDllOverrides} ${update}`,
    },
    {
        id: 'uninstall',
        name: 'Uninstall',
        command: uninstall,
    },
] as const

const launchOptions: LaunchOption[] = actionValues.map((action): LaunchOption => ({
    id: `reframework-${action.id}`,
    group: reframeworkGroup,
    name: reframeworkGroup,
    on: action.command,
    off: '',
    enableGlobally: false,
    valueId: 'reframework',
    valueName: action.name,
    ...('fallbackValue' in action && action.fallbackValue === true ? {fallbackValue: true} : {}),
}))

const recipe = {
    name: reframeworkGroup,
    launchOptions,
} satisfies Recipe

export default recipe
