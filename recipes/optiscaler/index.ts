import type { LaunchOption, Recipe } from '../shared/types.js'
import { remoteScript } from '../shared/remote-script.js'

const updateNightly = remoteScript('optiscaler', 'update-nightly')

type OptiScalerDropdownValue = {
    id: string
    name: string
    value: string | number | boolean
}

const optiScalerGroup = 'OptiScaler'
const optiScalerEnv = (option: string, value: string | number | boolean) => `OptiScaler_${option}="${value}"`

const optiScalerDropdown = (
    idPrefix: string,
    name: string,
    valueId: string,
    option: string,
    values: readonly OptiScalerDropdownValue[],
): LaunchOption[] => [
    {id: 'none', name: 'None', value: null},
    ...values,
].map((value): LaunchOption => ({
    id: `${idPrefix}-${value.id}`,
    group: optiScalerGroup,
    name,
    on: value.value === null ? '' : optiScalerEnv(option, value.value),
    off: '',
    enableGlobally: false,
    valueId,
    valueName: value.name,
    ...(value.value === null ? {fallbackValue: true} : {}),
}))

const menuShortcutKeyValues = [
    {
        id: 'auto',
        name: 'Auto',
        value: 'auto',
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
        id: 'previous-track',
        name: 'Previous Track',
        value: '0xB1',
    },
    {
        id: 'play-pause',
        name: 'Play/Pause',
        value: '0xB3',
    },
    {
        id: 'next-track',
        name: 'Next Track',
        value: '0xB0',
    },
    {
        id: 'escape',
        name: 'Escape',
        value: '0x1B',
    },
    {
        id: 'tab',
        name: 'Tab',
        value: '0x09',
    },
    {
        id: 'enter',
        name: 'Enter',
        value: '0x0D',
    },
] as const

