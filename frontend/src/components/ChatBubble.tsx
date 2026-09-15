/**
 * AI Chat Bubble Component
 * Floating assistant for the Omniflow assistant workflow.
 */

import { useState, useRef, useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import './ChatBubble.css'
import { Icon } from './Icon'
import { api, authHeaders, formatApiError } from '../api/client'

interface Message {
    id: number
    role: 'user' | 'assistant'
    content: string
    timestamp: Date
    proposal?: AIProposal
}

interface ProposalAction {
    action_index: number
    action: string
    arguments: Record<string, unknown>
}

interface AIProposal {
    request_id: string
    status: 'pending' | 'committed' | 'rejected'
    proposed_at?: string
    decided_at?: string
    actions: ProposalAction[]
    review?: { version: number; context_targets?: Array<{ table: string; id: number; name: string }>; actions: Array<{ action_index: number; action: string; arguments: Record<string, unknown>; targets: Array<{ table: string; id: number; name: string }>; depends_on_actions: number[] }> }
    review_digest?: string
}

interface StreamEvent {
    type: 'status' | 'delta' | 'result' | 'done' | 'error'
    message?: string
    content?: string
    error?: string
    data?: {
        success?: boolean
        message?: string
        response?: string
        error?: string
        pending_approval?: boolean
        proposal?: AIProposal
    }
}

const formatProposalValue = (value: unknown) => {
    if (typeof value === 'string') return value
    if (value === null) return 'None'
    return JSON.stringify(value)
}

const formatErrorDetail = (detail: unknown, fallback = 'Proposal decision failed') => {
    if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
        const record = detail as Record<string, unknown>
        if (Array.isArray(record.errors)) return formatApiError(record, fallback)
    }
    return formatApiError(detail, fallback)
}

