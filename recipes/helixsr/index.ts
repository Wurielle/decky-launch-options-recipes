import { readFileSync } from 'node:fs'
import type { Recipe } from '../shared/types.js'
import { remoteScript } from '../shared/remote-script.js'

const shellQuote = (value: string) => `'${value.replace(/'/g, "'\\''")}'`
// pnpm runs generation at the repository root. The embedded launcher preserves
// original argv and exports the selected Wine override after host setup.
let launcher = readFileSync('recipes/helixsr/launcher.sh', 'utf8')
for (const script of ['setup', 'dependency', 'configure']) {
    const command = remoteScript('helixsr', script)
        .replace('~/.dlor/run', '"$HOME/.dlor/run"')
        .replace('%command%', '/bin/true')
    launcher = launcher.split(`@@${script.toUpperCase()}@@`).join(command)
}
const launch = `bash -c ${shellQuote(launcher)} -- %command%`

const recipe = {
    name: 'HelixSR',
    launchOptions: [
        {
            id: 'helixsr',
            group: 'HelixSR',
            name: 'HelixSR (OptiScaler DX12)',
            on: `DLOR_HELIXSR_ACTION="on" ${launch}`,
            off: `DLOR_HELIXSR_ACTION="off" ${launch}`,
            enableGlobally: false,
            priority: -2,
        },
    ],
} satisfies Recipe

export default recipe
