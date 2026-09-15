interface QueryErrorStateProps {
    message: string
    error: unknown
}

export function QueryErrorState({ message, error }: QueryErrorStateProps) {
    const detail = error instanceof Error ? error.message : 'The server returned an unexpected error.'
    return (
        <div className="empty-state" role="alert">
            <div className="empty-text">{message}</div>
            <div className="item-meta">{detail}</div>
        </div>
    )
}
