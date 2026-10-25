import type { LaunchOption, Recipe } from '../shared/types.js'
import { remoteScript } from '../shared/remote-script.js'

const group = 'DLOR OptiScaler'
const install = remoteScript('dlor-optiscaler', 'install')
const uninstall = remoteScript('dlor-optiscaler', 'uninstall')

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
            on: `WINEDLLOVERRIDES="dxgi=n,b" SteamDeck=0 ${install}`,
            off: uninstall,
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
