import type { LaunchOption, Recipe } from './shared/types.js'

const mangoHudGroup = 'MangoHud'
const mangoHudConfig = (value: string) => `MANGOHUD_CONFIG="${value}"`

const presetValues = [
    {
        id: 'none',
        name: 'None',
        value: null,
        fallbackValue: true,
    },
    {
        id: '0',
        name: 'No Hud',
        value: '0',
    },
    {
        id: '1',
        name: 'FPS Only',
        value: '1',
    },
    {
        id: '2',
        name: 'Horizontal',
        value: '2',
    },
    {
        id: '3',
        name: 'Extended',
        value: '3',
    },
    {
        id: '4',
        name: 'Detailed',
        value: '4',
    },
] as const

const fpsLimitValues = [
    30,
    40,
    45,
    60,
    72,
    82,
    90,
    120,
    144,
    165,
    180,
    240,
    360,
    480,
] as const

const presetOptions: LaunchOption[] = presetValues.map((preset): LaunchOption => ({
    id: `mangohud-config-preset-${preset.id}`,
    group: mangoHudGroup,
    name: 'MangoHud Preset',
    on: preset.value === null ? '' : mangoHudConfig(`preset=${preset.value}`),
    off: '',
    enableGlobally: false,
    valueId: 'mangohud-config-preset',
    valueName: preset.name,
    ...('fallbackValue' in preset && preset.fallbackValue === true ? {fallbackValue: true} : {}),
}))

const fpsLimitOptions: LaunchOption[] = [
    {
        id: 'mangohud-fps-limit-none',
        group: mangoHudGroup,
        name: 'MangoHud FPS Limit',
        on: '',
        off: '',
        enableGlobally: false,
        valueId: 'mangohud-config-fps-limit',
        valueName: 'None',
        fallbackValue: true,
    },
    ...fpsLimitValues.map((fpsLimit): LaunchOption => ({
        id: `mangohud-fps-limit-${fpsLimit}`,
        group: mangoHudGroup,
        name: 'MangoHud FPS Limit',
        on: mangoHudConfig(`fps_limit=${fpsLimit}`),
        off: '',
        enableGlobally: false,
        valueId: 'mangohud-config-fps-limit',
        valueName: `${fpsLimit}`,
    })),
]

const launchOptions: LaunchOption[] = [
    {
        id: 'mangohud',
        group: mangoHudGroup,
        name: 'MangoHud',
        on: 'mangohud %command%',
        off: '',
        enableGlobally: false,
    },
    ...presetOptions,
    ...fpsLimitOptions,
]

const recipe = {
    "name": "MangoHud",
    launchOptions,
} satisfies Recipe

export default recipe
