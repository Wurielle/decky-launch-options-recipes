// Generate a self-contained command. The runner downloads the script on every launch.
export function remoteScript(recipe: string, script: string) {
    const required = (name: string, pattern: RegExp) => {
        const value = process.env[name]
        if (!value || !pattern.test(value)) throw new Error(`Missing or invalid ${name}`)
        return value
    }
    const owner = required('RECIPE_REPOSITORY_OWNER', /^[\w.-]+$/)
    const repository = required('RECIPE_REPOSITORY_NAME', /^[\w.-]+$/)
    const revision = required('RECIPE_COMMIT_SHA', /^[a-f0-9]{40}$/)
    const sourceRepository = `${owner}/${repository}`
    const prefix = sourceRepository === 'Wurielle/decky-launch-options-recipes'
        ? '' : `DLOR_REPOSITORY="${sourceRepository}" `
    // Keep generated commands pinned even though the runner accepts an omitted SHA.
    return `${prefix}~/.dlor/run ${recipe} ${script} ${revision} -- %command%`
}
