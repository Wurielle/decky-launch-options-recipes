// Open Manage recipes source on the test device with a recipe URL copied there.
// This checks the real installed plugin button without replacing the clipboard.
import assert from 'node:assert/strict'
import {mkdir} from 'node:fs/promises'
import {withConsoleUI} from './console-ui.mjs'

await withConsoleUI(async ({page, shared}) => {
    if (!page || !shared) throw new Error('Steam Big Picture Mode and SharedJSContext must be available')
    const dialog = page.getByRole('dialog').filter({has: page.getByRole('textbox', {name: /^Recipes source/})})
    await dialog.waitFor({state: 'visible', timeout: 5000})
    const field = dialog.getByRole('textbox', {name: /^Recipes source/})
    const original = await field.inputValue()
    try {
        await field.fill('')
        await dialog.getByRole('button', {name: 'Paste value from clipboard', exact: true}).click()
        await dialog.getByRole('button', {name: '✅ Pasted from clipboard', exact: true}).waitFor({state: 'visible'})
        const pasted = await field.inputValue()
        assert.ok(pasted.trim().length > 0, 'The button must paste non-empty text into the cleared field')
        assert.ok(['https:', 'http:'].includes(new URL(pasted).protocol), 'Copy a recipe source URL before running this test')
        const saved = await shared.evaluate(() => JSON.parse(localStorage.getItem('decky-launch-options-recipes-store')).recipesSource)
        assert.equal(saved, pasted, 'The pasted URL must be saved')
        await mkdir('.generated/console-ui', {recursive: true})
        await dialog.screenshot({path: '.generated/console-ui/clipboard-paste.png'})
        console.log(JSON.stringify({passed: true, pastedCharacters: pasted.length, saved: true}))
    } finally {
        // Testing must not select a different recipe source for the user.
        await field.fill(original)
    }
})
