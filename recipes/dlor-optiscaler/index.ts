import type { LaunchOption, Recipe } from '../shared/types.js'
import { remoteScript } from '../shared/remote-script.js'

const group = 'DLOR OptiScaler'
const install = remoteScript('dlor-optiscaler', 'install')
const uninstall = remoteScript('dlor-optiscaler', 'uninstall')

// The core always uses the official nightly and the declared DXGI proxy.
// OptiPatcher is mandatory in the main install; profiles only select files.
function choices(option: string, name: string, variable: string, values: readonly (string | { value: string, label: string })[]): LaunchOption[] {
    return [null, ...values].map((choice): LaunchOption => {
        const value = typeof choice === 'object' && choice !== null ? choice.value : choice
        return {
            id: `dlor-optiscaler-${option}-${value ?? 'none'}`,
            group,
            name,
            on: value === null ? '' : `${variable}="${value}"`,
            off: '',
            enableGlobally: value === null,
            valueId: `dlor-optiscaler-${option}`,
            valueName: choice === null ? 'None' : typeof choice === 'string' ? choice : choice.label,
            ...(value === null ? { fallbackValue: true } : {}),
        }
    })
}

const optimizedProfiles = [
    ['rx6000', 'RX 6000'], ['rx7000', 'RX 7000'],
    ['igpu-rdna2', 'Steam Deck / RDNA2 iGPU'], ['igpu-rdna3', 'RDNA3 iGPU'],
].flatMap(([family, label]) => ['Exact', 'Lossy'].map(variant => ({
    value: `zgauthier-${family}-${variant.toLowerCase()}`,
    label: `zgauthier ${variant} · ${label}`,
})))

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
        // Sources select files, never FSR activation settings or GPU presets.
        ...choices('fsr-profile', 'FSR4 compatibility', 'DLOR_OPTISCALER_FSR_PROFILE', [
            'bundled', 'rdna23-int8', 'rdna34-official-411', 'rdna2-valve-411',
            { value: 'sdk-amd', label: 'AMD SDK' },
            ...optimizedProfiles,
        ]),
    ],
} satisfies Recipe

export default recipe