const frameGenInputValues = [
    {
        id: 'auto',
        name: 'Auto',
        value: 'auto',
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
        name: 'Nvngx DLSSG',
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
    {
        id: 'xefg',
        name: 'XeFG',
        value: 'xefg',
    },
] as const

const frameGenOutputValues = [
    {
        id: 'auto',
        name: 'Auto',
        value: 'auto',
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
        id: 'dlssg',
        name: 'DLSSG',
        value: 'dlssg',
    },
    {
        id: 'reprojection',
        name: 'Reprojection (WIP; mouse / first-person only)',
        value: 'reprojection',
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
        id: 'ffx-12',
        name: 'FidelityFX / FSR4 (DX11on12)',
        value: 'ffx_12',
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
        id: 'ffx',
        name: 'FidelityFX / FSR4',
        value: 'ffx',
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
        id: 'ffx',
        name: 'FidelityFX (native Vulkan)',
        value: 'ffx',
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
        id: 'ffx-12',
        name: 'FidelityFX / FSR4 (VKon12)',
        value: 'ffx_12',
    },
    {
        id: 'dlss',
        name: 'DLSS',
        value: 'dlss',
    },
] as const

const fsr4PresetValues = [
    {id: 'auto', name: 'Auto', value: 'auto'},
    {id: '0', name: 'Native AA', value: 0},
    {id: '1', name: 'Ultra Quality / Quality', value: 1},
    {id: '2', name: 'Balanced', value: 2},
    {id: '3', name: 'Performance', value: 3},
    {id: '4', name: 'DRS', value: 4},
    {id: '5', name: 'Ultra Performance', value: 5},
] as const

// The updater accepts normalized section names, keeping V-Sync shell-safe.
const vsyncValues = [
    {id: 'none', name: 'None', value: null, override: null},
    {id: 'auto', name: 'Auto', value: 'auto', override: 'auto'},
    {id: 'on', name: 'On', value: true, override: true},
    {id: 'off', name: 'Off', value: false, override: true},
] as const

const vsyncOptions: LaunchOption[] = vsyncValues.map((value): LaunchOption => ({
    id: `optiscaler-vsync-${value.id}`,
    group: optiScalerGroup,
    name: 'OptiScaler VSync',
    on: value.value === null ? '' : `${optiScalerEnv('VSync_OverrideVsync', value.override)} ${optiScalerEnv('VSync_ForceVsync', value.value)}`,
    off: '',
    enableGlobally: false,
    valueId: 'optiscaler-vsync',
    valueName: value.name,
    ...(value.value === null ? {fallbackValue: true} : {}),
}))

const syncIntervalOptions: LaunchOption[] = optiScalerDropdown(
    'optiscaler-vsync-sync-interval',
    'OptiScaler VSync Sync Interval',
    'optiscaler-vsync-sync-interval',
    'VSync_SyncInterval',
    [
        {id: 'auto', name: 'Auto', value: 'auto'},
        ...[0, 1, 2, 3].map((value) => ({id: `${value}`, name: `${value}`, value})),
    ],
)

const booleanValues = [
    {id: 'auto', name: 'Auto', value: 'auto'},
    {id: 'on', name: 'On', value: true},
    {id: 'off', name: 'Off', value: false},
] as const

// Counts exclude the original frame; documented multipliers remain capability-dependent.
const mfgOptions: LaunchOption[] = ([['xefg', 'XeFG', 3], ['dlssg', 'DLSSG', 5]] as const).flatMap(([engine, section, maximum]) => {
    const prefix = `optiscaler-${engine}`
    const counts = Array.from({length: maximum}, (_, index) => ({
        id: `${index + 1}`, name: `${index + 2}× (${index + 1} generated)`, value: index + 1,
    }))
    return [
        ...optiScalerDropdown(
            `${prefix}-mfg-count`, `OptiScaler ${section} MFG Multiplier`, `${prefix}-mfg-count`,
            `${section}_InterpolationCount`,
            [{id: 'auto', name: 'Auto (2× default)', value: 'auto'}, ...counts],
        ),
        ...optiScalerDropdown(
            `${prefix}-mfg-game-count`, `OptiScaler ${section} Game MFG Override`, `${prefix}-mfg-game-count`,
            `${section}_OverrideInterpolationCount`,
            [
                {id: 'auto', name: 'Auto (no override)', value: 'auto'},
                {id: '0', name: 'Off (0 generated)', value: 0},
                ...counts,
            ],
        ),
        ...optiScalerDropdown(
            `${prefix}-target-fps`, `OptiScaler ${section} Dynamic MFG Target FPS`, `${prefix}-target-fps`,
            `${section}_FramerateTargetDMFG`,
            [
                {id: 'auto', name: 'Auto', value: 'auto'},
                ...(engine === 'dlssg' ? [{id: '0', name: 'Display refresh rate', value: 0}] : []),
                ...[10, 20, ...framerateLimitValues].map((value) => ({id: `${value}`, name: `${value} FPS`, value})),
            ],
        ),
    ]
})

const dynamicMfgOptions: LaunchOption[] = ([
    ['xefg-dynamic-mfg', 'XeFG Dynamic MFG', 'XeFG_DynamicMFG'],
    ['xefg-dynamic-allow-1x', 'XeFG Dynamic MFG Allow 1×', 'XeFG_DynamicAllow1X'],
    ['xefg-target-as-cap-dmfg', 'XeFG Dynamic MFG Use Target as FPS Limit', 'XeFG_TargetAsCapDMFG'],
    ['dlssg-force-dmfg', 'DLSSG Dynamic MFG (forces FG)', 'DLSSG_ForceDMFG'],
    ['dlssg-override-force-dmfg', 'DLSSG Native Game Dynamic MFG Override', 'DLSSG_OverrideForceDMFG'],
] as const).flatMap(([id, name, setting]) => optiScalerDropdown(
    `optiscaler-${id}`, `OptiScaler ${name}`, `optiscaler-${id}`, setting, booleanValues,
))

const launchOptions: LaunchOption[] = [
    {
        id: 'optiscaler',
        group: '',
        name: 'OptiScaler',
        on: '~/fgmod/fgmod %command%',
        off: '~/fgmod/fgmod-uninstaller.sh %command%',
    },
    {
        id: 'optiscaler-nightly-upgrade',
        group: optiScalerGroup,
        name: 'OptiScaler Nightly Upgrade',
        on: updateNightly,
        off: '',
        enableGlobally: false,
        priority: -1,
    },
    {
        id: 'optiscaler-framegen-enabled',
        group: optiScalerGroup,
        name: 'OptiScaler FrameGen',
        on: optiScalerEnv('FrameGen_Enabled', 'true'),
        off: optiScalerEnv('FrameGen_Enabled', 'false'),
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
        'optiscaler-framegen-nvngx-replacement',
        'OptiScaler FrameGen Nvngx Replacement',
        'optiscaler-framegen-nvngx-replacement',
        'FrameGen_FGNvngxReplacement',
        [
            {id: 'auto', name: 'Auto', value: 'auto'},
            {id: 'disabled', name: 'No replacement', value: 'None'},
            {id: 'nukems', name: 'Nukem (FSR3 FG)', value: 'Nukems'},
            {id: 'arturs', name: 'Artur / Enabler (MFG)', value: 'Arturs'},
            {id: 'ffx', name: 'FidelityFX (FSR3/4 FG)', value: 'FFX'},
            {id: 'combo', name: 'FidelityFX + Enabler', value: 'Combo'},
        ],
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
        'OptiScaler Upscaler (Dx11)',
        'optiscaler-upscalers-dx11',
        'Upscalers_Dx11Upscaler',
        dx11UpscalerValues,
    ),
    ...optiScalerDropdown(
        'optiscaler-upscalers-dx12',
        'OptiScaler Upscaler (Dx12)',
        'optiscaler-upscalers-dx12',
        'Upscalers_Dx12Upscaler',
        dx12UpscalerValues,
    ),
    ...optiScalerDropdown(
        'optiscaler-upscalers-vk',
        'OptiScaler Upscaler (Vulkan)',
        'optiscaler-upscalers-vk',
        'Upscalers_VulkanUpscaler',
        vulkanUpscalerValues,
    ),
    ...optiScalerDropdown(
        'optiscaler-fsr-upscaler-index',
        'OptiScaler FSR Upscaler Backend',
        'optiscaler-fsr-upscaler-index',
        'FSR_UpscalerIndex',
        [
            {
                id: 'auto',
                name: 'Auto',
                value: 'auto',
            },
            {
                id: '0',
                name: 'Backend 0 (runtime order)',
                value: 0,
            },
            {
                id: '1',
                name: 'Backend 1 (runtime order)',
                value: 1,
            },
            {
                id: '2',
                name: 'Backend 2 (runtime order)',
                value: 2,
            },
        ],
    ),
    ...optiScalerDropdown(
        'optiscaler-fsr4-preset',
        'OptiScaler FSR 4 Preset',
        'optiscaler-fsr4-preset',
        'FSR_Fsr4Preset',
        fsr4PresetValues,
    ),
    ...optiScalerDropdown(
        'optiscaler-fsr4-gpu-support',
        'OptiScaler FSR4 GPU Support Override',
        'optiscaler-fsr4-gpu-support',
        'FSR_Fsr4GpuSupport',
        [
            {id: 'auto', name: 'Auto', value: 'auto'},
            {id: '0', name: 'No override', value: 0},
            {id: '1', name: 'FP8', value: 1},
            {id: '2', name: 'INT8', value: 2},
            {id: '3', name: 'INT8-2 (RDNA2)', value: 3},
            {id: '4', name: 'INT8 Lite', value: 4},
        ],
    ),
    ...optiScalerDropdown(
        'optiscaler-fsr4-model',
        'OptiScaler FSR4 Model',
        'optiscaler-fsr4-model',
        'FSR_Fsr4Model',
        [
            {id: 'auto', name: 'Auto', value: 'auto'},
            {id: '0', name: 'FP8', value: 0},
            {id: '1', name: 'INT8', value: 1},
            {id: '2', name: 'INT8 RDNA2', value: 2},
            {id: '3', name: 'INT8 Lite', value: 3},
        ],
    ),
    ...optiScalerDropdown(
        'optiscaler-fsr-fg-index',
        'OptiScaler FSR FrameGen Backend',
        'optiscaler-fsr-fg-index',
        'FSR_FGIndex',
        [
            {id: 'auto', name: 'Auto', value: 'auto'},
            {id: '0', name: 'Backend 0 (runtime order)', value: 0},
            {id: '1', name: 'Backend 1 (runtime order)', value: 1},
        ],
    ),
    ...mfgOptions,
    ...dynamicMfgOptions,
    ...optiScalerDropdown(
        'optiscaler-xefg-rounding-dmfg',
        'OptiScaler XeFG Dynamic MFG Target Rounding',
        'optiscaler-xefg-rounding-dmfg',
        'XeFG_RoundingDMFG',
        [
            {id: 'auto', name: 'Auto', value: 'auto'},
            {id: '0', name: 'At most target', value: 0},
            {id: '1', name: 'Around target', value: 1},
            {id: '2', name: 'At least target', value: 2},
        ],
    ),
    ...vsyncOptions,
    ...syncIntervalOptions,
]

const recipe = {
    "name": "OptiScaler",
    launchOptions,
} satisfies Recipe

export default recipe
