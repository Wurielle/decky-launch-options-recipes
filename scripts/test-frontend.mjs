// Offline regression checks: node --test scripts/test-frontend.mjs
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {createRequire} from 'node:module'
import {test} from 'node:test'
import {runInNewContext} from 'node:vm'
import ts from 'typescript'

const require = createRequire(import.meta.url)

function loadSource(path, globals = {}, modules = {}) {
    const source = readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8')
    const {outputText} = ts.transpileModule(source, {
        compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX},
    })
    const exports = {}
    runInNewContext(outputText, {
        exports,
        require: (name) => name in modules ? modules[name] : require(name),
        console: {error() {}},
        ...globals,
    })
    return exports
}

const {createRecipesStore, defaultRecipesSource, recipesStorageKey} = loadSource('recipes-store.ts')
const customSource = 'https://raw.githubusercontent.com/example/recipes/refs/heads/feature/test/recipes.json'

function storage(initial) {
    const values = new Map(initial === undefined ? [] : [[recipesStorageKey, initial]])
    return {
        getItem: (key) => values.get(key) ?? null,
        setItem: (key, value) => values.set(key, value),
        removeItem: (key) => values.delete(key),
    }
}

test('custom source survives a plugin dismount and a fresh module/store load', () => {
    const saved = storage()
    const modules = {
        'react/jsx-runtime': {jsx: () => ({}), jsxs: () => ({})},
        'react': {},
        'react-icons/fa': {},
        '@tanstack/react-query': {},
        '@decky/ui': {staticClasses: {}},
        '@decky/api': {definePlugin: (initialize) => initialize},
        './query': {},
        './clipboard': {},
        './logs': {},
        './recipes-store': {createRecipesStore, defaultRecipesSource},
    }
    const store = createRecipesStore(saved)
    store.setState((state) => { state.recipesSource = customSource })
    const plugin = loadSource('index.tsx', {localStorage: saved}, modules).default()
    plugin.onDismount?.()
    const reloaded = loadSource('recipes-store.ts').createRecipesStore(saved)
    assert.equal(reloaded.state.recipesSource, customSource)
})

test('reset remains saved after reloading', () => {
    const saved = storage(JSON.stringify({recipesSource: customSource}))
    const store = createRecipesStore(saved)
    store.setState((state) => { state.recipesSource = defaultRecipesSource })
    assert.equal(createRecipesStore(saved).state.recipesSource, defaultRecipesSource)
})

test('missing, malformed, or invalid saved settings fall back safely', () => {
    for (const value of [undefined, '{broken', 'null', '[]', '{}', '{"recipesSource":42}', '{"recipesSource":"  "}']) {
        assert.equal(createRecipesStore(storage(value)).state.recipesSource, defaultRecipesSource)
    }
})

test('storage failures do not break editing or loading the plugin', () => {
    const saved = {
        getItem() { throw new Error('Storage unavailable') },
        setItem() { throw new Error('Quota exceeded') },
    }
    const store = createRecipesStore(saved)
    assert.equal(store.state.recipesSource, defaultRecipesSource)
    store.setState((state) => { state.recipesSource = customSource })
    assert.equal(store.state.recipesSource, customSource)
})

