import {
    ButtonItem,
    DialogBody,
    DialogButton,
    ModalRoot,
    PanelSection,
    PanelSectionRow,
    showModal,
    Spinner,
    staticClasses,
    TextField,
} from "@decky/ui";
import {definePlugin} from "@decky/api"
import {FaList} from "react-icons/fa";
import {QueryClientProvider} from "@tanstack/react-query";
import {queryClient, useGetRecipesQuery} from "./query";
import {useCallback, useState} from "react";
import {v4 as uuid} from 'uuid';
import {Store, StoreOptions, useStore} from '@tanstack/react-store'
import {produce} from "immer";

const defaultRecipesSource = 'https://raw.githubusercontent.com/Wurielle/decky-launch-options-recipes/refs/heads/dev/recipes.json'

function createStore<S>(state: S, options: StoreOptions<S, (state: S) => void> = {}) {
    return new Store<S, (state: S) => void>(state, {
        updateFn: (state) => (updater) => produce(state, updater),
        ...options
    });
}

const localStorageKey = 'decky-launch-options-recipes-store'
const storageStoreValue = localStorage.getItem(localStorageKey)
const recipesStore = createStore({
    recipesSource: defaultRecipesSource,
    ...(storageStoreValue ? JSON.parse(storageStoreValue) : {})
});
recipesStore.subscribe(({currentVal}) => {
    localStorage.setItem(localStorageKey, JSON.stringify(currentVal))
})

function RecipesSourceFormModal(props: { onCancel: () => void }) {
    const {onCancel} = props;
    const recipesSource = useStore(recipesStore, (s) => s.recipesSource)
    const setRecipesSource = useCallback((value: string) => {
        recipesStore.setState((state) => {
            state.recipesSource = value
        })
    }, [])
    return (
        <ModalRoot onCancel={onCancel}>
            <DialogBody>
                <TextField style={{marginBottom: 0}} label={'Recipes source'}
                           value={recipesSource}
                           onChange={(e) => setRecipesSource(e.target.value)}/>

                <div style={{display: 'flex', flexDirection: 'column', gap: '10px'}}>
                    <DialogButton
                        onClick={() => navigator.clipboard.readText().then((value) => setRecipesSource(value))}
                    >
                        Paste value from clipboard
                    </DialogButton>
                    <DialogButton
                        onClick={() => setRecipesSource(defaultRecipesSource)}
                    >
                        Reset
                    </DialogButton>
                </div>
            </DialogBody>
        </ModalRoot>
    )
}

function Content() {
    const [id, setId] = useState(uuid())
    const recipesSource = useStore(recipesStore, (s) => s.recipesSource)
    const {data, isLoading} = useGetRecipesQuery(`${recipesSource}?id=${id}`)
    return (
        <>
            <PanelSection>
                <PanelSectionRow>
                    <ButtonItem
                        layout="below"
                        onClick={() => {
                            const modalResult = showModal(
                                <RecipesSourceFormModal
                                    onCancel={() => modalResult.Close()}
                                />
                            )
                        }}
                    >
                        Manage recipes source
                    </ButtonItem>
                </PanelSectionRow>
            </PanelSection>
            <PanelSection title={'Recipes'}>
                <PanelSectionRow>
                    <ButtonItem
                        layout="below"
                        onClick={() => setId(uuid())}
                    >
                        Refetch recipes
                    </ButtonItem>
                </PanelSectionRow>
                {
                    isLoading ? (
                        <div style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            marginTop: '10px'
                        }}>
                            <Spinner
                                width={24}
                                height={24}
                            />
                        </div>
                    ) : data && Boolean(data.length) ? data.map((recipe) => (
                        <PanelSectionRow key={recipe.name}>
                            <ButtonItem
                                layout="below"
                                onClick={() => {
                                    window.dispatchEvent(new CustomEvent('dlo-add-launch-options', {
                                        detail: recipe.launchOptions
                                    }));
                                }}
                            >
                                {recipe.name}
                            </ButtonItem>
                        </PanelSectionRow>
                    )) : (<p style={{textAlign: 'center'}}>No recipes found</p>)
                }
            </PanelSection>
        </>
    );
}

export default definePlugin(() => {
    return {
        name: "Launch Options Recipes",
        titleView: <div className={staticClasses.Title}>Launch Options Recipes</div>,
        content:
            <QueryClientProvider client={queryClient}>
                <Content/>
            </QueryClientProvider>,
        icon: <FaList/>,
        onDismount() {
            localStorage.removeItem(localStorageKey)
        },
    };
});
