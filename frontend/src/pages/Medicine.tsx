/**
 * Medicine Page - Catalog, Plans, and "Take" logging
 */

import { useMemo, useState } from 'react'
import {
    useMedications,
    useCreateMedication,
    useDeleteMedication,
    useMedicationPlans,
    useCreateMedicationPlan,
    useDeleteMedicationPlan,
    useMedicationLogs,
    useLogMedication,
    type Medication,
    type MedicationPlan,
    type MedicationLog,
} from '../api/medications'
import { Icon } from '../components/Icon'
import { ModuleExportButton } from '../components/BackupActions'
import { QueryErrorState } from '../components/QueryErrorState'
import { useEscapeKey } from '../utils/useEscapeKey'

type MedsTab = 'plans' | 'meds'
type MedsFilter = 'all' | 'with_dosage' | 'no_dosage'
type PlansFilter = 'all' | 'active' | 'inactive'

function formatDoseTime(value: string) {
    return new Date(value).toLocaleString([], {
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
    })
}

export function MedicinePage() {
    const [tab, setTab] = useState<MedsTab>('plans')
    const [showHistory, setShowHistory] = useState(false)
    const [search, setSearch] = useState('')
    const [medsFilter, setMedsFilter] = useState<MedsFilter>('all')
    const [plansFilter, setPlansFilter] = useState<PlansFilter>('all')
    const [lastLogged, setLastLogged] = useState<MedicationLog | null>(null)

    const [showAddMed, setShowAddMed] = useState(false)
    const [showAddPlan, setShowAddPlan] = useState(false)
    const [medForm, setMedForm] = useState({ name: '', common_dosage: '', notes: '' })
    const [planForm, setPlanForm] = useState({
        plan_name: '',
        medication_id: 0,
        dosage: '',
        notes: '',
        schedule_times: '',
    })

    const { data: medications = [], isLoading, error: medicationsError } = useMedications()
    const { data: plans = [] } = useMedicationPlans()
    const { data: logs = [] } = useMedicationLogs()
    const createMedication = useCreateMedication()
    const deleteMedication = useDeleteMedication()
    const createPlan = useCreateMedicationPlan()
    const deletePlan = useDeleteMedicationPlan()
    const logMedication = useLogMedication()

    const selectTab = (next: MedsTab) => {
        setTab(next)
        setShowHistory(false)
        setSearch('')
    }

    const handleAddMed = () => {
        if (!medForm.name.trim()) return
        createMedication.mutate(medForm, {
            onSuccess: () => {
                setMedForm({ name: '', common_dosage: '', notes: '' })
                setShowAddMed(false)
            },
        })
    }

    const handleAddPlan = () => {
        if (!planForm.plan_name.trim() || !planForm.medication_id) return
        const times = planForm.schedule_times
            .split(',')
            .map(t => t.trim())
            .filter(Boolean)
        createPlan.mutate(
            {
                plan_name: planForm.plan_name,
                medication_id: planForm.medication_id,
                dosage: planForm.dosage || undefined,
                notes: planForm.notes || undefined,
                schedule_times: times,
            },
            {
                onSuccess: () => {
                    setPlanForm({ plan_name: '', medication_id: 0, dosage: '', notes: '', schedule_times: '' })
                    setShowAddPlan(false)
                },
            }
        )
    }

    const handleTake = (plan: MedicationPlan, scheduledTime?: string) => {
        logMedication.mutate({
            plan_id: plan.id,
            scheduled_time: scheduledTime,
        }, {
            onSuccess: log => {
                setLastLogged(log)
            },
        })
    }

    const handleConfirmDelete = (label: string, fn: () => void) => {
        if (window.confirm(`Delete "${label}"? This cannot be undone.`)) fn()
    }

    const filteredMeds = useMemo(() => {
        const q = search.trim().toLowerCase()
        return medications.filter((m: Medication) => {
            if (medsFilter === 'with_dosage' && !m.common_dosage) return false
            if (medsFilter === 'no_dosage' && m.common_dosage) return false
            if (q && !m.name.toLowerCase().includes(q)) return false
            return true
        })
    }, [medications, medsFilter, search])

    const filteredPlans = useMemo(() => {
        const q = search.trim().toLowerCase()
        return plans.filter((p: MedicationPlan) => {
            if (plansFilter === 'active' && !p.active) return false
            if (plansFilter === 'inactive' && p.active) return false
            if (q && !p.plan_name.toLowerCase().includes(q) && !(p.medication_name || '').toLowerCase().includes(q)) return false
            return true
        })
    }, [plans, plansFilter, search])

    useEscapeKey(showAddMed || showAddPlan, () => {
        if (showAddMed) setShowAddMed(false)
        else setShowAddPlan(false)
    })
    if (medicationsError) return <QueryErrorState message="Could not load medications." error={medicationsError} />
    return (
        <div className="page">
            {/* Page header: title/count on the left, History toggle on the right */}
            <div className="page-tabs" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div>
                    <h2 style={{ margin: 0 }}>Medicine</h2>
                    <div className="empty-text" style={{ marginTop: 2 }}>{medications.length} medications · {plans.length} plans</div>
                </div>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                    <ModuleExportButton module="medications" />
                    <button className="tab-btn secondary" onClick={() => setShowHistory(v => !v)}>
                        <Icon name={showHistory ? 'list' : 'stats'} size={16} /> {showHistory ? 'Back' : 'History'}
                    </button>
                </div>
            </div>

            <div className="content-card">
                {/* Tabs: Plans | Meds */}
                <div className="filter-tabs">
                    <button className={`filter-btn ${!showHistory && tab === 'plans' ? 'active' : ''}`} onClick={() => selectTab('plans')}>
                        <Icon name="list" size={16} /> Plans <span className="filter-btn-count">{plans.length}</span>
                    </button>
                    <button className={`filter-btn ${!showHistory && tab === 'meds' ? 'active' : ''}`} onClick={() => selectTab('meds')}>
                        <Icon name="medicine" size={16} /> Meds <span className="filter-btn-count">{medications.length}</span>
                    </button>
                </div>

                {!showHistory && (
                    <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between' }}>
                        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', flex: 1 }}>
                            <input
                                className="form-input"
                                placeholder={tab === 'meds' ? 'Search medications...' : 'Search plans...'}
                                value={search}
                                onChange={e => setSearch(e.target.value)}
                                style={{ width: 'auto', minWidth: 200, flex: '1 1 200px' }}
                            />
                            {tab === 'meds' ? (
                                <select className="form-input" value={medsFilter} onChange={e => setMedsFilter(e.target.value as MedsFilter)} style={{ width: 'auto', minWidth: 150 }}>
                                    <option value="all">Filter: All Medications</option>
                                    <option value="with_dosage">With Dosage</option>
                                    <option value="no_dosage">No Dosage Set</option>
                                </select>
                            ) : (
                                <select className="form-input" value={plansFilter} onChange={e => setPlansFilter(e.target.value as PlansFilter)} style={{ width: 'auto', minWidth: 130 }}>
                                    <option value="all">Filter: All Plans</option>
                                    <option value="active">Active</option>
                                    <option value="inactive">Inactive</option>
                                </select>
                            )}
                        </div>
                        {tab === 'meds' ? (
                            <button className="btn btn-primary toolbar-action" onClick={() => setShowAddMed(true)}><Icon name="add" size={16} /> Add Medication</button>
                        ) : (
                            <button className="btn btn-primary toolbar-action" onClick={() => setShowAddPlan(true)} disabled={medications.length === 0}><Icon name="add" size={16} /> Add Plan</button>
                        )}
                    </div>
                )}

                <h3>{showHistory ? 'Medication History' : tab === 'meds' ? 'Medication Catalog' : 'Plans & Schedule'}</h3>

                {!showHistory && tab === 'plans' && lastLogged && (
                    <div className="inline-success" role="status">
                        <Icon name="check" size={18} />
                        <span>
                            Logged {lastLogged.medication_name || 'medication'}
                            {lastLogged.plan_name && ` from ${lastLogged.plan_name}`} at {formatDoseTime(lastLogged.taken_at)}.
                        </span>
                    </div>
                )}

                {!showHistory && tab === 'meds' && (
                    isLoading ? <div className="empty-state"><div className="empty-text">Loading...</div></div> :
                        filteredMeds.length === 0 ? (
                            <div className="empty-state">
                                <div className="empty-icon"><Icon name="medicine" size={48} /></div>
                                <div className="empty-title">No medications found</div>
                                <div className="empty-text">Add medications to start building plans!</div>
                            </div>
                        ) : (
                            <ul className="item-list">
                                {filteredMeds.map((med: Medication) => (
                                    <li key={med.id} className="item-row">
                                        <div className="item-info">
                                            <strong>{med.name}</strong>
                                            <span className="item-meta">
                                                {med.common_dosage || 'No dosage set'}
                                                {med.notes && ` • ${med.notes}`}
                                            </span>
                                        </div>
                                        <button
                                            className="delete-btn"
                                            onClick={() => handleConfirmDelete(med.name, () => deleteMedication.mutate(med.id))}
                                            aria-label={`Delete ${med.name}`}
                                        ><Icon name="delete" size={16} label={`Delete ${med.name}`} /></button>
                                    </li>
                                ))}
                            </ul>
                        )
                )}

                {!showHistory && tab === 'plans' && (
                    filteredPlans.length === 0 ? (
                        <div className="empty-state">
                            <div className="empty-icon"><Icon name="list" size={48} /></div>
                            <div className="empty-title">No plans found</div>
                            <div className="empty-text">Create a plan to schedule reminders and log doses</div>
                        </div>
                    ) : (
                        <ul className="item-list">
                            {filteredPlans.map((plan: MedicationPlan) => (
                                <li key={plan.id} className="item-row" style={{ flexDirection: 'column', alignItems: 'stretch', gap: 8 }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%' }}>
                                        <div className="item-info">
                                            <strong>{plan.plan_name} — {plan.medication_name}</strong>
                                            <span className="item-meta">
                                                {plan.dosage || 'no dosage'}{!plan.active && ' • inactive'}
                                            </span>
                                        </div>
                                        <button
                                            className="delete-btn"
                                            onClick={() => handleConfirmDelete(plan.plan_name, () => deletePlan.mutate(plan.id))}
                                            aria-label={`Delete plan ${plan.plan_name}`}
                                        ><Icon name="delete" size={16} label={`Delete plan ${plan.plan_name}`} /></button>
                                    </div>
                                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                                        {plan.schedule_times.length === 0 ? (
                                            <button
                                                className="btn btn-primary"
                                                onClick={() => handleTake(plan)}
                                                disabled={logMedication.isPending}
                                            >Take now</button>
                                        ) : (
                                            plan.schedule_times.map(t => (
                                                <button
                                                    key={t}
                                                    className="btn btn-primary"
                                                    onClick={() => handleTake(plan, t)}
                                                    disabled={logMedication.isPending}
                                                >Take {t}</button>
                                            ))
                                        )}
                                    </div>
                                </li>
                            ))}
                        </ul>
                    )
                )}

                {!showHistory && tab === 'plans' && logs.length > 0 && (
                    <section className="recent-log-section" aria-labelledby="recent-medication-logs">
                        <div className="section-heading-row">
                            <h4 id="recent-medication-logs">Recent dose history</h4>
                            <button className="tab-btn secondary" onClick={() => setShowHistory(true)}>
                                <Icon name="stats" size={16} /> View all
                            </button>
                        </div>
                        <ul className="item-list compact-list">
                            {logs.slice(0, 5).map((log: MedicationLog) => (
                                <li key={log.id} className="item-row">
                                    <div className="item-info">
                                        <strong>{log.medication_name}</strong>
                                        <span className="item-meta">
                                            {log.plan_name && `${log.plan_name} • `}
                                            {formatDoseTime(log.taken_at)}
                                            {log.scheduled_time && ` (scheduled ${log.scheduled_time})`}
                                        </span>
                                    </div>
                                </li>
                            ))}
                        </ul>
                    </section>
                )}

                {showHistory && (
                    logs.length === 0 ? (
                        <div className="empty-state">
                            <div className="empty-icon"><Icon name="stats" size={48} /></div>
                            <div className="empty-title">No history yet</div>
                            <div className="empty-text">Take medications to build history</div>
                        </div>
                    ) : (
                        <ul className="item-list">
                            {logs.slice(0, 50).map((log: MedicationLog) => (
                                <li key={log.id} className="item-row">
                                    <div className="item-info">
                                        <strong>{log.medication_name}</strong>
                                        <span className="item-meta">
                                            {log.plan_name && `${log.plan_name} • `}
                                            {formatDoseTime(log.taken_at)}
                                            {log.scheduled_time && ` (scheduled ${log.scheduled_time})`}
                                        </span>
                                    </div>
                                </li>
                            ))}
                        </ul>
                    )
                )}
            </div>

            {/* Add Medication Modal */}
            {showAddMed && (
                <div className="modal-overlay" onClick={() => setShowAddMed(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()}>
                        <h3>Add Medication</h3>
                        <input className="form-input" placeholder="Medication name" value={medForm.name} onChange={e => setMedForm({ ...medForm, name: e.target.value })} autoFocus />
                        <input className="form-input" placeholder="Common dosage (e.g. 500mg)" value={medForm.common_dosage} onChange={e => setMedForm({ ...medForm, common_dosage: e.target.value })} style={{ marginTop: 8 }} />
                        <textarea className="form-input" placeholder="Notes (optional)" value={medForm.notes} onChange={e => setMedForm({ ...medForm, notes: e.target.value })} style={{ marginTop: 8, minHeight: 60 }} />
                        <div className="modal-actions">
                            <button className="btn btn-primary" onClick={handleAddMed} disabled={createMedication.isPending}>{createMedication.isPending ? 'Adding...' : 'Add Medication'}</button>
                            <button className="btn" onClick={() => setShowAddMed(false)}>Cancel</button>
                        </div>
                    </div>
                </div>
            )}

            {/* Add Plan Modal */}
            {showAddPlan && (
                <div className="modal-overlay" onClick={() => setShowAddPlan(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()}>
                        <h3>New Medication Plan</h3>
                        <input className="form-input" placeholder="Plan name (e.g. Morning Routine)" value={planForm.plan_name} onChange={e => setPlanForm({ ...planForm, plan_name: e.target.value })} autoFocus />
                        <select className="form-input" value={planForm.medication_id} onChange={e => setPlanForm({ ...planForm, medication_id: Number(e.target.value) })} style={{ marginTop: 8 }}>
                            <option value={0}>-- Select medication --</option>
                            {medications.map(m => (
                                <option key={m.id} value={m.id}>{m.name}</option>
                            ))}
                        </select>
                        <input className="form-input" placeholder="Dosage for this plan (optional)" value={planForm.dosage} onChange={e => setPlanForm({ ...planForm, dosage: e.target.value })} style={{ marginTop: 8 }} />
                        <input className="form-input" placeholder="Schedule times, comma-separated (e.g. 08:00, 20:00)" value={planForm.schedule_times} onChange={e => setPlanForm({ ...planForm, schedule_times: e.target.value })} style={{ marginTop: 8 }} />
                        <textarea className="form-input" placeholder="Notes (optional)" value={planForm.notes} onChange={e => setPlanForm({ ...planForm, notes: e.target.value })} style={{ marginTop: 8, minHeight: 60 }} />
                        <div className="modal-actions">
                            <button className="btn btn-primary" onClick={handleAddPlan} disabled={createPlan.isPending || !planForm.plan_name.trim() || !planForm.medication_id}>{createPlan.isPending ? 'Saving...' : 'Create Plan'}</button>
                            <button className="btn" onClick={() => setShowAddPlan(false)}>Cancel</button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}
