/**
 * Tasks Page - Feature-rich modal matching Vanilla JS
 */

import { useState, useMemo, useEffect } from 'react'
import { useTasks, useCreateTask, useUpdateTask, useDeleteTask, type Task } from '../api/tasks'
import { Icon } from '../components/Icon'
import { ModuleExportButton } from '../components/BackupActions'

type FilterType = 'all' | 'pending' | 'completed'
type ViewType = 'tasks' | 'analytics'
type Priority = 'low' | 'medium' | 'high'
type SortField = 'created_at' | 'updated_at' | 'completion_date'

const toIST = (dateStr?: string | null) => {
    if (!dateStr) return null
    return new Date(dateStr).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', dateStyle: 'medium', timeStyle: 'short' })
}

export function TasksPage() {
    const { data: tasks, isLoading, error } = useTasks()
    const createTask = useCreateTask()
    const updateTask = useUpdateTask()
    const deleteTask = useDeleteTask()

    const [filter, setFilter] = useState<FilterType>('pending')
    const [view, setView] = useState<ViewType>('tasks')
    const [showAddModal, setShowAddModal] = useState(false)
    const [editingTask, setEditingTask] = useState<Task | null>(null)
    const [selectedTask, setSelectedTask] = useState<Task | null>(null)
    const [search, setSearch] = useState('')
    const [priorityFilter, setPriorityFilter] = useState<Priority | ''>('')
    const [sortBy, setSortBy] = useState<SortField>('created_at')
    const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')

    const [form, setForm] = useState({
        title: '',
        description: '',
        priority: 'medium' as Priority
    })

    const resetForm = () => {
        setForm({ title: '', description: '', priority: 'medium' })
        setEditingTask(null)
    }

    const openAddModal = () => {
        resetForm()
        setShowAddModal(true)
    }

    const openEditModal = (task: Task) => {
        setForm({
            title: task.title,
            description: task.description || '',
            priority: (task.priority as Priority) || 'medium'
        })
        setEditingTask(task)
        setShowAddModal(true)
    }

    const openTaskDetails = (task: Task) => setSelectedTask(task)

    const closeDetailsModal = () => setSelectedTask(null)

    const closeModal = () => {
        setShowAddModal(false)
        resetForm()
    }

    useEffect(() => {
        if (!showAddModal && !selectedTask) return

        const handleEscape = (event: KeyboardEvent) => {
            if (event.key !== 'Escape') return
            if (showAddModal) {
                setShowAddModal(false)
                setForm({ title: '', description: '', priority: 'medium' })
                setEditingTask(null)
            } else {
                setSelectedTask(null)
            }
        }

        window.addEventListener('keydown', handleEscape)
        return () => window.removeEventListener('keydown', handleEscape)
    }, [showAddModal, selectedTask])

    const handleSubmit = () => {
        if (!form.title.trim()) return

        if (editingTask) {
            updateTask.mutate({ id: editingTask.id, data: form }, {
                onSuccess: closeModal
            })
        } else {
            createTask.mutate(form, {
                onSuccess: closeModal
            })
        }
    }

    const markComplete = (task: Task) => {
        updateTask.mutate({ id: task.id, data: { completed: !task.completed } })
    }

    const allTasks = tasks || []
    const pendingTasks = allTasks.filter(t => !t.completed)
    const completedTasks = allTasks.filter(t => t.completed)

    const filteredTasks = useMemo(() => {
        const source = tasks || []
        let list = filter === 'pending' ? source.filter(task => !task.completed)
            : filter === 'completed' ? source.filter(task => task.completed)
                : source
        if (priorityFilter) {
            list = list.filter(t => t.priority === priorityFilter)
        }
        const q = search.trim().toLowerCase()
        if (q) {
            list = list.filter(t => t.title.toLowerCase().includes(q) || (t.description || '').toLowerCase().includes(q))
        }
        list = [...list].sort((a, b) => {
            const aVal = a[sortBy] ? new Date(a[sortBy]!).getTime() : 0
            const bVal = b[sortBy] ? new Date(b[sortBy]!).getTime() : 0
            return sortOrder === 'desc' ? bVal - aVal : aVal - bVal
        })
        return list
    }, [tasks, filter, priorityFilter, search, sortBy, sortOrder])

    if (isLoading) return <div className="empty-state"><div className="empty-text">Loading...</div></div>
    if (error) return <div className="empty-state"><div className="empty-text">Error loading tasks</div></div>

    // Analytics calculations
    const completionRate = allTasks.length > 0 ? Math.round((completedTasks.length / allTasks.length) * 100) : 0
    return (
        <div className="page tasks">
            {/* Page header: title/count on the left, Stats toggle on the right */}
            <div className="page-tabs" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div>
                    <h2 style={{ margin: 0 }}>All Tasks</h2>
                    <div className="empty-text" style={{ marginTop: 2 }}>{allTasks.length} tasks in total</div>
                </div>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                    <ModuleExportButton module="tasks" />
                    <button className="tab-btn secondary" onClick={() => setView(v => v === 'tasks' ? 'analytics' : 'tasks')}>
                        <Icon name={view === 'tasks' ? 'stats' : 'tasks'} size={16} /> {view === 'tasks' ? 'Stats' : 'Tasks'}
                    </button>
                </div>
            </div>

            {view === 'tasks' ? (
                <div className="content-card">
                    {/* Filter tabs: Pending | Completed | All */}
                    <div className="filter-tabs">
                        <button className={`filter-btn ${filter === 'pending' ? 'active' : ''}`} onClick={() => setFilter('pending')}>
                            <Icon name="tasks" size={16} /> Pending <span className="filter-btn-count">{pendingTasks.length}</span>
                        </button>
                        <button className={`filter-btn ${filter === 'completed' ? 'active' : ''}`} onClick={() => setFilter('completed')}>
                            <Icon name="check" size={16} /> Completed <span className="filter-btn-count">{completedTasks.length}</span>
                        </button>
                        <button className={`filter-btn ${filter === 'all' ? 'active' : ''}`} onClick={() => setFilter('all')}>
                            <Icon name="list" size={16} /> All <span className="filter-btn-count">{allTasks.length}</span>
                        </button>
                    </div>

                    {/* Search + Priority filter + Sort controls + Add Task */}
                    <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between' }}>
                        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', flex: 1 }}>
                            <input
                                className="form-input"
                                placeholder="Search tasks..."
                                value={search}
                                onChange={e => setSearch(e.target.value)}
                                style={{ width: 'auto', minWidth: 200, flex: '1 1 200px' }}
                            />
                            <label className="task-select-wrap">
                                <span className="sr-only">Filter by priority</span>
                                <select className="form-input task-select" value={priorityFilter} onChange={e => setPriorityFilter(e.target.value as Priority | '')}>
                                    <option value="">All priorities</option>
                                    <option value="high">High priority</option>
                                    <option value="medium">Medium priority</option>
                                    <option value="low">Low priority</option>
                                </select>
                                <Icon name="down" size={16} />
                            </label>
                            <label className="task-select-wrap">
                                <span className="sr-only">Sort tasks by</span>
                                <select className="form-input task-select" value={sortBy} onChange={e => setSortBy(e.target.value as SortField)}>
                                    <option value="created_at">Created date</option>
                                    <option value="updated_at">Last updated</option>
                                    <option value="completion_date">Completion date</option>
                                </select>
                                <Icon name="down" size={16} />
                            </label>
                            <button className="btn btn-sm" onClick={() => setSortOrder(o => o === 'desc' ? 'asc' : 'desc')} style={{ padding: '6px 10px', fontSize: 14 }}>
                                <span className="icon-text">
                                    <Icon name={sortOrder === 'desc' ? 'sortDesc' : 'sortAsc'} size={14} />
                                    {sortOrder === 'desc' ? 'Newest' : 'Oldest'}
                                </span>
                            </button>
                        </div>
                        <button className="btn btn-primary toolbar-action" onClick={openAddModal}><Icon name="add" size={16} /> Add Task</button>
                    </div>

                    {filteredTasks.length === 0 ? (
                        <div className="empty-state">
                            <div className="empty-icon"><Icon name="tasks" size={48} /></div>
                            <div className="empty-title">No tasks yet</div>
                            <div className="empty-text">Add your first task to get started!</div>
                        </div>
                    ) : (
                        <ul className="item-list">
                            {filteredTasks.map(task => (
                                <li
                                    key={task.id}
                                    className={`item-row task-row ${task.completed ? 'completed' : ''}`}
                                    onClick={() => openTaskDetails(task)}
                                    onKeyDown={e => {
                                        if ((e.target as HTMLElement).closest('button')) return
                                        if (e.key === 'Enter' || e.key === ' ') {
                                            e.preventDefault()
                                            openTaskDetails(task)
                                        }
                                    }}
                                    role="button"
                                    tabIndex={0}
                                    aria-label={`View details for ${task.title}`}
                                >
                                    {/* Completion button */}
                                    <button
                                        onClick={e => { e.stopPropagation(); markComplete(task) }}
                                        title={task.completed ? 'Mark as pending' : 'Mark as complete'}
                                        style={{
                                            width: 32, height: 32, borderRadius: '50%', border: '2px solid',
                                            borderColor: task.completed ? '#22c55e' : 'var(--border)',
                                            background: task.completed ? '#22c55e' : 'transparent',
                                            color: task.completed ? '#fff' : 'var(--text-secondary)',
                                            cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
                                            fontSize: 16, marginRight: 12, flexShrink: 0, transition: 'all 0.2s'
                                        }}
                                    >
                                        {task.completed && <Icon name="check" size={16} />}
                                    </button>
                                    <div className="item-info" style={{ flex: 1 }}>
                                        <strong style={{ textDecoration: task.completed ? 'line-through' : 'none', opacity: task.completed ? 0.7 : 1 }}>{task.title}</strong>
                                        {task.description && <span className="item-meta task-description">{task.description}</span>}
                                        <span className="item-meta">
                                            Created: {toIST(task.created_at) || '—'}
                                            {task.completion_date && ` • Completed: ${toIST(task.completion_date)}`}
                                        </span>
                                    </div>
                                    <span className={`priority-badge ${task.priority} icon-text`}>
                                        <span className={`priority-dot ${task.priority}`} /> {task.priority}
                                    </span>
                                    <button className="item-action" onClick={() => openEditModal(task)} title="Edit" aria-label="Edit task"><Icon name="edit" size={16} /></button>
                                    <button onClick={e => { e.stopPropagation(); if (window.confirm(`Delete task "${task.title}"?`)) deleteTask.mutate(task.id) }} title="Delete" style={{ padding: '4px 8px', background: 'transparent', border: '1px solid var(--border)', borderRadius: 6, cursor: 'pointer', opacity: 0.6, fontSize: 13, marginLeft: 4, transition: 'opacity 0.2s' }} onMouseEnter={e => (e.currentTarget.style.opacity = '1')} onMouseLeave={e => (e.currentTarget.style.opacity = '0.6')} aria-label={`Delete ${task.title}`}><Icon name="delete" size={16} label={`Delete ${task.title}`} /></button>
                                </li>
                            ))}
                        </ul>
                    )}
                </div>
            ) : (
                <div className="content-card">
                    <div className="stats-heading">
                        <div>
                            <h3>Task overview</h3>
                            <p>See what needs your attention and how you’re progressing.</p>
                        </div>
                    </div>
                    <div className="stats-row" style={{ marginBottom: 24 }}>
                        <div className="stat-card"><div className="stat-value">{pendingTasks.length}</div><div className="stat-label">Needs attention</div><span className="stat-help">Open tasks</span></div>
                        <div className="stat-card"><div className="stat-value">{completedTasks.length}</div><div className="stat-label">Finished</div><span className="stat-help">Completed tasks</span></div>
                        <div className="stat-card"><div className="stat-value">{completionRate}%</div><div className="stat-label">Progress</div><span className="stat-help">Overall completion</span></div>
                    </div>
                    <div className="priority-overview">
                        <h4>Open tasks by priority</h4>
                        <div className="priority-overview-grid">
                            <div className="priority-overview-item"><span className="priority-dot high" /><span>High priority</span><strong>{allTasks.filter(t => !t.completed && t.priority === 'high').length}</strong></div>
                            <div className="priority-overview-item"><span className="priority-dot medium" /><span>Medium priority</span><strong>{allTasks.filter(t => !t.completed && t.priority === 'medium').length}</strong></div>
                            <div className="priority-overview-item"><span className="priority-dot low" /><span>Low priority</span><strong>{allTasks.filter(t => !t.completed && t.priority === 'low').length}</strong></div>
                        </div>
                    </div>

                    <h4>Recent Completions</h4>
                    {completedTasks.length === 0 ? (
                        <p style={{ color: 'var(--text-secondary)' }}>No completed tasks yet</p>
                    ) : (
                        <ul className="item-list">
                            {completedTasks.slice(0, 5).map(task => (
                                <li key={task.id} className="item-row">
                                    <div className="item-info">
                                        <strong className="icon-text"><Icon name="check" size={16} /> {task.title}</strong>
                                        <span className="item-meta">{task.completion_date ? `Completed: ${toIST(task.completion_date)}` : 'Completed'}</span>
                                    </div>
                                </li>
                            ))}
                        </ul>
                    )}
                </div>
            )}

            {/* Add/Edit Modal - Feature-rich matching Vanilla JS */}
            {showAddModal && (
                <div className="modal-overlay" onClick={closeModal}>
                    <div className="modal-content" onClick={e => e.stopPropagation()}>
                        <div className="modal-header">
                            <h3>{editingTask ? 'Edit Task' : 'Add New Task'}</h3>
                            <button className="modal-close" onClick={closeModal} aria-label="Close task form">
                                <Icon name="close" size={20} />
                            </button>
                        </div>

                        <label className="form-label">Title *</label>
                        <input
                            className="form-input"
                            placeholder="Task title"
                            value={form.title}
                            onChange={e => setForm({ ...form, title: e.target.value })}
                            autoFocus
                        />

                        <label className="form-label" style={{ marginTop: 12 }}>Description</label>
                        <textarea
                            className="form-input"
                            placeholder="Task description (optional)"
                            value={form.description}
                            onChange={e => setForm({ ...form, description: e.target.value })}
                            style={{ minHeight: 80 }}
                        />

                        <label className="form-label" style={{ marginTop: 12 }}>Priority</label>
                        <div className="priority-selector" style={{ display: 'flex', gap: 8 }}>
                            {(['low', 'medium', 'high'] as Priority[]).map(p => (
                                <label key={p} className={`priority-option ${form.priority === p ? 'selected' : ''}`} style={{
                                    flex: 1,
                                    padding: '8px 12px',
                                    border: `2px solid ${form.priority === p ? 'var(--primary)' : 'var(--border)'}`,
                                    borderRadius: 8,
                                    textAlign: 'center',
                                    cursor: 'pointer',
                                    background: form.priority === p ? 'rgba(102, 126, 234, 0.1)' : 'white'
                                }}>
                                    <input
                                        type="radio"
                                        name="priority"
                                        value={p}
                                        checked={form.priority === p}
                                        onChange={() => setForm({ ...form, priority: p })}
                                        style={{ display: 'none' }}
                                    />
                                    <span className="icon-text" style={{ justifyContent: 'center' }}>
                                        <span className={`priority-dot ${p}`} /> {p.charAt(0).toUpperCase() + p.slice(1)}
                                    </span>
                                </label>
                            ))}
                        </div>

                        <div className="modal-actions">
                            <button className="btn btn-primary" onClick={handleSubmit} disabled={createTask.isPending || updateTask.isPending}>
                                {(createTask.isPending || updateTask.isPending) ? 'Saving...' : (editingTask ? 'Update Task' : 'Add Task')}
                            </button>
                            <button className="btn" onClick={closeModal}>Cancel</button>
                        </div>
                    </div>
                </div>
            )}

            {selectedTask && (
                <div className="modal-overlay" onClick={closeDetailsModal}>
                    <div className="modal-content task-detail-modal" onClick={e => e.stopPropagation()}>
                        <div className="modal-header">
                            <h3>{selectedTask.title}</h3>
                            <button className="modal-close" onClick={closeDetailsModal} aria-label="Close task details">
                                <Icon name="close" size={20} />
                            </button>
                        </div>
                        <div className="modal-body task-detail-body">
                            <div className="task-detail-status">
                                <span className={`priority-badge ${selectedTask.priority} icon-text`}>
                                    <span className={`priority-dot ${selectedTask.priority}`} /> {selectedTask.priority}
                                </span>
                                <span className={selectedTask.completed ? 'task-status completed' : 'task-status'}>
                                    {selectedTask.completed ? 'Completed' : 'Pending'}
                                </span>
                            </div>
                            <div className="task-detail-field">
                                <span className="form-label">Description</span>
                                <p>{selectedTask.description || 'No description provided.'}</p>
                            </div>
                            <div className="task-detail-field">
                                <span className="form-label">Created</span>
                                <p>{toIST(selectedTask.created_at) || '—'}</p>
                            </div>
                            {selectedTask.due_date && <div className="task-detail-field">
                                <span className="form-label">Due date</span>
                                <p>{selectedTask.due_date}</p>
                            </div>}
                            {selectedTask.completion_date && <div className="task-detail-field">
                                <span className="form-label">Completed</span>
                                <p>{toIST(selectedTask.completion_date)}</p>
                            </div>}
                        </div>
                        <div className="modal-footer">
                            <button className="btn btn-primary" onClick={() => { closeDetailsModal(); openEditModal(selectedTask) }}>
                                <Icon name="edit" size={16} /> Edit Task
                            </button>
                            <button className="btn" onClick={closeDetailsModal}>Close</button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}