export function ChatBubble() {
    const [isOpen, setIsOpen] = useState(false)
    const [messages, setMessages] = useState<Message[]>([
        { id: 1, role: 'assistant', content: 'Hi! How can I help you today?', timestamp: new Date() }
    ])
    const [input, setInput] = useState('')
    const [isTyping, setIsTyping] = useState(false)
    const [aiStatus, setAiStatus] = useState('Thinking locally…')
    const [decidingProposal, setDecidingProposal] = useState<string | null>(null)
    const queryClient = useQueryClient()
    const messagesEndRef = useRef<HTMLDivElement>(null)
    const inputRef = useRef<HTMLInputElement>(null)

    useEffect(() => {
        if (!isOpen) return
        let cancelled = false
        void api.get<AIProposal[]>('/ai/proposals?status=pending').then(proposals => {
            if (cancelled || proposals.length === 0) return
            setMessages(previous => {
                const known = new Set(previous.map(message => message.proposal?.request_id).filter(Boolean))
                const recovered = proposals.filter(proposal => !known.has(proposal.request_id)).map((proposal, index) => ({
                    id: Date.now() + index,
                    role: 'assistant' as const,
                    content: 'Recovered pending proposal. Review it before approving.',
                    timestamp: new Date(proposal.proposed_at || Date.now()),
                    proposal,
                }))
                return recovered.length ? [...previous, ...recovered] : previous
            })
        }).catch(() => undefined)
        return () => { cancelled = true }
    }, [isOpen])

    // Auto-scroll to bottom on new messages
    useEffect(() => {
        if (isOpen) {
            messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
        }
    }, [messages, isOpen])

    // Focus input when opened
    useEffect(() => {
        if (isOpen) {
            inputRef.current?.focus()
        }
    }, [isOpen])

    // Handle keyboard
    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === 'Escape') {
            setIsOpen(false)
        }
    }

    const toggleChat = () => {
        setIsOpen(!isOpen)
    }

    const handleSend = async () => {
        if (!input.trim() || isTyping) return

        const prompt = input.trim()
        const history = messages
            .filter(message => message.content.trim().length > 0)
            .slice(-5)
            .map(({ role, content }) => ({ role, content }))

        const userMessage: Message = {
            id: Date.now(),
            role: 'user',
            content: prompt,
            timestamp: new Date()
        }

        setMessages(prev => [...prev, userMessage])
        setInput('')
        setIsTyping(true)
        setAiStatus('Connecting to local AI…')

        try {
            const response = await fetch('/api/ai/agent/chat/stream', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...authHeaders(),
                },
                body: JSON.stringify({ message: prompt, history })
            })

            if (!response.ok) {
                throw new Error('AI request failed')
            }

            if (!response.body) {
                throw new Error('AI response stream is unavailable')
            }

            const assistantId = userMessage.id + 1
            const reader = response.body.getReader()
            const decoder = new TextDecoder()
            let buffer = ''
            let assistantCreated = false

            const addAssistant = (content: string, proposal?: AIProposal) => {
                assistantCreated = true
                setMessages(previous => [...previous, {
                    id: assistantId,
                    role: 'assistant',
                    content,
                    timestamp: new Date(),
                    proposal,
                }])
            }

            const handleEvent = (event: StreamEvent) => {
                if (event.type === 'status' && event.message) {
                    setAiStatus(event.message)
                    return
                }
                if (event.type === 'delta' && event.content) {
                    if (!assistantCreated) {
                        addAssistant(event.content)
                    } else {
                        setMessages(previous => previous.map(message => message.id === assistantId
                            ? { ...message, content: message.content + event.content }
                            : message))
                    }
                    return
                }
                if (event.type === 'result' && event.data) {
                    const content = event.data.error
                        ? `Sorry, there was an issue: ${event.data.error}`
                        : event.data.message || event.data.response || 'Done!'
                    addAssistant(
                        content,
                        event.data.pending_approval && event.data.proposal
                            ? event.data.proposal
                            : undefined,
                    )
                    return
                }
                if (event.type === 'error') {
                    const detail = event.error || 'The local AI response was interrupted.'
                    if (assistantCreated) {
                        setMessages(previous => previous.map(message => message.id === assistantId
                            ? { ...message, content: `${message.content}\n\n${detail}` }
                            : message))
                    } else {
                        addAssistant(`Sorry, there was an issue: ${detail}`)
                    }
                }
            }

            while (true) {
                const { value, done } = await reader.read()
                buffer += decoder.decode(value, { stream: !done })
                const lines = buffer.split('\n')
                buffer = lines.pop() || ''
                for (const line of lines) {
                    if (line.trim()) handleEvent(JSON.parse(line) as StreamEvent)
                }
                if (done) break
            }
            if (buffer.trim()) handleEvent(JSON.parse(buffer) as StreamEvent)
            if (!assistantCreated) throw new Error('AI response ended without an answer')
        } catch (error) {
            console.error('AI chat error:', error)
            const errorMessage: Message = {
                id: Date.now() + 1,
                role: 'assistant',
                content: "Sorry, I'm having trouble connecting. Please try again later.",
                timestamp: new Date()
            }
            setMessages(prev => [...prev, errorMessage])
        } finally {
            setIsTyping(false)
        }
    }

    const decideProposal = async (messageId: number, proposal: AIProposal, decision: 'approve' | 'reject') => {
        setDecidingProposal(proposal.request_id)
        try {
            const response = await fetch(`/api/ai/proposals/${proposal.request_id}/${decision}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...authHeaders(),
                    ...(decision === 'approve' && proposal.review_digest ? { 'X-Omniflow-Review-Digest': proposal.review_digest } : {}),
                },
            })
            const payload = await response.json().catch(() => ({}))
            if (!response.ok) {
                if (response.status === 409) {
                    const current = await api.get<AIProposal>(`/ai/proposals/${proposal.request_id}`)
                    setMessages(previous => previous.map(message => message.id === messageId
                        ? {
                            ...message,
                            content: current.status === 'committed'
                                ? 'Those changes were already applied.'
                                : current.status === 'rejected'
                                    ? 'That proposal was already rejected.'
                                    : message.content,
                            proposal: current,
                        }
                        : message))
                    return
                }
                throw new Error(formatErrorDetail(payload.detail || payload.error, `HTTP ${response.status}`))
            }
            const status = decision === 'approve' ? 'committed' : 'rejected'
            setMessages(previous => previous.map(message => message.id === messageId
                ? {
                    ...message,
                    content: decision === 'approve'
                        ? payload.message || 'Approved changes were applied.'
                        : 'Proposal rejected. No data was changed.',
                    proposal: { ...proposal, status },
                }
                : message))
            if (decision === 'approve') await queryClient.invalidateQueries()
        } catch (error) {
            const detail = error instanceof Error ? error.message : 'Proposal decision failed'
            setMessages(previous => [...previous, {
                id: Date.now(),
                role: 'assistant',
                content: `I could not ${decision} that proposal: ${detail}`,
                timestamp: new Date(),
            }])
        } finally {
            setDecidingProposal(null)
        }
    }

    const formatTime = (date: Date) => {
        return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    }

    return (
        <div className="chat-bubble-container" onKeyDown={handleKeyDown}>
            {/* Chat Panel */}
            {isOpen && (
                <div
                    className="chat-panel"
                    role="dialog"
                    aria-label="AI Assistant"
                    aria-modal="true"
                >
                    <div className="chat-header">
                        <div>
                            <span className="icon-text"><Icon name="bot" size={18} /> AI Assistant</span>
                            <span className="chat-model">Local · Ollama</span>
                        </div>
                        <button
                            className="chat-close"
                            onClick={() => setIsOpen(false)}
                            aria-label="Close chat"
                        >
                            <Icon name="close" size={18} />
                        </button>
                    </div>

                    <div className="chat-messages" role="log" aria-live="polite">
                        {messages.map(msg => (
                            <div key={msg.id} className={`chat-message ${msg.role}`}>
                                <div className="message-content">{msg.content}</div>
                                {msg.proposal && (
                                    <div className={`proposal-card ${msg.proposal.status}`}>
                                        <div className="proposal-heading">
                                            <div className="proposal-title">
                                                {msg.proposal.actions.length === 1 ? 'Proposed change' : `${msg.proposal.actions.length} proposed changes`}
                                            </div>
                                            <span className="proposal-status">
                                                {msg.proposal.status === 'pending' ? 'Approval required' : msg.proposal.status}
                                            </span>
                                        </div>
                                        <p className="proposal-help">
                                            {msg.proposal.status === 'pending'
                                                ? 'Nothing changes until you approve.'
                                                : msg.proposal.status === 'rejected'
                                                    ? 'No domain data was changed.'
                                                    : 'Changes were applied and added to the audit trail.'}
                                        </p>
                                        {msg.proposal.review?.context_targets?.map(target => (
                                            <div key={`${target.table}-${target.id}`} className="proposal-target">Context target: {target.table} #{target.id} — {target.name}</div>
                                        ))}
                                        <ol className="proposal-actions">
                                            {msg.proposal.actions.map(action => (
                                                <li key={action.action_index}>
                                                    <strong className="proposal-action-name">{action.action.replaceAll('.', ' ')}</strong>
                                                    {msg.proposal?.review?.actions[action.action_index]?.targets.map(target => <div key={`${target.table}-${target.id}`} className="proposal-target">Target: {target.table} #{target.id} — {target.name}</div>)}
                                                    {msg.proposal?.review?.actions[action.action_index]?.depends_on_actions.map(dependency => <div key={dependency} className="proposal-target">Depends on action {dependency + 1}</div>)}
                                                    <dl className="proposal-arguments">
                                                        {Object.entries(action.arguments).map(([name, value]) => (
                                                            <div key={name}>
                                                                <dt>{name.replaceAll('_', ' ')}</dt>
                                                                <dd>{formatProposalValue(value)}</dd>
                                                            </div>
                                                        ))}
                                                    </dl>
                                                </li>
                                            ))}
                                        </ol>
                                        {msg.proposal.status === 'pending' && (
                                            <div className="proposal-buttons">
                                                <button
                                                    type="button"
                                                    className="proposal-reject"
                                                    disabled={decidingProposal === msg.proposal.request_id}
                                                    onClick={() => decideProposal(msg.id, msg.proposal!, 'reject')}
                                                >Reject</button>
                                                <button
                                                    type="button"
                                                    className="proposal-approve"
                                                    disabled={decidingProposal === msg.proposal.request_id}
                                                    onClick={() => decideProposal(msg.id, msg.proposal!, 'approve')}
                                                >Approve changes</button>
                                            </div>
                                        )}
                                    </div>
                                )}
                                <div className="message-time">{formatTime(msg.timestamp)}</div>
                            </div>
                        ))}
                        {isTyping && (
                            <div className="chat-message assistant typing">
                                <div className="typing-indicator">
                                    <span></span><span></span><span></span>
                                </div>
                                <span className="typing-status">{aiStatus}</span>
                            </div>
                        )}
                        <div ref={messagesEndRef} />
                    </div>

                    <div className="chat-input-area">
                        <input
                            ref={inputRef}
                            type="text"
                            value={input}
                            onChange={(e) => setInput(e.target.value)}
                            onKeyDown={(e) => e.key === 'Enter' && handleSend()}
                            placeholder="Ask your local assistant…"
                            aria-label="Chat message input"
                            disabled={isTyping}
                        />
                        <button
                            onClick={handleSend}
                            disabled={!input.trim() || isTyping}
                            aria-label="Send message"
                        >
                            <Icon name="send" size={18} />
                        </button>
                    </div>
                </div>
            )}

            {/* Floating Bubble */}
            <button
                className={`chat-bubble ${isOpen ? 'open' : ''}`}
                onClick={toggleChat}
                aria-label={isOpen ? 'Close AI chat' : 'Open AI chat'}
                aria-expanded={isOpen}
            >
                <Icon name={isOpen ? 'close' : 'bot'} size={24} />
            </button>
        </div>
    )
}
