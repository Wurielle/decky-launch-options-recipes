import {callable, FileSelectionType, openFilePicker, toaster} from '@decky/api'
import {
    ButtonItem,
    DialogBody,
    DialogButton,
    DialogHeader,
    Focusable,
    GamepadButton,
    ModalRoot,
    showModal,
} from '@decky/ui'
import type {GamepadEvent} from '@decky/ui'
import {useEffect, useRef, useState} from 'react'

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
        const element = scrollRef.current
        if (!element) return
        const direction = event.detail.button === GamepadButton.DIR_UP ? -1
            : event.detail.button === GamepadButton.DIR_DOWN ? 1 : 0
        if (!direction || (direction < 0 && element.scrollTop <= 0)
            || (direction > 0 && element.scrollTop + element.clientHeight >= element.scrollHeight)) return
        event.preventDefault()
        element.scrollBy({top: direction * 120, behavior: event.detail.is_repeat ? 'auto' : 'smooth'})
    }

    return (
        <ModalRoot onCancel={onClose} bAllowFullSize>
            <DialogHeader>Log file</DialogHeader>
            <DialogBody>
                <p style={{fontSize: '14px', overflowWrap: 'anywhere', marginTop: 0}}>
                    {log?.path ?? path}
                </p>
                {error ? <p role="alert">Could not open log: {error}</p> : !log ? (
                    <p role="status">Loading log…</p>
                ) : (
                    <>
                        {log.truncated && <p>Showing the latest 1 MiB of this log. Older content is omitted.</p>}
                        <Focusable
                            ref={scrollRef}
                            tabIndex={0}
                            onGamepadDirection={scrollLog}
                            aria-label="Log contents"
                            style={{maxHeight: '50vh', overflowY: 'auto', padding: '8px'}}
                        >
                            <pre style={{whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', fontSize: '13px', margin: 0}}>
                                {log.content || 'This log is empty.'}
                            </pre>
                        </Focusable>
                    </>
                )}
                <DialogButton style={{marginTop: '12px'}} onClick={onClose}>Close</DialogButton>
            </DialogBody>
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
