/**
 * Gym Page - Templates, Logged Workouts, and Exercise Library
 */

import { useMemo, useState } from 'react'
import {
    useExercises,
    useCreateExercise,
    useUpdateExercise,
    useDeleteExercise,
    useTrainingSets,
    useCreateTrainingSet,
    useUpdateTrainingSet,
    useDeleteTrainingSet,
    useTrainingHistory,
    useLogWorkout,
    useDeleteTrainingHistory,
    type Exercise,
    type TrainingSet,
    type TrainingHistory,
} from '../api/gym'
import { Icon } from '../components/Icon'
import { ModuleExportButton } from '../components/BackupActions'
import { QueryErrorState } from '../components/QueryErrorState'
import { useEscapeKey } from '../utils/useEscapeKey'

type GymTab = 'workouts' | 'exercises'

interface SessionExercise {
    exercise_id: number
    sets_completed: number | ''
    reps_completed: number | ''
}

const today = () => {
    const now = new Date()
    const year = now.getFullYear()
    const month = String(now.getMonth() + 1).padStart(2, '0')
    const day = String(now.getDate()).padStart(2, '0')
    return `${year}-${month}-${day}`
}

export function GymPage() {
    const [tabOverride, setTabOverride] = useState<GymTab | null>(null)
    const [showHistory, setShowHistory] = useState(false)
    const [search, setSearch] = useState('')

    const [showAddExercise, setShowAddExercise] = useState(false)
    const [showAddTemplate, setShowAddTemplate] = useState(false)
    const [showLogWorkout, setShowLogWorkout] = useState(false)
    const [editingExerciseId, setEditingExerciseId] = useState<number | null>(null)
    const [editingTemplateId, setEditingTemplateId] = useState<number | null>(null)

    const [exerciseForm, setExerciseForm] = useState({ name: '', muscle_group: '', equipment: '', description: '' })
    const [templateForm, setTemplateForm] = useState<{ name: string; description: string; exercise_ids: number[] }>({ name: '', description: '', exercise_ids: [] })
    const [logForm, setLogForm] = useState<{
        name: string
        session_date: string
        duration_minutes: string
        notes: string
        training_set_id: number | ''
        exercises: SessionExercise[]
    }>({ name: '', session_date: today(), duration_minutes: '', notes: '', training_set_id: '', exercises: [] })

    const { data: exercises = [], isLoading: loadingExercises, error: exercisesError } = useExercises()
    const { data: templates = [] } = useTrainingSets()
    const { data: history = [], isLoading: loadingHistory } = useTrainingHistory()

    const tab: GymTab = tabOverride ?? (!loadingExercises && exercises.length === 0 ? 'exercises' : 'workouts')

    const createExercise = useCreateExercise()
    const updateExercise = useUpdateExercise()
    const deleteExercise = useDeleteExercise()
    const createTemplate = useCreateTrainingSet()
    const updateTemplate = useUpdateTrainingSet()
    const deleteTemplate = useDeleteTrainingSet()
    const logWorkout = useLogWorkout()
    const deleteHistory = useDeleteTrainingHistory()

    const selectTab = (next: GymTab) => {
        setTabOverride(next)
        setShowHistory(false)
        setSearch('')
    }

    const confirmDelete = (label: string, fn: () => void) => {
        if (window.confirm(`Delete "${label}"?`)) fn()
    }

    const handleAddExercise = () => {
        if (!exerciseForm.name.trim() || !exerciseForm.muscle_group.trim()) return
        const body = {
            name: exerciseForm.name,
            muscle_group: exerciseForm.muscle_group,
            equipment: exerciseForm.equipment || undefined,
            description: exerciseForm.description || undefined,
        }
        const onSuccess = () => {
            setExerciseForm({ name: '', muscle_group: '', equipment: '', description: '' })
            setEditingExerciseId(null)
            setShowAddExercise(false)
        }
        if (editingExerciseId) {
            updateExercise.mutate({ id: editingExerciseId, ...body }, { onSuccess })
            return
        }
        createExercise.mutate(body, {
            onSuccess,
        })
    }

    const openEditExercise = (exercise: Exercise) => {
        setExerciseForm({
            name: exercise.name,
            muscle_group: exercise.muscle_group,
            equipment: exercise.equipment || '',
            description: exercise.description || '',
        })
        setEditingExerciseId(exercise.id)
        setShowAddExercise(true)
    }

    const closeExerciseModal = () => {
        setExerciseForm({ name: '', muscle_group: '', equipment: '', description: '' })
        setEditingExerciseId(null)
        setShowAddExercise(false)
    }

    const handleSaveTemplate = () => {
        if (!templateForm.name.trim() || templateForm.exercise_ids.length === 0) return
        const body = { name: templateForm.name, description: templateForm.description || undefined, exercises: templateForm.exercise_ids.map(id => ({ exercise_id: id })) }
        const onSuccess = () => { setTemplateForm({ name: '', description: '', exercise_ids: [] }); setEditingTemplateId(null); setShowAddTemplate(false) }
        if (editingTemplateId) updateTemplate.mutate({ id: editingTemplateId, ...body }, { onSuccess })
        else createTemplate.mutate(body, { onSuccess })
    }

    const openEditTemplate = (template: TrainingSet) => {
        setTemplateForm({ name: template.name, description: template.description || '', exercise_ids: template.exercises.map(exercise => exercise.exercise_id) })
        setEditingTemplateId(template.id)
        setShowAddTemplate(true)
    }

    const closeTemplateModal = () => { setTemplateForm({ name: '', description: '', exercise_ids: [] }); setEditingTemplateId(null); setShowAddTemplate(false) }
    useEscapeKey(showAddExercise, closeExerciseModal)
    useEscapeKey(showAddTemplate, closeTemplateModal)
    useEscapeKey(showLogWorkout, () => setShowLogWorkout(false))
    const openLogWorkout = (templateId?: number) => {
        const tpl = templateId ? templates.find(t => t.id === templateId) : null
        setLogForm({
            name: tpl?.name ?? '',
            session_date: today(),
            duration_minutes: '',
            notes: '',
            training_set_id: templateId ?? '',
            exercises: tpl
                ? tpl.exercises.map(e => ({
                    exercise_id: e.exercise_id,
                    sets_completed: '',
                    reps_completed: '',
                }))
                : [],
        })
        setShowLogWorkout(true)
    }

    const addExerciseToLog = (exerciseId: number) => {
        if (!exerciseId) return
        if (logForm.exercises.some(e => e.exercise_id === exerciseId)) return
        setLogForm({
            ...logForm,
            exercises: [...logForm.exercises, { exercise_id: exerciseId, sets_completed: '', reps_completed: '' }],
        })
    }

    const updateLoggedExercise = (idx: number, patch: Partial<SessionExercise>) => {
        setLogForm({
            ...logForm,
            exercises: logForm.exercises.map((e, i) => (i === idx ? { ...e, ...patch } : e)),
        })
    }

    const removeLoggedExercise = (idx: number) => {
        setLogForm({ ...logForm, exercises: logForm.exercises.filter((_, i) => i !== idx) })
    }

    const handleLogWorkout = () => {
        if (logForm.exercises.length === 0) return
        const workoutExercises = []
        for (const exercise of logForm.exercises) {
            workoutExercises.push({
                exercise_id: exercise.exercise_id,
                sets_completed: exercise.sets_completed === '' ? undefined : Number(exercise.sets_completed),
                reps_completed: exercise.reps_completed === '' ? undefined : Number(exercise.reps_completed),
            })
        }
        logWorkout.mutate(
            {
                training_set_id: logForm.training_set_id || undefined,
                name: logForm.name || undefined,
                session_date: logForm.session_date,
                duration_minutes: logForm.duration_minutes ? Number(logForm.duration_minutes) : undefined,
                notes: logForm.notes || undefined,
                exercises: workoutExercises,
            },
            { onSuccess: () => setShowLogWorkout(false) }
        )
    }

    const exerciseName = (id: number) => exercises.find(e => e.id === id)?.name ?? `#${id}`

    const filteredTemplates = useMemo(() => {
        const q = search.trim().toLowerCase()
        if (!q) return templates
        return templates.filter((t: TrainingSet) => t.name.toLowerCase().includes(q) || (t.description || '').toLowerCase().includes(q))
    }, [templates, search])

    const filteredExercises = useMemo(() => {
        const q = search.trim().toLowerCase()
        if (!q) return exercises
        return exercises.filter((ex: Exercise) => ex.name.toLowerCase().includes(q) || ex.muscle_group.toLowerCase().includes(q))
    }, [exercises, search])

    if (exercisesError) return <QueryErrorState message="Could not load exercises." error={exercisesError} />

    return (
        <div className="page">
            {/* Page header: title/count on the left, History toggle on the right */}
            <div className="page-tabs" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div>
                    <h2 style={{ margin: 0 }}>Gym</h2>
                    <div className="empty-text" style={{ marginTop: 2 }}>{templates.length} templates · {exercises.length} exercises</div>
                </div>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                    <ModuleExportButton module="gym" />
                    <button className="tab-btn secondary" onClick={() => setShowHistory(v => !v)}>
                        <Icon name={showHistory ? 'list' : 'stats'} size={16} /> {showHistory ? 'Back' : 'History'}
                    </button>
                </div>
            </div>

            <div className="content-card">
                {/* Tabs: Workouts | Exercises */}
                <div className="filter-tabs">
                    <button className={`filter-btn ${!showHistory && tab === 'workouts' ? 'active' : ''}`} onClick={() => selectTab('workouts')}>
                        <Icon name="gym" size={16} /> Workouts <span className="filter-btn-count">{templates.length}</span>
                    </button>
                    <button className={`filter-btn ${!showHistory && tab === 'exercises' ? 'active' : ''}`} onClick={() => selectTab('exercises')}>
                        <Icon name="gym" size={16} /> Exercises <span className="filter-btn-count">{exercises.length}</span>
                    </button>
                </div>

                {!showHistory && (
                    <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between' }}>
                        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', flex: 1 }}>
                            <input
                                className="form-input"
                                placeholder={tab === 'exercises' ? 'Search exercises...' : 'Search templates...'}
                                value={search}
                                onChange={e => setSearch(e.target.value)}
                                style={{ width: 'auto', minWidth: 200, flex: '1 1 200px' }}
                            />
                        </div>
                        {tab === 'exercises' ? (
                            <button className="btn btn-primary toolbar-action" onClick={() => setShowAddExercise(true)}><Icon name="add" size={16} /> Add Exercise</button>
                        ) : (
                            <button className="tab-btn secondary toolbar-action" onClick={() => setShowAddTemplate(true)} disabled={exercises.length === 0}>
                                <Icon name="add" size={16} /> New Template
                            </button>
                        )}
                    </div>
                )}

                <h3>{showHistory ? 'Workout History' : tab === 'exercises' ? 'Exercise Library' : 'Templates'}</h3>

                {!showHistory && tab === 'workouts' && (
                    <>
                        {filteredTemplates.length === 0 ? (
                            <div className="empty-state">
                                <div className="empty-icon"><Icon name="gym" size={48} /></div>
                                <div className="empty-title">No templates found</div>
                                <div className="empty-text">
                                    {exercises.length === 0
                                        ? 'Add an exercise first, then create a template or log a workout.'
                                        : 'Create a template, then log workouts from its row.'}
                                </div>
                            </div>
                        ) : (
                            <ul className="item-list">
                            {filteredTemplates.map((t: TrainingSet) => (
                                <li key={t.id} className="item-row">
                                    <button className="btn btn-primary" onClick={() => openLogWorkout(t.id)}>
                                        Log Workout
                                    </button>
                                        <div className="item-info">
                                            <strong>{t.name}</strong>
                                            <span className="item-meta">
                                                Exercises: {t.exercises.map(e => e.exercise_name).join(", ") || "none"}
                                                {t.description && ` • Notes: ${t.description}`}
                                            </span>
                                        </div>
                                        <button className="item-action" onClick={() => openEditTemplate(t)} aria-label={`Edit template ${t.name}`}><Icon name="edit" size={16} /></button>
                                        <button className="delete-btn" onClick={() => confirmDelete(t.name, () => deleteTemplate.mutate(t.id))} aria-label={`Delete template ${t.name}`}><Icon name="delete" size={16} label={`Delete template ${t.name}`} /></button>
                                    </li>
                                ))}
                            </ul>
                        )}
                    </>
                )}

                {!showHistory && tab === 'exercises' && (
                    loadingExercises ? <div className="empty-state"><div className="empty-text">Loading...</div></div> :
                        filteredExercises.length === 0 ? (
                            <div className="empty-state">
                                <div className="empty-icon"><Icon name="gym" size={48} /></div>
                                <div className="empty-title">No exercises found</div>
                                <div className="empty-text">
                                    {exercises.length === 0
                                        ? 'Add exercises to your library — you need at least one to build workout plans.'
                                        : 'Add exercises to your library'}
                                </div>
                            </div>
                        ) : (
                            <ul className="item-list">
                                {filteredExercises.map((ex: Exercise) => (
                                    <li key={ex.id} className="item-row">
                                        <div className="item-info">
                                            <strong>{ex.name}</strong>
                                            <span className="item-meta">
                                                Muscle group: {ex.muscle_group}
                                                {ex.equipment && ` • Equipment: ${ex.equipment}`}
                                                {ex.description && ` • Notes: ${ex.description}`}
                                            </span>
                                        </div>
                                        <button className="item-action" onClick={() => openEditExercise(ex)} aria-label={`Edit exercise ${ex.name}`}><Icon name="edit" size={16} /></button>
                                        <button className="delete-btn" onClick={() => confirmDelete(ex.name, () => deleteExercise.mutate(ex.id))} aria-label={`Delete exercise ${ex.name}`}><Icon name="delete" size={16} label={`Delete exercise ${ex.name}`} /></button>
                                    </li>
                                ))}
                            </ul>
                        )
                )}

                {showHistory && (
                    loadingHistory ? <div className="empty-state"><div className="empty-text">Loading...</div></div> :
                        history.length === 0 ? (
                            <div className="empty-state">
                                <div className="empty-icon"><Icon name="stats" size={48} /></div>
                                <div className="empty-title">No workouts logged</div>
                                <div className="empty-text">Log a workout to see history.</div>
                            </div>
                        ) : (
                            <ul className="item-list">
                                {history.map((h: TrainingHistory) => (
                                    <li key={h.id} className="item-row">
                                        <div className="item-info">
                                            <strong>{h.set_name || 'Workout'}</strong>
                                            <span className="item-meta">
                                                {new Date(h.session_date).toLocaleDateString()}
                                                {h.duration_minutes && ` • ${h.duration_minutes} min`}
                                                {` • ${h.exercises.length} exercises`}
                                                {h.notes && ` • Notes: ${h.notes}`}
                                            </span>
                                        </div>
                                        <button className="delete-btn" onClick={() => confirmDelete(h.set_name || 'Workout', () => deleteHistory.mutate(h.id))} aria-label={`Delete workout ${h.set_name || 'Workout'}`}><Icon name="delete" size={16} label={`Delete workout ${h.set_name || 'Workout'}`} /></button>
                                    </li>
                                ))}
                            </ul>
                        )
                )}
            </div>

            {/* Add Exercise Modal */}
            {showAddExercise && (
                <div className="modal-overlay" onClick={closeExerciseModal}>
                    <div className="modal-content" onClick={e => e.stopPropagation()}>
                        <h3>{editingExerciseId ? 'Edit Exercise' : 'Add Exercise'}</h3>
                        <input className="form-input" placeholder="Exercise name" value={exerciseForm.name} onChange={e => setExerciseForm({ ...exerciseForm, name: e.target.value })} autoFocus />
                        <input className="form-input" placeholder="Muscle group (e.g. Chest, Back)" value={exerciseForm.muscle_group} onChange={e => setExerciseForm({ ...exerciseForm, muscle_group: e.target.value })} style={{ marginTop: 8 }} />
                        <input className="form-input" placeholder="Equipment (optional)" value={exerciseForm.equipment} onChange={e => setExerciseForm({ ...exerciseForm, equipment: e.target.value })} style={{ marginTop: 8 }} />
                        <textarea className="form-input" placeholder="Description (optional)" value={exerciseForm.description} onChange={e => setExerciseForm({ ...exerciseForm, description: e.target.value })} style={{ marginTop: 8, minHeight: 70 }} />
                        <div className="modal-actions">
                            <button className="btn btn-primary" onClick={handleAddExercise} disabled={createExercise.isPending || updateExercise.isPending}>
                                {createExercise.isPending || updateExercise.isPending ? 'Saving...' : editingExerciseId ? 'Save Exercise' : 'Add Exercise'}
                            </button>
                            <button className="btn" onClick={closeExerciseModal}>Cancel</button>
                        </div>
                    </div>
                </div>
            )}

            {/* Add Template Modal */}
            {showAddTemplate && (
                <div className="modal-overlay" onClick={closeTemplateModal}>
                    <div className="modal-content" onClick={e => e.stopPropagation()}>
                        <h3>{editingTemplateId ? 'Edit Workout Template' : 'New Workout Template'}</h3>
                        <input className="form-input" placeholder="Template name (e.g. Push Day)" value={templateForm.name} onChange={e => setTemplateForm({ ...templateForm, name: e.target.value })} autoFocus />
                        <input className="form-input" placeholder="Description (optional)" value={templateForm.description} onChange={e => setTemplateForm({ ...templateForm, description: e.target.value })} style={{ marginTop: 8 }} />
                        <div style={{ marginTop: 8, fontSize: 12, opacity: 0.8 }}>Pick exercises:</div>
                        <div style={{ marginTop: 4, maxHeight: 220, overflowY: 'auto', border: '1px solid #ddd', borderRadius: 4, padding: 8 }}>
                            {exercises.map(ex => {
                                const selected = templateForm.exercise_ids.includes(ex.id)
                                return (
                                    <label key={ex.id} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '2px 0' }}>
                                        <input
                                            type="checkbox"
                                            checked={selected}
                                            onChange={() => setTemplateForm({
                                                ...templateForm,
                                                exercise_ids: selected
                                                    ? templateForm.exercise_ids.filter(id => id !== ex.id)
                                                    : [...templateForm.exercise_ids, ex.id],
                                            })}
                                        />
                                        {ex.name} <span style={{ opacity: 0.6 }}>({ex.muscle_group})</span>
                                    </label>
                                )
                            })}
                        </div>
                        <div className="modal-actions">
                            <button className="btn btn-primary" onClick={handleSaveTemplate} disabled={createTemplate.isPending || updateTemplate.isPending || !templateForm.name.trim() || templateForm.exercise_ids.length === 0}>
                                {createTemplate.isPending || updateTemplate.isPending ? 'Saving...' : editingTemplateId ? 'Save Changes' : 'Save Template'}
                            </button>
                            <button className="btn" onClick={closeTemplateModal}>Cancel</button>
                        </div>
                    </div>
                </div>
            )}

            {/* Log Workout Modal */}
            {showLogWorkout && (
                <div className="modal-overlay" onClick={() => setShowLogWorkout(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 560 }}>
                        <h3>Log Workout {logForm.name && `- ${logForm.name}`}</h3>
                        <div style={{ display: 'flex', gap: 8 }}>
                            <input className="form-input" type="date" value={logForm.session_date} onChange={e => setLogForm({ ...logForm, session_date: e.target.value })} style={{ flex: 1 }} />
                            <input className="form-input" type="number" placeholder="Duration (min)" value={logForm.duration_minutes} onChange={e => setLogForm({ ...logForm, duration_minutes: e.target.value })} style={{ flex: 1 }} />
                        </div>
                        <input className="form-input" placeholder="Notes, including weights (optional)" value={logForm.notes} onChange={e => setLogForm({ ...logForm, notes: e.target.value })} style={{ marginTop: 8 }} />

                        <div style={{ marginTop: 12, fontSize: 12, opacity: 0.8 }}>Exercises:</div>
                        {logForm.exercises.length === 0 && (
                            <div style={{ fontSize: 12, opacity: 0.6, padding: '6px 0' }}>No exercises added yet.</div>
                        )}
                        {logForm.exercises.map((ex, idx) => (
                            <div key={idx} style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 6 }}>
                                <span style={{ flex: 1, fontSize: 13 }}>{exerciseName(ex.exercise_id)}</span>
                                <input className="form-input" type="number" min={0} placeholder="Sets" aria-label={`${exerciseName(ex.exercise_id)} sets`} value={ex.sets_completed} onChange={e => updateLoggedExercise(idx, { sets_completed: e.target.value === '' ? '' : Number(e.target.value) })} style={{ width: 82 }} />
                                <input className="form-input" type="number" min={0} placeholder="Reps" aria-label={`${exerciseName(ex.exercise_id)} reps`} value={ex.reps_completed} onChange={e => updateLoggedExercise(idx, { reps_completed: e.target.value === '' ? '' : Number(e.target.value) })} style={{ width: 82 }} />
                                <button className="delete-btn" onClick={() => removeLoggedExercise(idx)} aria-label="Remove exercise"><Icon name="close" size={16} label="Remove exercise" /></button>
                            </div>
                        ))}
                        <select className="form-input" defaultValue="" onChange={e => { addExerciseToLog(Number(e.target.value)); e.target.value = '' }} style={{ marginTop: 8 }}>
                            <option value="">+ Add exercise...</option>
                            {exercises.map(ex => (
                                <option key={ex.id} value={ex.id}>{ex.name}</option>
                            ))}
                        </select>

                        <div className="modal-actions">
                            <button className="btn btn-primary" onClick={handleLogWorkout} disabled={logWorkout.isPending || logForm.exercises.length === 0}>
                                {logWorkout.isPending ? 'Saving...' : 'Save Workout'}
                            </button>
                            <button className="btn" onClick={() => setShowLogWorkout(false)}>Cancel</button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}
