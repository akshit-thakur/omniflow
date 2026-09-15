/**
 * Meals Page (Meal Planner) - Next Meal timeline + 7x4 Weekly Grid
 */

import { Fragment, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMealPlans, useDeleteMealPlan, useSaveMealBatch, type MealPlan, type MealBatchItem } from '../api/mealplans'
import { useRecipes } from '../api/cookbook'
import { Icon } from '../components/Icon'
import { ModuleExportButton } from '../components/BackupActions'
import { QueryErrorState } from '../components/QueryErrorState'
import { useEscapeKey } from '../utils/useEscapeKey'

type MealPlanView = 'next_meal' | 'weekly'
type MealPlanModalTab = 'single_day' | 'full_week'
type DayOfWeek = 'Monday' | 'Tuesday' | 'Wednesday' | 'Thursday' | 'Friday' | 'Saturday' | 'Sunday'
type MealType = 'breakfast' | 'lunch' | 'snack' | 'dinner'

const DAYS: DayOfWeek[] = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
const MEAL_TYPES: MealType[] = ['breakfast', 'lunch', 'snack', 'dinner']
const MEAL_TYPE_LABEL: Record<MealType, string> = { breakfast: 'Breakfast', lunch: 'Lunch', snack: 'Snack', dinner: 'Dinner' }
const MEAL_HOUR: Record<MealType, number> = { breakfast: 8, lunch: 13, snack: 16, dinner: 19 }
const MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']

const parseLocalDate = (dateStr: string) => {
    const [y, m, d] = dateStr.split('-').map(Number)
    return new Date(y, m - 1, d)
}

const formatLocalDate = (d: Date) => {
    const y = d.getFullYear()
    const m = String(d.getMonth() + 1).padStart(2, '0')
    const day = String(d.getDate()).padStart(2, '0')
    return `${y}-${m}-${day}`
}

// Monday-based week start, independent of locale's default week start.
const startOfWeek = () => {
    const d = new Date()
    d.setHours(0, 0, 0, 0)
    const jsDay = d.getDay() // 0=Sun..6=Sat
    const diff = jsDay === 0 ? -6 : 1 - jsDay
    d.setDate(d.getDate() + diff)
    return d
}

const dateForDayIndex = (dayIndex: number) => {
    const d = startOfWeek()
    d.setDate(d.getDate() + dayIndex)
    return formatLocalDate(d)
}

const dayIndexFromDate = (dateStr: string) => {
    const jsDay = parseLocalDate(dateStr).getDay() // 0=Sun..6=Sat
    return (jsDay + 6) % 7 // 0=Mon..6=Sun
}

const dateSubtext = (dateStr: string) => {
    const d = parseLocalDate(dateStr)
    return `${String(d.getDate()).padStart(2, '0')}/${MONTHS[d.getMonth()]}`
}

const currentDayIndex = () => (new Date().getDay() + 6) % 7

const currentMealTypeIndex = () => {
    const hour = new Date().getHours()
    let idx = 0
    MEAL_TYPES.forEach((t, i) => { if (hour >= MEAL_HOUR[t]) idx = i })
    return idx
}

interface SlotState { recipe_id: string; notes: string }
const emptySlot = (): SlotState => ({ recipe_id: '', notes: '' })
const emptyDayForm = (): Record<MealType, SlotState> => ({
    breakfast: emptySlot(), lunch: emptySlot(), snack: emptySlot(), dinner: emptySlot(),
})

