import type { LaunchOption, Recipe } from './types.js'

const recommendedDlls = [
    'winhttp.dll',
    'version.dll',
    'dinput8.dll',
    'dxgi.dll',
    'd3d9.dll',
    'd3d10.dll',
    'd3d10_1.dll',
    'd3d11.dll',
    'd3d12.dll',
    'd3dcompiler_43.dll',
    'd3dcompiler_47.dll',
    'xinput1_3.dll',
    'xinput1_4.dll',
    'xinput9_1_0.dll',
    'dsound.dll',
    'xaudio2_7.dll',
    'xaudio2_8.dll',
    'xaudio2_9.dll',
    'openal32.dll',
    'binkw32.dll',
    'bink2w64.dll',
    'steam_api.dll',
    'steam_api64.dll',
] as const

const overrideValues = [
    {
        id: 'none',
        name: 'None',
        value: null,
        fallbackValue: true,
    },
    {
        id: 'native',
        name: 'Native',
        value: 'n',
    },
    {
        id: 'builtin',
        name: 'Builtin',
        value: 'b',
    },
    {
        id: 'native-builtin',
        name: 'Native, Builtin',
        value: 'n,b',
    },
    {
        id: 'builtin-native',
        name: 'Builtin, Native',
        value: 'b,n',
    },
    {
        id: 'disabled',
        name: 'Disabled',
        value: '',
    },
] as const

const dllName = (dll: string) => dll.replace(/\.dll$/u, '')
const dllId = (dll: string) => dllName(dll).replace(/_/gu, '-')

const launchOptions: LaunchOption[] = recommendedDlls.flatMap((dll) => {
    const name = dllName(dll)
    const id = dllId(dll)
    const valueId = `wine-dll-override-${id}`

    return overrideValues.map((override): LaunchOption => ({
        id: `${valueId}-${override.id}`,
        group: 'Wine',
        name: `${dll} Override`,
        on: override.value === null ? '' : `WINEDLLOVERRIDES="${name}=${override.value}"`,
        off: '',
        enableGlobally: false,
        valueId,
        valueName: override.name,
        ...('fallbackValue' in override && override.fallbackValue === true ? {fallbackValue: true} : {}),
    }))
})

const recipe = {
    "name": "Wine",
    launchOptions,
} satisfies Recipe

export default recipe
