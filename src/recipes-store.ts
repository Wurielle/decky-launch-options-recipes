import {Store} from '@tanstack/react-store'
import {produce} from 'immer'

export const defaultRecipesSource = 'https://raw.githubusercontent.com/Wurielle/decky-launch-options-recipes/refs/heads/dev/recipes.json'
export const recipesStorageKey = 'decky-launch-options-recipes-store'

type RecipesState = {recipesSource: string}
type RecipesStorage = Pick<Storage, 'getItem' | 'setItem'>

function loadRecipesSource(storage: RecipesStorage) {
    try {
        const saved = JSON.parse(storage.getItem(recipesStorageKey) ?? 'null')
        if (typeof saved?.recipesSource === 'string' && saved.recipesSource.trim()) {
            return saved.recipesSource.trim()
        }
    } catch (error) {
        console.error('Could not load recipes source', error)
    }
    return defaultRecipesSource
}

export function createRecipesStore(storage: RecipesStorage) {
    const store = new Store<RecipesState, (state: RecipesState) => void>({
        recipesSource: loadRecipesSource(storage),
    }, {
        updateFn: (state) => (updater) => produce(state, updater),
    })
    store.subscribe(({currentVal}) => {
        try {
            storage.setItem(recipesStorageKey, JSON.stringify(currentVal))
        } catch (error) {
            console.error('Could not save recipes source', error)
        }
    })
    return store
}
