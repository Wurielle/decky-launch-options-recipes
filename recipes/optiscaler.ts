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

type OptiScalerCustomDropdownValue = {
    id: string
    name: string
    on: string
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

const optiScalerCustomDropdown = (
    idPrefix: string,
    name: string,
    valueId: string,
    values: readonly OptiScalerCustomDropdownValue[],
): LaunchOption[] => values.map((value): LaunchOption => ({
    id: `${idPrefix}-${value.id}`,
    group: optiScalerGroup,
    name,
    on: value.on,
    off: '',
    enableGlobally: value.enableGlobally ?? false,
    valueId,
    valueName: value.name,
    ...(value.fallbackValue === true ? {fallbackValue: true} : {}),
}))

const menuShortcutKeyValues = [
    {
        id: 'auto',
        name: 'Auto',
        value: 'auto',
        enableGlobally: true,
        fallbackValue: true,
    },
    {
        id: 'insert',
        name: 'Insert',
        value: '0x2D',
    },
    {
        id: 'volume-down',
        name: 'Volume Down',
        value: '0xAE',
    },
    {
        id: 'volume-up',
        name: 'Volume Up',
        value: '0xAF',
    },
    {
        id: 'start',
        name: 'Start',
        value: '0xCF',
    },
    {
        id: 'select',
        name: 'Select',
        value: '0xD0',
    },
] as const

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
        name: 'No Frame Generation',
        value: 'nofg',
    },
    {
        id: 'dlssg',
        name: 'DLSSG via Streamline',
        value: 'dlssg',
    },
    {
        id: 'nvngxfg',
        name: "Nukem's/Artur's DLSSG",
        value: 'nvngxfg',
    },
    {
        id: 'fsrfg',
        name: 'FSR 3.1 FG',
        value: 'fsrfg',
    },
    {
        id: 'upscaler',
        name: 'OptiFG (Upscaler)',
        value: 'upscaler',
    },
    {
        id: 'fsrfg30',
        name: 'FSR 3.0 FG',
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
        name: 'No Frame Generation',
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
        name: 'FSR3-FG Nukem/Enabler',
        value: 'nvngxfg',
    },
    {
        id: 'dlssg',
        name: 'DLSSG',
        value: 'dlssg',
    },
    {
        id: 'dlssgwithnvngx',
        name: 'DLSSG with Nvngx FG',
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

const latencyProviderValues = [
    {
        id: 'auto',
        name: 'Auto',
        on: [
            optiScalerEnv('fakenvapi_UseFakenvapi', 'auto'),
            optiScalerEnv('fakenvapi_ForceXeLL', 'auto'),
            optiScalerEnv('fakenvapi_ForceLatencyFlex', 'auto'),
        ].join(' '),
        fallbackValue: true,
    },
    {
        id: 'fakenvapi',
        name: 'Fakenvapi',
        on: optiScalerEnv('fakenvapi_UseFakenvapi', 'true'),
    },
    {
        id: 'xell',
        name: 'Force XeLL',
        on: optiScalerEnv('fakenvapi_ForceXeLL', 'true'),
    },
    {
        id: 'latencyflex',
        name: 'Force LatencyFlex',
        on: optiScalerEnv('fakenvapi_ForceLatencyFlex', 'true'),
    },
    {
        id: 'disabled',
        name: 'Disable Fakenvapi',
        on: optiScalerEnv('fakenvapi_UseFakenvapi', 'false'),
    },
] as const

const latencyFlexModeValues = [
    {
        id: 'auto',
        name: 'Auto',
        value: 'auto',
        fallbackValue: true,
    },
    {
        id: 'conservative',
        name: 'Conservative',
        value: 0,
    },
    {
        id: 'aggressive',
        name: 'Aggressive',
        value: 1,
    },
    {
        id: 'reflex-frame-ids',
        name: 'Reflex Frame IDs',
        value: 2,
    },
] as const

const reflexOverrideValues = [
    {
        id: 'auto',
        name: 'Auto',
        value: 'auto',
        fallbackValue: true,
    },
    {
        id: 'disabled',
        name: 'Force Disabled',
        value: 1,
    },
    {
        id: 'enabled',
        name: 'Force Enabled',
        value: 2,
    },
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
        enableGlobally: false,
    },
    ...optiScalerDropdown(
        'optiscaler-menu-shortcut-key',
        'OptiScaler Menu Shortcut',
        'optiscaler-menu-shortcut-key',
        'Menu_ShortcutKey',
        menuShortcutKeyValues,
    ),
    {
        id: 'optiscaler-hudfix',
        group: optiScalerGroup,
        name: 'OptiScaler FrameGen OptiFG HUDFix',
        on: optiScalerEnv('OptiFG_HUDFix', 'true'),
        off: optiScalerEnv('OptiFG_HUDFix', 'auto'),
        enableGlobally: false,
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
    ...optiScalerCustomDropdown(
        'optiscaler-latency-provider',
        'OptiScaler Latency Provider',
        'optiscaler-latency-provider',
        latencyProviderValues,
    ),
    ...optiScalerDropdown(
        'optiscaler-latencyflex-mode',
        'OptiScaler LatencyFlex Mode',
        'optiscaler-latencyflex-mode',
        'fakenvapi_LatencyFlexMode',
        latencyFlexModeValues,
    ),
    ...optiScalerDropdown(
        'optiscaler-reflex-override',
        'OptiScaler Reflex Override',
        'optiscaler-reflex-override',
        'fakenvapi_ForceReflex',
        reflexOverrideValues,
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
