import { useEffect } from 'react'

export function useEscapeKey(active: boolean, onEscape: () => void) {
    useEffect(() => {
        if (!active) return
        const handleKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') onEscape()
        }
        window.addEventListener('keydown', handleKeyDown)
        return () => window.removeEventListener('keydown', handleKeyDown)
    }, [active, onEscape])
}