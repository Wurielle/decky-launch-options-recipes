// Dropdown fallback policy: use "Auto" instead of "None" because empty launch
// options would leave existing OptiScaler.ini values unchanged instead of
// resetting them to OptiScaler defaults.
import type { LaunchOption, Recipe } from './types.js'

type OptiScalerDropdownValue = {
    id: string
    name: string
    value: string | number | boolean
    enableGlobally?: boolean
    fallbackValue?: boolean
}

const optiScalerGroup = 'OptiScaler'
const optiScalerEnv = (option: string, value: string | number | boolean) => `OptiScaler_${option}="${value}"`

const optiScalerDropdown = (
    idPrefix: string,
    name: string,
    valueId: string,
    option: string,
    values: readonly OptiScalerDropdownValue[],
): LaunchOption[] => values.map((value): LaunchOption => ({
    id: `${idPrefix}-${value.id}`,
    group: optiScalerGroup,
    name,
    on: optiScalerEnv(option, value.value),
    off: '',
    enableGlobally: value.enableGlobally ?? false,
    valueId,
    valueName: value.name,
    ...(value.fallbackValue === true ? {fallbackValue: true} : {}),
}))

const frameGenInputValues = [
    {
        id: 'auto',
        name: 'Auto',
        value: 'auto',
        enableGlobally: true,
        fallbackValue: true,
    },
    {
        id: 'nofg',
        name: 'No FrameGen',
        value: 'nofg',
    },
    {
        id: 'dlssg',
        name: 'DLSSG',
        value: 'dlssg',
    },
    {
        id: 'nvngxfg',
        name: 'NvngxFG',
        value: 'nvngxfg',
    },
    {
        id: 'fsrfg',
        name: 'FSR FG',
        value: 'fsrfg',
    },
    {
        id: 'upscaler',
        name: 'Upscaler',
        value: 'upscaler',
    },
    {
        id: 'fsrfg30',
        name: 'FSR FG 3.0',
        value: 'fsrfg30',
    },
] as const

const frameGenOutputValues = [
    {
        id: 'auto',
        name: 'Auto',
        value: 'auto',
        enableGlobally: true,
        fallbackValue: true,
    },
    {
        id: 'nofg',
        name: 'No FrameGen',
        value: 'nofg',
    },
    {
        id: 'fsrfg',
        name: 'FSR FG',
        value: 'fsrfg',
    },
    {
        id: 'xefg',
        name: 'XeFG',
        value: 'xefg',
    },
    {
        id: 'nvngxfg',
        name: 'NvngxFG',
        value: 'nvngxfg',
    },
    {
        id: 'dlssg',
        name: 'DLSSG',
        value: 'dlssg',
    },
    {
        id: 'dlssgwithnvngx',
        name: 'DLSSG with NvngxFG',
        value: 'dlssgwithnvngx',
    },
] as const

