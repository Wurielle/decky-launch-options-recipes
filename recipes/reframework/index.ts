import type { LaunchOption, Recipe } from '../types.js'

const reframeworkGroup = 'REFramework'
const repositoryOwner = '{{env:RECIPE_REPOSITORY_OWNER}}'
const repositoryName = '{{env:RECIPE_REPOSITORY_NAME}}'
const commitSha = '{{env:RECIPE_COMMIT_SHA}}'
const scriptsBaseUrl = `https://raw.githubusercontent.com/${repositoryOwner}/${repositoryName}/${commitSha}/recipes/reframework/scripts`
const wineDllOverrides = 'WINEDLLOVERRIDES="dinput8.dll=n,b"'
const hostRuntime = '"${STEAM_RUNTIME}/scripts/switch-runtime.sh" --runtime="" --'
const runScript = (scriptName: string) => `bash -c '${hostRuntime} curl -fsSL --retry 3 --retry-delay 1 "${scriptsBaseUrl}/${scriptName}" | bash -s -- "$STEAM_COMPAT_INSTALL_PATH"; exec "$@"' -- %command%`

const actionValues = [
    {
        id: 'none',
        name: 'None',
        command: '',
        fallbackValue: true,
    },
    {
        id: 'install-update',
        name: 'Install/Update',
        command: `${wineDllOverrides} ${runScript('update.sh')}`,
    },
    {
        id: 'uninstall',
        name: 'Uninstall',
        command: runScript('uninstall.sh'),
    },
] as const

const launchOptions: LaunchOption[] = actionValues.map((action): LaunchOption => ({
    id: `reframework-${action.id}`,
    group: reframeworkGroup,
    name: reframeworkGroup,
    on: action.command,
    off: '',
    enableGlobally: false,
    valueId: 'reframework',
    valueName: action.name,
    ...('fallbackValue' in action && action.fallbackValue === true ? {fallbackValue: true} : {}),
}))

const recipe = {
    name: reframeworkGroup,
    launchOptions,
} satisfies Recipe

export default recipe
