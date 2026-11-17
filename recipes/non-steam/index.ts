import type { LaunchOption, Recipe } from '../shared/types.js'
import { remoteScript } from '../shared/remote-script.js'

const group = 'Non-Steam'
const resizeWindow = remoteScript('non-steam', 'resize-window')
const scalingPercentages = [100, 125, 150, 175, 200, 250, 300] as const
const sizes = [
    [1280, 720],
    [1280, 800],
    [1920, 1080],
    [1920, 1200],
    [2560, 1440],
    [2560, 1600],
    [3840, 2160],
] as const

const none = (option: string, name: string): LaunchOption => ({
    id: `non-steam-app-${option}-none`,
    group,
    name,
    on: '',
    off: '',
    enableGlobally: false,
    valueId: `non-steam-app-${option}`,
    valueName: 'None',
    fallbackValue: true,
})

// GTK requires integer window scaling; Qt and Chromium also accept fractions.
// Keep the toolkit explicit instead of promising one scale flag works everywhere.
const scalingOptions: LaunchOption[] = [
    none('scaling', 'App Scaling'),
    ...scalingPercentages.flatMap((percentage): LaunchOption[] => {
        const scale = percentage / 100
        const integer = Number.isInteger(scale)
        const toolkit = integer ? 'gtk-qt' : 'qt'
        return [
            {
                id: `non-steam-app-scaling-${toolkit}-${percentage}`,
                group,
                name: 'App Scaling',
                on: `${integer ? `GDK_SCALE="${scale}" ` : ''}QT_SCALE_FACTOR="${scale}"`,
                off: '',
                enableGlobally: false,
                valueId: 'non-steam-app-scaling',
                valueName: `${percentage}% (${integer ? 'GTK / Qt' : 'Qt'})`,
            },
            {
                id: `non-steam-app-scaling-chromium-electron-${percentage}`,
                group,
                name: 'App Scaling',
                on: `%command% --force-device-scale-factor=${scale}`,
                off: '',
                enableGlobally: false,
                valueId: 'non-steam-app-scaling',
                valueName: `${percentage}% (Chromium / Electron)`,
            },
        ]
    }),
]

// Resize the app itself. A nested compositor can lose Steam's app attribution
// and duplicate performance overlays. The helper runs asynchronously before the
// app starts; the shared runner preserves the app's argv and Steam environment.
const sizeOptions: LaunchOption[] = [
    none('size', 'App Size'),
    ...[{id: 'fullscreen', name: 'Fullscreen', value: 'fullscreen'}, ...sizes.map(([width, height]) => ({
        id: `windowed-${width}x${height}`,
        name: `${width} × ${height}`,
        value: `${width}x${height}`,
    }))].map((size): LaunchOption => ({
        id: `non-steam-app-size-${size.id}`,
        group,
        name: 'App Size',
        on: `DLOR_NON_STEAM_APP_SIZE="${size.value}" `
            + 'GDK_BACKEND="x11" QT_QPA_PLATFORM="xcb" MOZ_ENABLE_WAYLAND="0" '
            + resizeWindow,
        off: '',
        enableGlobally: false,
        valueId: 'non-steam-app-size',
        valueName: size.name,
    })),
]

const recipe = {
    name: 'Non-Steam',
    launchOptions: [...scalingOptions, ...sizeOptions],
} satisfies Recipe

export default recipe
