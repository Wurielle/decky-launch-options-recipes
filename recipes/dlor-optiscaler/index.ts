import type { LaunchOption, Recipe } from '../shared/types.js'
import { remoteScript } from '../shared/remote-script.js'

const group = 'DLOR OptiScaler'
const install = remoteScript('dlor-optiscaler', 'install')
const uninstall = remoteScript('dlor-optiscaler', 'uninstall')
// remoteScript validates build metadata. The helper-only runner does not export
// its revision; supply module acquisition context without changing other recipes'.
const sourceContext = `DLOR_OPTISCALER_SOURCE_REVISION="${process.env.RECIPE_COMMIT_SHA}" DLOR_OPTISCALER_SOURCE_REPOSITORY="${process.env.RECIPE_REPOSITORY_OWNER}/${process.env.RECIPE_REPOSITORY_NAME}"`

// The core always uses the official nightly and the declared DXGI proxy.
// OptiPatcher is mandatory in the main install; profiles only select files.
function choices(option: string, name: string, variable: string, values: readonly string[]): LaunchOption[] {
    return [null, ...values].map((value): LaunchOption => ({
        id: `dlor-optiscaler-${option}-${value ?? 'none'}`,
        group,
        name,
        on: value === null ? '' : `${variable}="${value}"`,
        off: '',
        enableGlobally: false,
        valueId: `dlor-optiscaler-${option}`,
        valueName: value === null ? 'None' : value,
        ...(value === null ? { fallbackValue: true } : {}),
    }))
}

const recipe = {
    name: group,
    launchOptions: [
        {
            id: 'dlor-optiscaler',
            group,
            name: group,
            on: `WINEDLLOVERRIDES="dxgi=n,b" ${sourceContext} ${install}`,
            off: `${sourceContext} ${uninstall}`,
            enableGlobally: false,
        },
        // Compatibility profiles use a third-party distribution, not an AMD
        // driver installer. No profile rewrites FSR activation settings.
        ...choices('fsr-profile', 'FSR4 compatibility', 'DLOR_OPTISCALER_FSR_PROFILE', [
            'bundled', 'rdna23-int8', 'rdna34-official-411', 'rdna2-valve-411',
        ]),
    ],
} satisfies Recipe

export default recipe
