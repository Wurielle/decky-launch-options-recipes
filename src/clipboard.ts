// Steam's keyboard key IDs (EHIDKeyboardKey), not DOM key codes.
const LEFT_CONTROL = 103
const KEY_V = 25

export function readClipboardText(container: HTMLElement = document.body): Promise<string> {
    // Decky dialogs can live in a different window from the plugin's JS context.
    const ownerDocument = container.ownerDocument
    const ownerWindow = ownerDocument.defaultView as (Window & {SteamClient?: typeof SteamClient}) | null
    const browser = ownerWindow?.SteamClient?.Browser
        ?? (typeof SteamClient === 'undefined' ? undefined : SteamClient.Browser)
    // Input's controller keyboard API lives in Steam's shared JS context. The
    // popup window exposes Browser.Paste, but that can read an empty CEF clipboard.
    const input = typeof SteamClient === 'undefined' ? ownerWindow?.SteamClient?.Input : SteamClient.Input
    const hasKeyboardPaste = typeof input?.ControllerKeyboardSetKeyState === 'function'
    if (!hasKeyboardPaste && typeof browser?.Paste !== 'function') {
        return ownerWindow?.navigator.clipboard?.readText?.()
            ?? Promise.reject(new Error('Clipboard reading is unavailable'))
    }

    // Use the same system Ctrl+V sequence as the virtual keyboard's Paste key.
    return new Promise((resolve, reject) => {
        const previousFocus = ownerDocument.activeElement as HTMLElement | null
        const textarea = ownerDocument.createElement('textarea')
        textarea.tabIndex = -1
        textarea.style.cssText = 'position: fixed; opacity: 0; width: 1px; height: 1px; pointer-events: none;'

        const cleanup = () => {
            clearTimeout(timeout)
            clearInterval(poll)
            const restoreFocus = ownerDocument.activeElement === textarea
            textarea.remove()
            if (restoreFocus) {
                previousFocus?.focus?.({preventScroll: true})
            }
        }
        const fail = (error: unknown) => {
            cleanup()
            reject(error)
        }
        const finish = (value: string) => {
            cleanup()
            resolve(value)
        }
        const timeout = setTimeout(() => {
            fail(new Error('Steam clipboard paste timed out'))
        }, 3000)
        // Steam can update the native input without emitting a DOM paste event.
        const poll = setInterval(() => {
            if (textarea.value) finish(textarea.value)
        }, 50)

        textarea.addEventListener('paste', (event) => {
            event.preventDefault()
            finish(event.clipboardData?.getData('text/plain') ?? '')
        }, {once: true})
        textarea.addEventListener('input', () => finish(textarea.value), {once: true})

        container.appendChild(textarea)
        textarea.focus({preventScroll: true})
        try {
            if (hasKeyboardPaste) {
                try {
                    input.ControllerKeyboardSetKeyState(LEFT_CONTROL, true)
                    input.ControllerKeyboardSetKeyState(KEY_V, true)
                } finally {
                    try {
                        input.ControllerKeyboardSetKeyState(KEY_V, false)
                    } finally {
                        input.ControllerKeyboardSetKeyState(LEFT_CONTROL, false)
                    }
                }
            } else {
                Promise.resolve(browser!.Paste()).catch(fail)
            }
        } catch (error) {
            fail(error)
        }
    })
}
