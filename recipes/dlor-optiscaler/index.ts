import type { LaunchOption, Recipe } from '../shared/types.js'

const group = 'DLOR OptiScaler'
// Refreshed with the shell entrypoints by scripts/update-source-hashes.py.
const launchSha256 = '90702109f4d5a9777f130264db7a67776d6f8c46c39c26d946f982b90109d4ff'
const required = (name: string, pattern: RegExp) => {
    const value = process.env[name]
    if (!value || !pattern.test(value)) throw new Error(`Missing or invalid ${name}`)
    return value
}
const repository = `${required('RECIPE_REPOSITORY_OWNER', /^[\w.-]+$/)}/${required('RECIPE_REPOSITORY_NAME', /^[\w.-]+$/)}`
const revision = required('RECIPE_COMMIT_SHA', /^[a-f0-9]{40}$/)
const url = `https://raw.githubusercontent.com/${repository}/${revision}/recipes/dlor-optiscaler/scripts/launch.sh`
// The current runner only executes helpers. Acquire the complete wrapper here;
// all logging, caching, preparation and game handoff remain in the scripts.
// Host cleanup's /* must precede the first '=' for DLO's assignment parser.
// A gated, direct-exec coprocess keeps cancellation interruptible and child-only;
// job specs cannot target a recycled PID. Disable job control to avoid group kills.
// read preserves source newlines. Locals and saved REPLY restore caller exports.
const bootstrap = [
    'h() { case "${STEAM_RUNTIME-}" in /*)',
    'export PATH="${SYSTEM_PATH:-/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin}" LD_LIBRARY_PATH="${SYSTEM_LD_LIBRARY_PATH-}";',
    'unset STEAM_RUNTIME;; esac; unset LD_PRELOAD; exec "$@"; }; set +m;',
    'a() { local COPROC COPROC_PID p f;',
    'c() { trap "" INT TERM; kill -9 %+ 2>/dev/null; wait %+ 2>/dev/null; exit "$1"; };',
    'trap "c 130" INT; trap "c 143" TERM;',
    `coproc { read -r; h curl -fsSL --proto '=https' --proto-redir '=https' --connect-timeout 10 --max-time 60 "${url}" </dev/null; };`,
    'p=$!;exec {f}<&"${COPROC[0]}";echo >&"${COPROC[1]}";',
    'IFS= read -rd "" REPLY <&"$f";exec {f}<&-;',
    'wait "$p" || REPLY=;trap - INT TERM;',
    `[[ $(printf %s "$REPLY" | h sha256sum) == "${launchSha256}  -" ]] || REPLY=; };`,
    'set -- "${REPLY+x}" "${REPLY-}" "$@";a;set -- "$REPLY" "$@";',
    '[[ $2 ]] && REPLY=$3 || unset REPLY;',
    `if [[ $1 ]]; then export DLOR_OPTISCALER_SOURCE_REVISION="${revision}" DLOR_OPTISCALER_SOURCE_REPOSITORY="${repository}";`,
    'exec bash -c "$1" -- "${@:4}"; fi;',
    'printf "DLOR OptiScaler: invalid launcher; continuing original game.\\n" >&2;',
    'shift 3; exec "$@"',
].join('')
const launch = `bash -c '${bootstrap.replace(/'/g, "'\\''")}' -- %command%`

// The core always uses the official nightly and its supporting-DLL layout.
// None preserves proxy/profile policy; OptiPatcher remains opt-in.
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
            on: `DLOR_OPTISCALER_ACTION="install" ${launch}`,
            off: `DLOR_OPTISCALER_ACTION="uninstall" ${launch}`,
            enableGlobally: false,
        },
        ...choices('proxy', 'Injection proxy', 'DLOR_OPTISCALER_PROXY', [
            'dxgi', 'winmm', 'version', 'd3d12', 'dbghelp', 'wininet', 'winhttp',
        ]),
        // Compatibility profiles use a third-party distribution, not an AMD
        // driver installer. None leaves runtime/user policy intact (bundled).
        ...choices('fsr-profile', 'FSR4 compatibility (third-party)', 'DLOR_OPTISCALER_FSR_PROFILE', [
            'bundled', 'rdna23-int8', 'rdna34-official-411', 'rdna2-valve-411',
        ]),
        {
            id: 'dlor-optiscaler-optipatcher',
            group,
            name: 'OptiPatcher',
            on: 'DLOR_OPTISCALER_OPTIPATCHER="1"',
            off: 'DLOR_OPTISCALER_OPTIPATCHER="0"',
            enableGlobally: false,
        },
    ],
} satisfies Recipe

export default recipe
