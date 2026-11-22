import type { LaunchOption, Recipe } from '../shared/types.js'
import { remoteScript } from '../shared/remote-script.js'
import { wineDllOverridesMerge } from '../shared/env-variable-merges.js'
import { createOptiScalerOptions } from '../optiscaler/index.js'
import anrFramegen from '../anr-framegen/index.js'

const group = 'DLOR OptiScaler'
const install = remoteScript('dlor-optiscaler', 'install')
const uninstall = remoteScript('dlor-optiscaler', 'uninstall')

// DLO collects dropdown assignments before running this pre-launch command.
const installCommand = `export WINEDLLOVERRIDES="\${WINEDLLOVERRIDES:+$WINEDLLOVERRIDES;}\${DLOR_OPTISCALER_PROXY:-dxgi}=n,b" && SteamDeck=0 ${install}`
const proxyValueId = 'dlor-optiscaler-proxy'
const proxyChoices = ['dxgi', 'winmm', 'd3d12', 'dbghelp', 'version', 'wininet', 'winhttp'] as const

// The core always uses the official nightly and the selected DLL proxy.
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
            enableGlobally: value === 'sdk-amd',
            valueId: `dlor-optiscaler-${option}`,
            valueName: choice === null ? 'None' : typeof choice === 'string' ? choice : choice.label,
            ...(value === 'sdk-amd' ? { fallbackValue: true } : {}),
        }
    })
}

const optimizedProfiles = [
    ['rx6000', 'RDNA 2'], ['rx7000', 'RDNA 3'],
    ['igpu-rdna2', 'RDNA 2 iGPU'], ['igpu-rdna3', 'RDNA 3 iGPU'],
].flatMap(([family, label]) => ['Exact', 'Lossy'].map(variant => ({
    value: `zgauthier2000-${family}-${variant.toLowerCase()}`,
    label: `${label} - ${variant}`,
})))

const recipe = {
    id: 'dlor-optiscaler',
    name: group,
    environmentVariableMerges: [wineDllOverridesMerge],
    launchOptions: [
        // Reuse the old toggle ID for None so re-import clears its OFF uninstaller.
        ...[
            { id: 'dlor-optiscaler', name: 'None', command: '' },
            { id: 'dlor-optiscaler-install', name: 'Install', command: installCommand },
            { id: 'dlor-optiscaler-uninstall', name: 'Uninstall', command: uninstall },
        ].map((action): LaunchOption => ({
            id: action.id,
            name: group,
            on: action.command,
            off: '',
            enableGlobally: false,
            valueId: 'dlor-optiscaler',
            valueName: action.name,
            ...(action.id === 'dlor-optiscaler' ? { fallbackValue: true } : {}),
        })),
        ...[null, ...proxyChoices].map((proxy): LaunchOption => ({
            id: `${proxyValueId}-${proxy ?? 'none'}`,
            name: 'OptiScaler Proxy',
            on: proxy === null ? '' : `DLOR_OPTISCALER_PROXY="${proxy}"`,
            off: '',
            enableGlobally: false,
            valueId: proxyValueId,
            valueName: proxy === null ? 'None' : `${proxy}.dll`,
            ...(proxy === null ? { fallbackValue: true } : {}),
        })),
        // Sources select files, never FSR activation settings or GPU presets.
        ...choices('fsr-override', 'FSR Override', 'DLOR_OPTISCALER_FSR_PROFILE', [
            { value: 'bundled', label: 'Bundled' },
            { value: 'sdk-amd', label: 'AMD SDK' },
            ...optimizedProfiles,
        ]),
        ...[
            ...createOptiScalerOptions('10').filter(option => option.valueId !== 'optiscaler'),
            // Install after the core and its priority -1 nightly upgrade. Remove
            // ANR before core removal can delete its required OptiScaler.ini.
            ...anrFramegen.launchOptions.map(option => ({
                ...option,
                priority: option.id === 'optiscaler-framegen-anr-uninstall' ? 1 : -2,
            })),
        ].map(option => ({
            ...option,
            id: `dlor-${option.id}`,
            group,
            ...(option.valueId ? { valueId: `dlor-${option.valueId}` } : {}),
        })),
    ],
} satisfies Recipe

export default recipe
