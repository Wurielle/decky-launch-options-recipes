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
import {useCallback, useEffect, useLayoutEffect, useRef, useState} from "react";
import {v4 as uuid} from 'uuid';
import {Store, StoreOptions, useStore} from '@tanstack/react-store'
import {produce} from "immer";
import {readClipboardText} from "./clipboard";
import {BrowseLogsButton} from "./logs";

const defaultRecipesSource = 'https://raw.githubusercontent.com/Wurielle/decky-launch-options-recipes/refs/heads/dev/recipes.json'

function getGitHubSourceDescription(value: string) {
    try {
        const url = new URL(value.trim())
        if (url.hostname !== 'raw.githubusercontent.com' || !['https:', 'http:'].includes(url.protocol)) {
            return undefined
        }

        const [owner, repository, ...path] = url.pathname.slice(1).split('/').map(decodeURIComponent)
        const explicitRef = path[0] === 'refs'
        if (explicitRef && path[1] !== 'heads' && path[1] !== 'tags') return undefined
        const refIndex = explicitRef ? 2 : 0
        if (!owner || !repository || !path.slice(refIndex).every(Boolean) || path.length <= refIndex + 1) {
            return undefined
        }

        // For explicit refs, infer the branch/tag from everything before the recipe filename.
        const ref = explicitRef ? path.slice(refIndex, -1).join('/') : path[refIndex]
        const refLabel = explicitRef && path[1] === 'tags' ? 'Tag' : /^[a-f\d]{40}$/i.test(ref) ? 'Commit' : 'Branch'
        return {owner, repository, refLabel, ref}
    } catch {
        return undefined
    }
}

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

function useButtonFeedback() {
    const [feedback, setFeedback] = useState({text: ''})
    useEffect(() => {
        if (!feedback.text) return
        const timeout = setTimeout(() => setFeedback({text: ''}), 2000)
        return () => clearTimeout(timeout)
    }, [feedback])
    const showFeedback = useCallback((text: string) => setFeedback({text}), [])
    return [feedback.text, showFeedback] as const
}

function RecipesSourceFormModal(props: { onCancel: () => void }) {
    const {onCancel} = props;
    const recipesSource = useStore(recipesStore, (s) => s.recipesSource)
    const [pasteFeedback, setPasteFeedback] = useButtonFeedback()
    const [resetFeedback, setResetFeedback] = useButtonFeedback()
    const [isPasting, setIsPasting] = useState(false)
    const sourceDescription = getGitHubSourceDescription(recipesSource)
    const setRecipesSource = useCallback((value: string) => {
        recipesStore.setState((state) => {
            state.recipesSource = value
        })
    }, [])
    const pasteRecipesSource = async () => {
        setIsPasting(true)
        setPasteFeedback('')
        try {
            const value = (await readClipboardText()).trim()
            if (!value) {
                setPasteFeedback('❌ Clipboard is empty')
                return
            }
            setRecipesSource(value)
            setPasteFeedback('✅ Pasted from clipboard')
        } catch {
            setPasteFeedback('❌ Paste failed')
        } finally {
            setIsPasting(false)
        }
    }
    const resetRecipesSource = () => {
        try {
            setRecipesSource(defaultRecipesSource)
            setResetFeedback('✅ Reset to default')
        } catch {
            setResetFeedback('❌ Reset failed')
        }
    }
    return (
        <ModalRoot onCancel={onCancel}>
            <DialogBody>
                <TextField
                    style={{marginBlock: 0}}
                    label={'Recipes source'}
                    disabled={isPasting}
                    value={recipesSource}
                    onChange={(e) => setRecipesSource(e.target.value)}
                    description={sourceDescription && (
                        <div style={{
                            fontSize: '14px',
                            textAlign: 'left',
                            overflowWrap: 'anywhere',
                            display: 'flex',
                            flexDirection: 'column',
                            gap: '2px',
                            marginBlock: 0,
                            paddingBlock: 0,
                        }}>
                            <div><strong>User:</strong> {sourceDescription.owner}</div>
                            <div><strong>Repository:</strong> {sourceDescription.repository}</div>
                            <div><strong>{sourceDescription.refLabel}:</strong> {sourceDescription.ref}</div>
                        </div>
                    )}
                />

                <div style={{display: 'flex', flexDirection: 'column', gap: '10px'}}>
                    <DialogButton
                        disabled={isPasting}
                        onClick={pasteRecipesSource}
                    >
                        <span aria-live="polite">
                            {isPasting ? 'Reading clipboard…' : pasteFeedback || 'Paste value from clipboard'}
                        </span>
                    </DialogButton>
                    <DialogButton
                        disabled={isPasting}
                        onClick={resetRecipesSource}
                    >
                        <span aria-live="polite">{resetFeedback || 'Reset'}</span>
                    </DialogButton>
                </div>
            </DialogBody>
        </ModalRoot>
    )
}

function resetAncestorScrollPositions(element: HTMLElement | null) {
    const ownerDocument = element?.ownerDocument ?? document
    let current = element?.parentElement

    while (current && current !== ownerDocument.body) {
        if (current.scrollTop > 0 || current.scrollHeight > current.clientHeight) {
            current.scrollTop = 0
        }
        current = current.parentElement
    }

    ownerDocument.scrollingElement?.scrollTo({top: 0})
}

function Content() {
    const contentRef = useRef<HTMLDivElement>(null)
    const [id, setId] = useState(uuid())
    const recipesSource = useStore(recipesStore, (s) => s.recipesSource)
    const {data, isLoading} = useGetRecipesQuery(`${recipesSource}?id=${id}`)
    useLayoutEffect(() => {
        const resetScroll = () => resetAncestorScrollPositions(contentRef.current)
        resetScroll()
        const frame = window.requestAnimationFrame(resetScroll)
        return () => window.cancelAnimationFrame(frame)
    }, [])

    return (
        <>
            <div ref={contentRef} style={{display: 'none'}} />
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
                <PanelSectionRow>
                    <BrowseLogsButton/>
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
