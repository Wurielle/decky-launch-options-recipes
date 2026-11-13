import {spawn} from 'node:child_process'
import {once} from 'node:events'
import {readFile, mkdir} from 'node:fs/promises'
import {createServer} from 'node:net'
import path from 'node:path'
import {fileURLToPath} from 'node:url'
import {chromium} from 'playwright-core'

// Attach to the running Steam UI. No browser or remote desktop service is installed
// on the console, and its debugging port is reached only through an SSH tunnel.
export async function withConsoleUI(run) {
    const host = process.env.CONSOLE_SSH_HOST ?? 'console'
    const remotePort = Number(process.env.CONSOLE_CDP_PORT ?? 8080)
    if (host.startsWith('-') || !Number.isInteger(remotePort) || remotePort < 1 || remotePort > 65535) {
        throw new Error('Use an SSH host alias and a valid CONSOLE_CDP_PORT')
    }
    const server = createServer()
    server.listen(0, '127.0.0.1')
    await once(server, 'listening')
    const port = server.address().port
    await new Promise((resolve) => server.close(resolve))
    const tunnel = spawn('ssh', [
        '-N', '-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
        '-o', 'ExitOnForwardFailure=yes',
        '-L', `127.0.0.1:${port}:127.0.0.1:${remotePort}`, host,
    ], {stdio: ['ignore', 'ignore', 'pipe']})
    let sshError = ''
    tunnel.stderr.on('data', (data) => { sshError += data })
    let spawnError
    tunnel.on('error', (error) => { spawnError = error })
    try {
        const endpoint = `http://127.0.0.1:${port}`
        let ready = false
        for (let attempt = 0; attempt < 100; attempt++) {
            if (spawnError) throw spawnError
            if (tunnel.exitCode !== null) throw new Error(`SSH failed: ${sshError.trim()}`)
            try {
                const response = await fetch(`${endpoint}/json/version`, {signal: AbortSignal.timeout(500)})
                if (response.ok) { ready = true; break }
            } catch {}
            await new Promise((resolve) => setTimeout(resolve, 100))
        }
        if (!ready) throw new Error(`Steam debugging is unavailable on ${host}:${remotePort}. ${sshError.trim()}`)
        const browser = await chromium.connectOverCDP(endpoint, {timeout: 10000})
        const pages = browser.contexts().flatMap((context) => context.pages())
        const title = process.env.CONSOLE_UI_PAGE ?? 'Steam Big Picture Mode'
        const page = (await Promise.all(pages.map(async (page) => ({page, title: await page.title()}))))
            .find((candidate) => candidate.title === title)?.page
        const shared = (await Promise.all(pages.map(async (page) => ({page, title: await page.title()}))))
            .find((candidate) => candidate.title === 'SharedJSContext')?.page
        if (page) page.setDefaultTimeout(5000)
        return await run({browser, pages, page, shared})
    } finally {
        // Disconnect without sending Browser.close to the user's running Steam.
        tunnel.kill()
    }
}

async function main() {
    const [command = 'snapshot', ...args] = process.argv.slice(2)
    if (command === 'help') {
        console.log('console-ui: pages | snapshot | screenshot [path] | click x y | click-text text | fill selector value | press key | type text | evaluate file')
        return
    }
    await withConsoleUI(async ({pages, page, shared}) => {
        if (command === 'pages') {
            console.log(JSON.stringify(await Promise.all(pages.map(async (page) => ({title: await page.title(), url: page.url().split('?')[0]}))), null, 2))
            return
        }
        if (!page) throw new Error('Steam UI window not found; use pages and set CONSOLE_UI_PAGE to its title')
        switch (command) {
            case 'snapshot':
                console.log(await page.locator('body').ariaSnapshot())
                break
            case 'screenshot': {
                const output = path.resolve(args[0] ?? '.generated/console-ui/latest.png')
                await mkdir(path.dirname(output), {recursive: true})
                await page.screenshot({path: output, timeout: 10000})
                console.log(output)
                break
            }
            case 'click':
                if (args.length !== 2 || !args.every((value) => Number.isFinite(Number(value)))) throw new Error('click requires x y')
                await page.mouse.click(Number(args[0]), Number(args[1]))
                break
            case 'click-text':
                await page.getByText(args.join(' '), {exact: true}).click()
                break
            case 'fill':
                if (args.length !== 2) throw new Error('fill requires selector value')
                await page.locator(args[0]).fill(args[1])
                break
            case 'press':
                await page.keyboard.press(args.join(' '))
                break
            case 'type':
                await page.keyboard.insertText(args.join(' '))
                break
            case 'evaluate':
                if (!shared || args.length !== 1) throw new Error('evaluate requires a JavaScript file and SharedJSContext')
                console.log(JSON.stringify(await shared.evaluate(await readFile(args[0], 'utf8')), null, 2))
                break
            default:
                throw new Error(`Unknown command: ${command}`)
        }
    })
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
    main().catch((error) => { console.error(error.message); process.exitCode = 1 })
}
