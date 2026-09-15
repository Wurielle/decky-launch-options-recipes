import {callable, FileSelectionType, openFilePicker, toaster} from '@decky/api'
import {
    ButtonItem,
    Focusable,
    GamepadButton,
    ModalRoot,
    showModal,
} from '@decky/ui'
import type {GamepadEvent} from '@decky/ui'
import {useEffect, useRef, useState} from 'react'
import type {ComponentType, ReactNode} from 'react'

const SCROLL_STEP = 120

const ModalScrollContent = Focusable as ComponentType<{
    autoFocus?: boolean
    children: ReactNode
    focusable?: boolean
    noFocusRing?: boolean
    onGamepadDirection?: (event: GamepadEvent) => void
}>

function findScrollableAncestor(element: HTMLElement | null) {
    const ownerWindow = element?.ownerDocument.defaultView
    let current = element
    while (current && current !== element?.ownerDocument.body) {
        const overflowY = ownerWindow?.getComputedStyle(current).overflowY
        if ((overflowY === 'auto' || overflowY === 'scroll' || overflowY === 'overlay')
            && current.scrollHeight > current.clientHeight) return current
        current = current.parentElement
    }
    return null
}

type LogFile = {
    path: string
    content: string
    truncated: boolean
}

const getLogsDirectory = callable<[], string>('get_logs_directory')
const readLogFile = callable<[path: string], LogFile>('read_log_file')
const errorMessage = (error: unknown) => error instanceof Error ? error.message : String(error)

function LogFileModal({path, onClose}: {path: string; onClose: () => void}) {
    const [log, setLog] = useState<LogFile>()
    const [error, setError] = useState('')
    const scrollRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        let active = true
        readLogFile(path).then(
            (result) => { if (active) setLog(result) },
            (failure) => { if (active) setError(errorMessage(failure)) },
        )
        return () => { active = false }
    }, [path])

    const scrollLog = (event: GamepadEvent) => {
        const element = findScrollableAncestor(scrollRef.current)
        if (!element || (event.detail.button !== GamepadButton.DIR_UP
            && event.detail.button !== GamepadButton.DIR_DOWN)) return
        event.preventDefault()
        element.scrollBy({
            top: event.detail.button === GamepadButton.DIR_UP ? -SCROLL_STEP : SCROLL_STEP,
            behavior: event.detail.is_repeat ? 'auto' : 'smooth',
        })
    }

    return (
        <ModalRoot onCancel={onClose} bAllowFullSize>
            <ModalScrollContent autoFocus focusable noFocusRing onGamepadDirection={scrollLog}>
                <div ref={scrollRef}>
                    <p style={{fontSize: '14px', overflowWrap: 'anywhere', marginTop: 0}}>
                        {log?.path ?? path}
                    </p>
                    {error ? <p role="alert">Could not open log: {error}</p> : !log ? (
                        <p role="status">Loading log…</p>
                    ) : (
                        <>
                            {log.truncated && <p>Showing the latest 1 MiB of this log. Older content is omitted.</p>}
                            <pre style={{whiteSpace: 'pre-wrap', wordBreak: 'break-word', margin: 0}}>
                                {log.content || 'This log is empty.'}
                            </pre>
                        </>
                    )}
                </div>
            </ModalScrollContent>
        </ModalRoot>
    )
}

export function BrowseLogsButton() {
    const [isBrowsing, setIsBrowsing] = useState(false)
    const browseLogs = async () => {
        setIsBrowsing(true)
        try {
            const directory = await getLogsDirectory()
            const selected = await openFilePicker(
                FileSelectionType.FILE, directory, true, true, undefined, ['log'], true, false,
            )
            const modal = showModal(
                <LogFileModal path={selected.realpath || selected.path} onClose={() => modal.Close()}/>,
            )
        } catch (error) {
            // Decky's native picker rejects its promise when dismissed.
            if (errorMessage(error) !== 'User canceled') {
                toaster.toast({title: 'Could not browse logs', body: errorMessage(error)})
            }
        } finally {
            setIsBrowsing(false)
        }
    }

    return (
        <ButtonItem layout="below" disabled={isBrowsing} onClick={browseLogs}>
            {isBrowsing ? 'Opening logs…' : 'Browse logs'}
        </ButtonItem>
    )
}