const framerateLimitValues = [
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

const dx11UpscalerValues = [
    {
        id: 'auto',
        name: 'Auto',
        value: 'auto',
        enableGlobally: true,
        fallbackValue: true,
    },
    {
        id: 'fsr22',
        name: 'FSR 2.2 (native)',
        value: 'fsr22',
    },
    {
        id: 'fsr31',
        name: 'FSR 3.1 (native)',
        value: 'fsr31',
    },
    {
        id: 'xess',
        name: 'XeSS (native, Arc only)',
        value: 'xess',
    },
    {
        id: 'xess12',
        name: 'XeSS (DX11on12)',
        value: 'xess_12',
    },
    {
        id: 'fsr21-12',
        name: 'FSR 2.1 (DX11on12)',
        value: 'fsr21_12',
    },
    {
        id: 'fsr22-12',
        name: 'FSR 2.2 (DX11on12)',
        value: 'fsr22_12',
    },
    {
        id: 'fsr31-12',
        name: 'FSR 3.1 / FSR4 (DX11on12)',
        value: 'fsr31_12',
    },
    {
        id: 'dlss',
        name: 'DLSS',
        value: 'dlss',
    },
] as const

const dx12UpscalerValues = [
    {
        id: 'auto',
        name: 'Auto',
        value: 'auto',
        enableGlobally: true,
        fallbackValue: true,
    },
    {
        id: 'xess',
        name: 'XeSS',
        value: 'xess',
    },
    {
        id: 'fsr21',
        name: 'FSR 2.1',
        value: 'fsr21',
    },
    {
        id: 'fsr22',
        name: 'FSR 2.2',
        value: 'fsr22',
    },
    {
        id: 'fsr31',
        name: 'FSR 3.1 / FSR4',
        value: 'fsr31',
    },
    {
        id: 'dlss',
        name: 'DLSS',
        value: 'dlss',
    },
] as const

const vulkanUpscalerValues = [
    {
        id: 'auto',
        name: 'Auto',
        value: 'auto',
        enableGlobally: true,
        fallbackValue: true,
    },
    {
        id: 'fsr21',
        name: 'FSR 2.1 (native)',
        value: 'fsr21',
    },
    {
        id: 'fsr22',
        name: 'FSR 2.2 (native)',
        value: 'fsr22',
    },
    {
        id: 'fsr31',
        name: 'FSR 3.1 (native)',
        value: 'fsr31',
    },
    {
        id: 'xess',
        name: 'XeSS (native)',
        value: 'xess',
    },
    {
        id: 'fsr21-12',
        name: 'FSR 2.1 (VKon12)',
        value: 'fsr21_12',
    },
    {
        id: 'fsr31-12',
        name: 'FSR 3.1 / FSR4 (VKon12)',
        value: 'fsr31_12',
    },
    {
        id: 'dlss',
        name: 'DLSS',
        value: 'dlss',
    },
] as const

const launchOptions: LaunchOption[] = [
    {
        id: 'optiscaler',
        group: '',
        name: 'OptiScaler',
        on: '~/fgmod/fgmod %command%',
        off: '~/fgmod/fgmod-uninstaller.sh %command%',
        enableGlobally: false,
    },
    {
        id: 'optiscaler-framegen-enabled',
        group: optiScalerGroup,
        name: 'OptiScaler FrameGen',
        on: optiScalerEnv('FrameGen_Enabled', 'true'),
        off: optiScalerEnv('FrameGen_Enabled', 'false'),
        enableGlobally: true,
    },
    ...optiScalerDropdown(
        'optiscaler-framegen-input',
        'OptiScaler FrameGen Input',
        'optiscaler-framegen-input',
        'FrameGen_FGInput',
        frameGenInputValues,
    ),
    ...optiScalerDropdown(
        'optiscaler-framegen-output',
        'OptiScaler FrameGen Output',
        'optiscaler-framegen-output',
        'FrameGen_FGOutput',
        frameGenOutputValues,
    ),
    ...optiScalerDropdown(
        'optiscaler-framerate-limit',
        'OptiScaler Framerate Limit',
        'optiscaler-framerate-limit',
        'Framerate_FramerateLimit',
        [
            {
                id: 'auto',
                name: 'Auto',
                value: 'auto',
                fallbackValue: true,
                enableGlobally: true,
            },
            {
                id: 'disabled',
                name: 'Disabled',
                value: '0.0',
            },
            ...framerateLimitValues.map((framerateLimit) => ({
                id: `${framerateLimit}`,
                name: `${framerateLimit}`,
                value: framerateLimit,
            })),
        ],
    ),
    ...optiScalerDropdown(
        'optiscaler-upscalers-dx11',
        'OptiScaler Dx11 Upscaler',
        'optiscaler-upscalers-dx11',
        'Upscalers_Dx11Upscaler',
        dx11UpscalerValues,
    ),
    ...optiScalerDropdown(
        'optiscaler-upscalers-dx12',
        'OptiScaler Dx12 Upscaler',
        'optiscaler-upscalers-dx12',
        'Upscalers_Dx12Upscaler',
        dx12UpscalerValues,
    ),
    ...optiScalerDropdown(
        'optiscaler-upscalers-vk',
        'OptiScaler Vulkan Upscaler',
        'optiscaler-upscalers-vk',
        'Upscalers_VulkanUpscaler',
        vulkanUpscalerValues,
    ),
]

const recipe = {
    "name": "OptiScaler",
    launchOptions,
} satisfies Recipe

export default recipe