export function MealsPage() {
    const [view, setView] = useState<MealPlanView>('next_meal')
    const [showModal, setShowModal] = useState(false)
    const [modalTab, setModalTab] = useState<MealPlanModalTab>('single_day')
    const [saving, setSaving] = useState(false)

    const [singleDay, setSingleDay] = useState(currentDayIndex())
    const [singleDayForm, setSingleDayForm] = useState<Record<MealType, SlotState>>(emptyDayForm())
    const [weekForm, setWeekForm] = useState<Record<number, Record<MealType, string>>>(() => {
        const grid: Record<number, Record<MealType, string>> = {}
        DAYS.forEach((_, i) => { grid[i] = { breakfast: '', lunch: '', snack: '', dinner: '' } })
        return grid
    })

    const { data: mealPlans = [], isLoading, error: mealPlansError } = useMealPlans()
    const { data: recipes = [] } = useRecipes()
    const deleteMealPlan = useDeleteMealPlan()
    const saveMealBatch = useSaveMealBatch()

    const weekStart = startOfWeek()
    const thisWeek = useMemo(() => {
        const weekEnd = new Date(weekStart.getTime() + 7 * 24 * 60 * 60 * 1000)
        return mealPlans.filter(p => {
            const d = parseLocalDate(p.date)
            return d >= weekStart && d < weekEnd
        })
    }, [mealPlans, weekStart])

    const gridMap = useMemo(() => {
        const map = new Map<string, MealPlan>()
        thisWeek.forEach(p => map.set(`${dayIndexFromDate(p.date)}-${p.meal_type}`, p))
        return map
    }, [thisWeek])

    const nextMeals = useMemo(() => {
        const curKey = currentDayIndex() * MEAL_TYPES.length + currentMealTypeIndex()
        return thisWeek
            .map(p => {
                const dayIdx = dayIndexFromDate(p.date)
                const mealIdx = MEAL_TYPES.indexOf(p.meal_type as MealType)
                return { plan: p, sortKey: dayIdx * MEAL_TYPES.length + mealIdx, dayIdx }
            })
            .filter(x => x.sortKey >= curKey)
            .sort((a, b) => a.sortKey - b.sortKey)
    }, [thisWeek])

    const loadSingleDay = (day: number) => {
        setSingleDay(day)
        const form = emptyDayForm()
        MEAL_TYPES.forEach(t => {
            const existing = gridMap.get(`${day}-${t}`)
            if (existing) form[t] = { recipe_id: existing.recipe_id ? String(existing.recipe_id) : '', notes: existing.notes || '' }
        })
        setSingleDayForm(form)
    }

    const loadFullWeek = () => {
        const grid: Record<number, Record<MealType, string>> = {}
        DAYS.forEach((_, dayIdx) => {
            grid[dayIdx] = { breakfast: '', lunch: '', snack: '', dinner: '' }
            MEAL_TYPES.forEach(t => {
                const existing = gridMap.get(`${dayIdx}-${t}`)
                grid[dayIdx][t] = existing?.recipe_id ? String(existing.recipe_id) : ''
            })
        })
        setWeekForm(grid)
    }

    const openModal = (tab: MealPlanModalTab) => {
        if (tab === 'single_day') loadSingleDay(currentDayIndex())
        else loadFullWeek()
        setModalTab(tab)
        setShowModal(true)
    }

    const handleSaveSingleDay = async () => {
        setSaving(true)
        try {
            const items: MealBatchItem[] = []
            const deleteIds: number[] = []
            MEAL_TYPES.forEach(t => {
                const existing = gridMap.get(`${singleDay}-${t}`)
                const slot = singleDayForm[t]
                if (!slot.recipe_id && !slot.notes.trim()) {
                    if (existing) deleteIds.push(existing.id)
                } else {
                    items.push({ id: existing?.id, date: dateForDayIndex(singleDay), meal_type: t, recipe_id: slot.recipe_id ? parseInt(slot.recipe_id) : null, notes: slot.notes.trim() || null })
                }
            })
            await saveMealBatch.mutateAsync({ items, delete_ids: deleteIds })
            setShowModal(false)
        } finally {
            setSaving(false)
        }
    }

    const handleSaveFullWeek = async () => {
        setSaving(true)
        try {
            const items: MealBatchItem[] = []
            const deleteIds: number[] = []
            for (let dayIdx = 0; dayIdx < DAYS.length; dayIdx++) {
                for (const t of MEAL_TYPES) {
                    const existing = gridMap.get(`${dayIdx}-${t}`)
                    const recipeId = weekForm[dayIdx][t]
                    if (!recipeId) {
                        if (existing) deleteIds.push(existing.id)
                    } else {
                        items.push({ id: existing?.id, date: dateForDayIndex(dayIdx), meal_type: t, recipe_id: parseInt(recipeId), notes: existing?.notes || null })
                    }
                }
            }
            await saveMealBatch.mutateAsync({ items, delete_ids: deleteIds })
            setShowModal(false)
        } finally {
            setSaving(false)
        }
    }

    const handleSkip = (plan: MealPlan) => {
        if (window.confirm('Skip this meal? It will be removed from the plan.')) deleteMealPlan.mutate(plan.id)
    }

    useEscapeKey(showModal && !saving, () => setShowModal(false))
    if (mealPlansError) return <QueryErrorState message="Could not load meal plans." error={mealPlansError} />
    return (
        <div className="page">
            <div className="page-tabs" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                    <h2 style={{ margin: 0 }}>Meal Plan</h2>
                    <div className="empty-text" style={{ marginTop: 2 }}>{mealPlans.length} planned · {thisWeek.length} this week</div>
                </div>
                <ModuleExportButton module="kitchen" />
            </div>

            <div className="content-card">
                <div style={{ display: 'flex', gap: 16, alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', marginBottom: 16, borderBottom: '1px solid var(--border)', paddingBottom: 12 }}>
                    <div className="filter-tabs" style={{ marginBottom: 0, border: 'none' }}>
                        <button className={`filter-btn ${view === 'next_meal' ? 'active' : ''}`} onClick={() => setView('next_meal')}>
                            <Icon name="calendar" size={16} /> Next Meal
                        </button>
                        <button className={`filter-btn ${view === 'weekly' ? 'active' : ''}`} onClick={() => setView('weekly')}>
                            <Icon name="list" size={16} /> Weekly View
                        </button>
                    </div>
                    <button className="btn btn-primary toolbar-action" onClick={() => openModal(view === 'weekly' ? 'full_week' : 'single_day')}>
                        <Icon name="edit" size={16} /> Update Meal Plan
                    </button>
                </div>

                {view === 'next_meal' && (
                    isLoading ? <div className="empty-state"><div className="empty-text">Loading...</div></div> :
                        nextMeals.length === 0 ? (
                            <div className="empty-state">
                                <div className="empty-icon"><Icon name="meals" size={48} /></div>
                                <div className="empty-title">No upcoming meals planned</div>
                                <div className="empty-text">Use "Update Meal Plan" to plan your next meal!</div>
                            </div>
                        ) : (
                            <ul className="item-list">
                                {nextMeals.map(({ plan, dayIdx }) => (
                                    <li key={plan.id} className="item-row">
                                        <div className="item-info">
                                            <strong>{DAYS[dayIdx]} {MEAL_TYPE_LABEL[plan.meal_type as MealType]} <span style={{ fontWeight: 400, opacity: 0.6 }}>· {dateSubtext(plan.date)}</span></strong>
                                            {plan.recipe_id && plan.recipe_name ? (
                                                <Link className="item-meta" to={`/cookbook?recipe=${plan.recipe_id}`}>{plan.recipe_name}</Link>
                                            ) : (
                                                <span className="item-meta">{plan.notes || 'No recipe set'}</span>
                                            )}
                                        </div>
                                        <span className="priority-badge low">{plan.meal_type}</span>
                                        <button className="item-action item-action--skip" onClick={() => handleSkip(plan)} title="Skip meal" aria-label="Skip meal"><Icon name="close" size={16} /></button>
                                    </li>
                                ))}
                            </ul>
                        )
                )}

                {view === 'weekly' && (
                    <div className="meal-grid-wrapper">
                        <div className="meal-grid">
                            <div className="meal-grid-corner" />
                            {DAYS.map(day => <div key={day} className="meal-grid-day-header">{day.slice(0, 3)}</div>)}
                            {MEAL_TYPES.map(type => (
                                <Fragment key={type}>
                                    <div className="meal-grid-row-header">{MEAL_TYPE_LABEL[type]}</div>
                                    {DAYS.map((_, dayIdx) => {
                                        const plan = gridMap.get(`${dayIdx}-${type}`)
                                        return (
                                            <div key={`${dayIdx}-${type}`} className="meal-grid-cell">
                                                <span className={`meal-grid-chip ${plan ? '' : 'meal-grid-chip-empty'}`} title={plan?.recipe_name || plan?.notes || ''}>
                                                    {plan?.recipe_id && plan?.recipe_name ? (
                                                            <Link className="meal-grid-chip" to={`/cookbook?recipe=${plan.recipe_id}`}>{plan.recipe_name}</Link>
                                                        ) : (plan?.recipe_name || plan?.notes || '—')}
                                                </span>
                                            </div>
                                        )
                                    })}
                                </Fragment>
                            ))}
                        </div>
                    </div>
                )}
            </div>

            {/* Update Meal Plan Modal */}
            {showModal && (
                <div className="modal-overlay" onClick={() => !saving && setShowModal(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: modalTab === 'full_week' ? 860 : 480 }}>
                        <h3>Update Meal Plan</h3>
                        <div className="filter-tabs" style={{ marginTop: 8 }}>
                            <button className={`filter-btn ${modalTab === 'single_day' ? 'active' : ''}`} onClick={() => { setModalTab('single_day'); loadSingleDay(singleDay) }}>Single Day</button>
                            <button className={`filter-btn ${modalTab === 'full_week' ? 'active' : ''}`} onClick={() => { setModalTab('full_week'); loadFullWeek() }}>Full Week</button>
                        </div>

                        {modalTab === 'single_day' && (
                            <>
                                <select className="form-input" value={singleDay} onChange={e => loadSingleDay(Number(e.target.value))} style={{ marginTop: 12 }}>
                                    {DAYS.map((day, idx) => (
                                        <option key={day} value={idx}>{day} ({dateSubtext(dateForDayIndex(idx))})</option>
                                    ))}
                                </select>
                                {MEAL_TYPES.map(t => (
                                    <div key={t} style={{ marginTop: 10 }}>
                                        <label className="form-label">{MEAL_TYPE_LABEL[t]}</label>
                                        <select
                                            className="form-input"
                                            value={singleDayForm[t].recipe_id}
                                            onChange={e => setSingleDayForm({ ...singleDayForm, [t]: { ...singleDayForm[t], recipe_id: e.target.value } })}
                                        >
                                            <option value="">No recipe</option>
                                            {recipes.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}
                                        </select>
                                        <input
                                            className="form-input"
                                            placeholder="Notes (optional)"
                                            value={singleDayForm[t].notes}
                                            onChange={e => setSingleDayForm({ ...singleDayForm, [t]: { ...singleDayForm[t], notes: e.target.value } })}
                                            style={{ marginTop: 4 }}
                                        />
                                    </div>
                                ))}
                                <div className="modal-actions">
                                    <button className="btn btn-primary" onClick={handleSaveSingleDay} disabled={saving}>{saving ? 'Saving...' : 'Save Day'}</button>
                                    <button className="btn" onClick={() => setShowModal(false)} disabled={saving}>Cancel</button>
                                </div>
                            </>
                        )}

                        {modalTab === 'full_week' && (
                            <>
                                <div className="meal-grid-wrapper" style={{ marginTop: 12 }}>
                                    <div className="meal-grid meal-grid-editable">
                                        <div className="meal-grid-corner" />
                                        {DAYS.map(day => <div key={day} className="meal-grid-day-header">{day.slice(0, 3)}</div>)}
                                        {MEAL_TYPES.map(type => (
                                            <Fragment key={type}>
                                                <div className="meal-grid-row-header">{MEAL_TYPE_LABEL[type]}</div>
                                                {DAYS.map((_, dayIdx) => (
                                                    <div key={`${dayIdx}-${type}`} className="meal-grid-cell">
                                                        <select
                                                            className="form-input meal-grid-select"
                                                            value={weekForm[dayIdx][type]}
                                                            onChange={e => setWeekForm({
                                                                ...weekForm,
                                                                [dayIdx]: { ...weekForm[dayIdx], [type]: e.target.value },
                                                            })}
                                                        >
                                                            <option value="">—</option>
                                                            {recipes.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}
                                                        </select>
                                                    </div>
                                                ))}
                                            </Fragment>
                                        ))}
                                    </div>
                                </div>
                                <div className="modal-actions">
                                    <button className="btn btn-primary" onClick={handleSaveFullWeek} disabled={saving}>{saving ? 'Saving...' : 'Save Week'}</button>
                                    <button className="btn" onClick={() => setShowModal(false)} disabled={saving}>Cancel</button>
                                </div>
                            </>
                        )}
                    </div>
                </div>
            )}
        </div>
    )
}
