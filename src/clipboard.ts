export function readClipboardText(): Promise<string> {
    if (typeof SteamClient === 'undefined' || typeof SteamClient.Browser?.Paste !== 'function') {
        return navigator.clipboard.readText()
    }

    // Steam's browser blocks clipboard reads but supports its native paste command.
    return new Promise((resolve, reject) => {
        const previousFocus = document.activeElement
        const textarea = document.createElement('textarea')
        textarea.tabIndex = -1
        textarea.style.cssText = 'position: fixed; opacity: 0; width: 1px; height: 1px; pointer-events: none;'

        const cleanup = () => {
            clearTimeout(timeout)
            const restoreFocus = document.activeElement === textarea
            textarea.remove()
            if (restoreFocus && previousFocus instanceof HTMLElement) {
                previousFocus.focus({preventScroll: true})
            }
        }
        const timeout = setTimeout(() => {
            cleanup()
            reject(new Error('Steam clipboard paste timed out'))
        }, 3000)

        textarea.addEventListener('paste', (event) => {
            event.preventDefault()
            const text = event.clipboardData?.getData('text/plain') ?? ''
            cleanup()
            resolve(text)
        }, {once: true})

        document.body.appendChild(textarea)
        textarea.focus({preventScroll: true})
        try {
            SteamClient.Browser.Paste()
        } catch (error) {
            cleanup()
            reject(error)
        }
    })
}
