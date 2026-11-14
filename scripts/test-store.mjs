import assert from 'node:assert/strict'
import {spawnSync} from 'node:child_process'
import {copyFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync} from 'node:fs'
import {tmpdir} from 'node:os'
import path from 'node:path'
import {fileURLToPath} from 'node:url'
import {test} from 'node:test'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const revision = '1234567890abcdef1234567890abcdef12345678'

function fixture(t) {
    const directory = mkdtempSync(path.join(tmpdir(), 'recipe-store-'))
    t.after(() => rmSync(directory, {recursive: true, force: true}))
    const compiled = path.join(directory, '.generated/recipes-build')
    for (const name of ['recipes/beta', 'recipes/shared', '.generated/recipes-build/scripts', '.generated/recipes-build/recipes/beta', '.generated/recipes-build/recipes/shared']) {
        mkdirSync(path.join(directory, name), {recursive: true})
    }
    writeFileSync(path.join(directory, 'package.json'), '{"type":"module"}')
    for (const file of ['scripts/build-recipes.js', 'store.config.js', 'recipes/shared/remote-script.js']) {
        copyFileSync(path.join(root, '.generated/recipes-build', file), path.join(compiled, file))
    }
    for (const [source, name, helper] of [['alpha.ts', 'Alpha', './shared/remote-script.js'], ['beta/index.ts', 'Beta', '../shared/remote-script.js']]) {
        writeFileSync(path.join(directory, 'recipes', source), '// Discovery fixture')
        writeFileSync(path.join(compiled, 'recipes', source.replace(/\.ts$/, '.js')), `
            import {remoteScript} from '${helper}'
            export default {
                name: '${name}',
                launchOptions: [{id: '${name.toLowerCase()}', on: remoteScript('example', 'install')}],
            }
        `)
    }
    writeFileSync(path.join(directory, 'recipes/shared/index.ts'), '// Must be ignored')
    writeFileSync(path.join(compiled, 'recipes/shared/index.js'), 'throw new Error("Shared modules are not recipes")')
    writeFileSync(path.join(directory, 'recipes.json'), JSON.stringify([{name: 'Beta'}, {name: 'Alpha'}]))
    const git = (...args) => {
        const result = spawnSync('git', args, {cwd: directory, encoding: 'utf8'})
        assert.equal(result.status, 0, result.stderr)
    }
    git('init', '--quiet', '--initial-branch=feature/store/test')
    git('add', 'recipes.json')
    git('-c', 'user.name=Store Test', '-c', 'user.email=store@example.invalid', 'commit', '--quiet', '-m', 'fixture')
    return {
        git,
        read: (name) => readFileSync(path.join(directory, name), 'utf8'),
        build(overrides = {}) {
            const env = {
                ...process.env,
                RECIPE_REPOSITORY_OWNER: 'Wurielle',
                RECIPE_REPOSITORY_NAME: 'decky-launch-options-recipes',
                RECIPE_COMMIT_SHA: revision,
                RECIPE_BRANCH: 'dev',
                ...overrides,
            }
            for (const [key, value] of Object.entries(env)) {
                if (value === undefined) delete env[key]
            }
            return spawnSync(process.execPath, [path.join(compiled, 'scripts/build-recipes.js')], {
                cwd: directory, env, encoding: 'utf8',
            })
        },
    }
}

test('store contains only metadata while recipes retain their order and commit pins', (t) => {
    const project = fixture(t)
    const result = project.build()
    assert.equal(result.status, 0, result.stderr)
    const store = JSON.parse(project.read('store.json'))
    const recipes = JSON.parse(project.read('recipes.json'))
    assert.deepEqual(Object.keys(store), ['name', 'description', 'type', 'github'])
    assert.equal(store.name, 'Decky Launch Options Recipes')
    assert.ok(store.description.trim())
    assert.equal(store.type, 'github')
    assert.deepEqual(store.github, {repository: 'Wurielle/decky-launch-options-recipes', branch: 'dev'})
    assert.deepEqual(recipes.map(recipe => recipe.name), ['Beta', 'Alpha'])
    assert.equal(recipes[0].launchOptions[0].on, `~/.dlor/run example install ${revision} -- %command%`)
    const original = project.read('store.json')
    assert.equal(project.build().status, 0)
    assert.equal(project.read('store.json'), original)
})

test('fork metadata and runner commands use the same repository and preserve branch slashes', (t) => {
    const project = fixture(t)
    const result = project.build({
        RECIPE_REPOSITORY_OWNER: 'example', RECIPE_REPOSITORY_NAME: 'custom-recipes', RECIPE_BRANCH: 'feature/my-store',
    })
    assert.equal(result.status, 0, result.stderr)
    const store = JSON.parse(project.read('store.json'))
    const recipes = JSON.parse(project.read('recipes.json'))
    assert.equal(store.github.repository, 'example/custom-recipes')
    assert.equal(store.github.branch, 'feature/my-store')
    assert.equal(recipes[0].launchOptions[0].on, `DLOR_REPOSITORY="example/custom-recipes" ~/.dlor/run example install ${revision} -- %command%`)
})

test('local builds infer the checked-out branch when RECIPE_BRANCH is absent', (t) => {
    const project = fixture(t)
    const result = project.build({RECIPE_BRANCH: undefined})
    assert.equal(result.status, 0, result.stderr)
    assert.equal(JSON.parse(project.read('store.json')).github.branch, 'feature/store/test')
})

test('detached builds require an explicit branch and leave the existing catalog untouched on failure', (t) => {
    const project = fixture(t)
    project.git('checkout', '--quiet', '--detach')
    const original = project.read('recipes.json')
    const result = project.build({RECIPE_BRANCH: undefined})
    assert.notEqual(result.status, 0)
    assert.match(result.stderr, /Set RECIPE_BRANCH/)
    assert.equal(project.read('recipes.json'), original)
    assert.equal(project.build({RECIPE_BRANCH: 'dev'}).status, 0)
})