function clipboardFixture(paste, {native = true, readText, keyboardPaste} = {}) {
    let textarea
    let removed = false
    let restored = false
    const keyEvents = []
    const previousFocus = {focus() { restored = true; doc.activeElement = previousFocus }}
    const browser = {Paste() { return paste(textarea, doc) }}
    const doc = {
        activeElement: previousFocus,
        defaultView: {navigator: {clipboard: {readText}}},
        createElement() {
            textarea = new EventTarget()
            Object.assign(textarea, {
                style: {}, value: '',
                focus() { doc.activeElement = textarea },
                remove() { removed = true },
            })
            return textarea
        },
    }
    if (native) doc.defaultView.SteamClient = {Browser: browser}
    const container = {ownerDocument: doc, appendChild(element) { assert.equal(element, textarea) }}
    const {readClipboardText} = loadSource('clipboard.ts', {
        setTimeout: (callback) => setTimeout(callback, 100), clearTimeout,
        setInterval: (callback) => setInterval(callback, 1), clearInterval,
        // The shared JS context is separate from the dialog's document/window.
        document: {body: {}, createElement() { throw new Error('Wrong document') }},
        ...(keyboardPaste ? {SteamClient: {Input: {
            ControllerKeyboardSetKeyState(key, pressed) {
                keyEvents.push([key, pressed])
                if (key === 25 && pressed) keyboardPaste(textarea)
            },
        }}} : {}),
    })
    return {
        read: () => readClipboardText(container),
        keyEvents,
        assertCleanedUp() { assert.equal(removed, true); assert.equal(restored, true) },
    }
}

test('uses virtual keyboard paste even when the browser clipboard is empty', async () => {
    const fixture = clipboardFixture(() => { throw new Error('Browser paste must not be used') }, {
        keyboardPaste(textarea) {
            textarea.value = customSource
            textarea.dispatchEvent(new Event('input'))
        },
    })
    assert.equal(await fixture.read(), customSource)
    assert.deepEqual(fixture.keyEvents, [[103, true], [25, true], [25, false], [103, false]])
    fixture.assertCleanedUp()
})

test('releases both keys if virtual keyboard paste fails', async () => {
    const fixture = clipboardFixture(undefined, {
        keyboardPaste() { throw new Error('Keyboard failure') },
    })
    await assert.rejects(fixture.read(), /Keyboard failure/)
    assert.deepEqual(fixture.keyEvents, [[103, true], [25, true], [25, false], [103, false]])
    fixture.assertCleanedUp()
})

test('paste uses the dialog window and restores its focus', async () => {
    const fixture = clipboardFixture((textarea) => {
        const event = new Event('paste', {cancelable: true})
        event.clipboardData = {getData: () => customSource}
        textarea.dispatchEvent(event)
    })
    assert.equal(await fixture.read(), customSource)
    fixture.assertCleanedUp()
})

test('native input without a paste event is captured', async () => {
    const fixture = clipboardFixture((textarea) => {
        textarea.value = customSource
        textarea.dispatchEvent(new Event('input'))
    })
    assert.equal(await fixture.read(), customSource)
    fixture.assertCleanedUp()
})

test('native input without any DOM event is captured', async () => {
    const fixture = clipboardFixture((textarea) => { textarea.value = customSource })
    assert.equal(await fixture.read(), customSource)
    fixture.assertCleanedUp()
})

test('empty clipboard paste is reported as empty', async () => {
    const fixture = clipboardFixture((textarea) => {
        const event = new Event('paste', {cancelable: true})
        event.clipboardData = {getData: () => ''}
        textarea.dispatchEvent(event)
    })
    assert.equal(await fixture.read(), '')
    fixture.assertCleanedUp()
})

test('synchronous and asynchronous native failures clean up', async () => {
    for (const paste of [() => { throw new Error('Native failure') }, () => Promise.reject(new Error('Native failure'))]) {
        const fixture = clipboardFixture(paste)
        await assert.rejects(fixture.read(), /Native failure/)
        fixture.assertCleanedUp()
    }
})

test('native paste timeout cleans up and restores focus', async () => {
    const fixture = clipboardFixture(() => {})
    await assert.rejects(fixture.read(), /timed out/)
    fixture.assertCleanedUp()
})

test('standard browser clipboard works without Steam', async () => {
    const fixture = clipboardFixture(undefined, {native: false, readText: async () => customSource})
    assert.equal(await fixture.read(), customSource)
})

test('unavailable clipboard rejects instead of throwing synchronously', async () => {
    const fixture = clipboardFixture(undefined, {native: false})
    await assert.rejects(fixture.read(), /unavailable/)
})
