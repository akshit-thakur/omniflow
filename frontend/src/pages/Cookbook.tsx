/**
 * Cookbook Page - Recipes and per-recipe ingredient linking.
 * Ingredients are selected from the shared ingredient library while creating or editing recipes.
 */

import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
    useRecipes,
    useRecipe,
    useCreateRecipe,
    useUpdateRecipe,
    useDeleteRecipe,
    useIngredients,
    useAddRecipeIngredient,
    useRemoveRecipeIngredient,
    useRecipeAvailability,
    type Recipe,
    type Ingredient,
} from '../api/cookbook'
import { Icon } from '../components/Icon'
import { ModuleExportButton } from '../components/BackupActions'
import { QueryErrorState } from '../components/QueryErrorState'
import { exactNonNegativeDecimal } from '../utils/decimal'
import { useEscapeKey } from '../utils/useEscapeKey'

type SortOption = 'recent' | 'prep_time' | 'name'
type DifficultyFilter = 'all' | 'Easy' | 'Medium' | 'Hard'

const DIFFICULTIES = ['Easy', 'Medium', 'Hard'] as const

export function CookbookPage() {
    const [search, setSearch] = useState('')
    const [difficulty, setDifficulty] = useState<DifficultyFilter>('all')
    const [sort, setSort] = useState<SortOption>('recent')
    const [showAddRecipe, setShowAddRecipe] = useState(false)
    const [editId, setEditId] = useState<number | null>(null)
    const [searchParams] = useSearchParams()
    const [viewId, setViewId] = useState<number | null>(() => {
        const recipeId = Number(searchParams.get('recipe'))
        return Number.isSafeInteger(recipeId) && recipeId > 0 ? recipeId : null
    })
    const [recipeIngredients, setRecipeIngredients] = useState<Array<{ ingredient_id: string; quantity: string; unit: string }>>([])

    const [recipeForm, setRecipeForm] = useState({
        name: '', description: '', instructions: '', difficulty: 'Easy', prep_time_minutes: ''
    })

    const { data: recipes = [], isLoading: loadingRecipes, error: recipesError } = useRecipes()
    const { data: ingredients = [] } = useIngredients()
    const createRecipe = useCreateRecipe()
    const deleteRecipe = useDeleteRecipe()
    const addRecipeIngredient = useAddRecipeIngredient()

    const handleAddRecipe = async () => {
        if (!recipeForm.name.trim() || !recipeForm.instructions.trim()) return
        const completedIngredients = recipeIngredients.filter(line => line.ingredient_id || line.quantity || line.unit.trim())
        if (completedIngredients.some(line => !line.ingredient_id || !line.quantity || !line.unit.trim())) return
        const recipe = await createRecipe.mutateAsync({
            name: recipeForm.name,
            description: recipeForm.description || undefined,
            instructions: recipeForm.instructions,
            difficulty: recipeForm.difficulty as 'Easy' | 'Medium' | 'Hard',
            prep_time_minutes: recipeForm.prep_time_minutes ? parseInt(recipeForm.prep_time_minutes) : undefined,
        }) as Recipe
        await Promise.all(completedIngredients.map(line => addRecipeIngredient.mutateAsync({
            recipe_id: recipe.id,
            ingredient_id: parseInt(line.ingredient_id),
            quantity: line.quantity,
            unit: line.unit.trim(),
        })))
        setRecipeForm({ name: '', description: '', instructions: '', difficulty: 'Easy', prep_time_minutes: '' })
        setRecipeIngredients([])
        setShowAddRecipe(false)
    }

    const addIngredientRow = () => setRecipeIngredients([...recipeIngredients, { ingredient_id: '', quantity: '', unit: '' }])
    const openAddRecipe = () => { setRecipeIngredients([{ ingredient_id: '', quantity: '', unit: '' }]); setShowAddRecipe(true) }
    const updateIngredientRow = (index: number, patch: Partial<typeof recipeIngredients[number]>) => setRecipeIngredients(recipeIngredients.map((line, i) => i === index ? { ...line, ...patch } : line))
    const removeIngredientRow = (index: number) => setRecipeIngredients(recipeIngredients.filter((_, i) => i !== index))
    const handleDeleteRecipe = (id: number, name: string) => {
        if (!window.confirm(`Delete recipe "${name}"?`)) return
        deleteRecipe.mutate(id)
    }

    const visibleRecipes = useMemo(() => {
        const q = search.trim().toLowerCase()
        let list = recipes.filter((r: Recipe) => {
            if (difficulty !== 'all' && r.difficulty !== difficulty) return false
            if (q && !r.name.toLowerCase().includes(q) && !(r.description || '').toLowerCase().includes(q)) return false
            return true
        })
        list = [...list].sort((a, b) => {
            if (sort === 'prep_time') return (a.prep_time_minutes ?? Infinity) - (b.prep_time_minutes ?? Infinity)
            if (sort === 'name') return a.name.localeCompare(b.name)
            return b.id - a.id // recent = highest id first
        })
        return list
    }, [recipes, search, difficulty, sort])

    useEscapeKey(showAddRecipe, () => { setShowAddRecipe(false); setRecipeIngredients([]) })
    if (recipesError) return <QueryErrorState message="Could not load recipes." error={recipesError} />
    return (
        <div className="page">
            <div className="page-tabs" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                    <h2 style={{ margin: 0 }}>Cookbook</h2>
                    <div className="empty-text" style={{ marginTop: 2 }}>{recipes.length} recipes</div>
                </div>
                <ModuleExportButton module="kitchen" />
            </div>

            <div className="content-card">
                <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between' }}>
                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', flex: 1 }}>
                        <input
                            className="form-input"
                            placeholder="Search recipes..."
                            value={search}
                            onChange={e => setSearch(e.target.value)}
                            style={{ width: 'auto', minWidth: 200, flex: '1 1 200px' }}
                        />
                        <select className="form-input" value={difficulty} onChange={e => setDifficulty(e.target.value as DifficultyFilter)} style={{ width: 'auto', minWidth: 140 }}>
                            <option value="all">Filter: All Difficulties</option>
                            {DIFFICULTIES.map(d => <option key={d} value={d}>{d}</option>)}
                        </select>
                        <select className="form-input" value={sort} onChange={e => setSort(e.target.value as SortOption)} style={{ width: 'auto', minWidth: 150 }}>
                            <option value="recent">Sort: Recently Added</option>
                            <option value="prep_time">Sort: Prep Time</option>
                            <option value="name">Sort: Name</option>
                        </select>
                    </div>
                    <button className="btn btn-primary toolbar-action" onClick={openAddRecipe}>
                        <Icon name="add" size={16} /> Add Recipe
                    </button>
                </div>

                <h3>All Recipes</h3>

                {loadingRecipes ? <div className="empty-state"><div className="empty-text">Loading...</div></div> :
                    visibleRecipes.length === 0 ? (
                        <div className="empty-state">
                            <div className="empty-icon"><Icon name="cookbook" size={48} /></div>
                            <div className="empty-title">No recipes found</div>
                            <div className="empty-text">Add your first recipe to get started!</div>
                        </div>
                    ) : (
                        <ul className="item-list">
                            {visibleRecipes.map((r: Recipe) => (
                                <li key={r.id} className="item-row">
                                    <div className="item-info" style={{ cursor: 'pointer' }} onClick={() => setViewId(r.id)}>
                                        <strong>{r.name}</strong>
                                        <span className="item-meta">
                                            {r.difficulty && `${r.difficulty}`}
                                            {r.prep_time_minutes ? ` • ${r.prep_time_minutes}m prep` : ''}
                                            {r.ingredient_count != null ? ` • ${r.ingredient_count} ingredients` : ''}
                                        </span>
                                    </div>
                                    <button className="item-action" onClick={() => setEditId(r.id)} aria-label={`Edit recipe ${r.name}`}><Icon name="edit" size={16} /></button>
                                    <button className="delete-btn" onClick={() => handleDeleteRecipe(r.id, r.name)} aria-label={`Delete recipe ${r.name}`}><Icon name="delete" size={16} label={`Delete recipe ${r.name}`} /></button>
                                </li>
                            ))}
                        </ul>
                    )
                }
            </div>

            {/* Add Recipe Modal */}
            {showAddRecipe && (
                <div className="modal-overlay" onClick={() => setShowAddRecipe(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()}>
                        <h3>Add Recipe</h3>
                        <input className="form-input" placeholder="Recipe name *" value={recipeForm.name} onChange={e => setRecipeForm({ ...recipeForm, name: e.target.value })} autoFocus />
                        <input className="form-input" placeholder="Description" value={recipeForm.description} onChange={e => setRecipeForm({ ...recipeForm, description: e.target.value })} style={{ marginTop: 8 }} />
                        <textarea className="form-input" placeholder="Instructions *" value={recipeForm.instructions} onChange={e => setRecipeForm({ ...recipeForm, instructions: e.target.value })} rows={4} style={{ marginTop: 8 }} />
                        <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                            <select className="form-input" value={recipeForm.difficulty} onChange={e => setRecipeForm({ ...recipeForm, difficulty: e.target.value })} style={{ flex: 1 }}>
                                {DIFFICULTIES.map(d => <option key={d} value={d}>{d}</option>)}
                            </select>
                            <input className="form-input" placeholder="Prep (min)" value={recipeForm.prep_time_minutes} onChange={e => setRecipeForm({ ...recipeForm, prep_time_minutes: e.target.value })} style={{ flex: 1 }} />
                        </div>
                        <h4 style={{ marginTop: 16, marginBottom: 8 }}>Ingredients <span className="item-meta">(optional)</span></h4>
                        {recipeIngredients.map((line, index) => (
                            <div key={index} style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                                <select className="form-input" value={line.ingredient_id} onChange={e => updateIngredientRow(index, { ingredient_id: e.target.value, unit: ingredients.find(i => i.id === Number(e.target.value))?.default_unit || line.unit })} style={{ flex: 2 }}>
                                    <option value="">Select ingredient</option>
                                    {ingredients.map(ingredient => <option key={ingredient.id} value={ingredient.id}>{ingredient.name}</option>)}
                                </select>
                                <input className="form-input" type="number" min="0" step="0.01" placeholder="Qty" value={line.quantity} onChange={e => updateIngredientRow(index, { quantity: e.target.value })} style={{ flex: 1 }} />
                                <input className="form-input" placeholder="Unit" value={line.unit} onChange={e => updateIngredientRow(index, { unit: e.target.value })} style={{ flex: 1 }} />
                                <button className="delete-btn" onClick={() => removeIngredientRow(index)} aria-label="Remove ingredient"><Icon name="close" size={16} label="Remove ingredient" /></button>
                            </div>
                        ))}
                        <button className="btn" type="button" onClick={addIngredientRow} style={{ marginTop: 8 }}>+ Add ingredient</button>

                        <div className="modal-actions">
                            <button className="btn btn-primary" onClick={handleAddRecipe} disabled={createRecipe.isPending || addRecipeIngredient.isPending}>{createRecipe.isPending || addRecipeIngredient.isPending ? 'Adding...' : 'Add Recipe'}</button>
                            <button className="btn" onClick={() => { setShowAddRecipe(false); setRecipeIngredients([]) }}>Cancel</button>
                        </div>
                    </div>
                </div>
            )}

            {/* Edit Recipe Modal */}
            {viewId != null && (
                <RecipeDetails recipeId={viewId} onClose={() => setViewId(null)} />
            )}

            {editId != null && (
                <RecipeEditor
                    recipeId={editId}
                    ingredients={ingredients}
                    onClose={() => setEditId(null)}
                />
            )}
        </div>
    )
}

function RecipeDetails({ recipeId, onClose }: { recipeId: number; onClose: () => void }) {
    const { data: recipe, isLoading } = useRecipe(recipeId)
    useEscapeKey(true, onClose)

    return (
        <div className="modal-overlay" onClick={onClose}>
            <div className="modal-content recipe-details-modal" onClick={e => e.stopPropagation()}>
                {isLoading || !recipe ? (
                    <div className="recipe-details-loading">Loading recipe...</div>
                ) : (
                    <>
                        <div className="modal-header recipe-details-header">
                            <div>
                                <div className="recipe-details-kicker">Recipe details</div>
                                <h3>{recipe.name}</h3>
                            </div>
                            <button className="modal-close" onClick={onClose} aria-label="Close recipe details"><Icon name="close" size={20} /></button>
                        </div>
                        <div className="recipe-details-body">
                            <div className="recipe-details-meta">
                                <span>{recipe.difficulty || 'No difficulty set'}</span>
                                {recipe.prep_time_minutes != null && <span>{recipe.prep_time_minutes} min prep</span>}
                            </div>
                            <section className="recipe-details-section">
                                <h4>Description</h4>
                                <p>{recipe.description || 'No description provided.'}</p>
                            </section>
                            <section className="recipe-details-section">
                                <h4>Instructions</h4>
                                <div className="recipe-details-instructions">{recipe.instructions || 'No instructions provided.'}</div>
                            </section>
                            <section className="recipe-details-section">
                                <h4>Ingredients <span>{recipe.ingredients?.length || 0}</span></h4>
                                {recipe.ingredients?.length ? (
                                    <ul className="recipe-ingredient-list">
                                        {recipe.ingredients.map(line => (
                                            <li key={line.ingredient_id}>
                                                <strong>{line.ingredient_name || 'Ingredient'}</strong>
                                                <span>{line.quantity} {line.unit}</span>
                                            </li>
                                        ))}
                                    </ul>
                                ) : <div className="recipe-details-empty">No ingredients linked yet.</div>}
                            </section>
                        </div>
                        <div className="modal-actions recipe-details-footer">
                            <button className="btn btn-primary" onClick={onClose}>Done</button>
                        </div>
                    </>
                )}
            </div>
        </div>
    )
}
interface RecipeEditorProps {
    recipeId: number
    ingredients: Ingredient[]
    onClose: () => void
}

function RecipeEditor({ recipeId, ingredients, onClose }: RecipeEditorProps) {
    const { data: recipe, isLoading } = useRecipe(recipeId)
    const { data: availability } = useRecipeAvailability(recipeId)
    const updateRecipe = useUpdateRecipe()
    const addIng = useAddRecipeIngredient()
    const removeIng = useRemoveRecipeIngredient()

    const [edits, setEdits] = useState<{
        name?: string; description?: string; instructions?: string;
        difficulty?: string; prep_time_minutes?: string;
    }>({})

    const [newIng, setNewIng] = useState({ ingredient_id: '', quantity: '', unit: '' })

    const handleSave = () => {
        if (!recipe) return
        const data: Record<string, unknown> = {}
        if (edits.name !== undefined && edits.name !== recipe.name) data.name = edits.name
        if (edits.description !== undefined && edits.description !== (recipe.description ?? '')) data.description = edits.description
        if (edits.instructions !== undefined && edits.instructions !== (recipe.instructions ?? '')) data.instructions = edits.instructions
        if (edits.difficulty && edits.difficulty !== recipe.difficulty) data.difficulty = edits.difficulty
        if (edits.prep_time_minutes !== undefined) {
            const n = parseInt(edits.prep_time_minutes)
            if (!isNaN(n) && n !== recipe.prep_time_minutes) data.prep_time_minutes = n
        }
        if (Object.keys(data).length === 0) { onClose(); return }
        updateRecipe.mutate({ id: recipeId, data: data as Parameters<typeof updateRecipe.mutate>[0]['data'] }, {
            onSuccess: () => onClose(),
        })
    }

    const handleAddIngredient = () => {
        const ingId = parseInt(newIng.ingredient_id)
        const quantity = exactNonNegativeDecimal(newIng.quantity, 8)
        if (!ingId || quantity === null || !newIng.unit.trim()) return
        addIng.mutate(
            { recipe_id: recipeId, ingredient_id: ingId, quantity, unit: newIng.unit },
            { onSuccess: () => setNewIng({ ingredient_id: '', quantity: '', unit: '' }) }
        )
    }

    const handleRemoveIngredient = (ingredient_id: number, name: string) => {
        if (!window.confirm(`Remove ${name} from recipe?`)) return
        removeIng.mutate({ recipe_id: recipeId, ingredient_id })
    }

    const onSelectIngredient = (id: string) => {
        const ing = ingredients.find(i => i.id === parseInt(id))
        setNewIng({ ...newIng, ingredient_id: id, unit: ing?.default_unit ?? newIng.unit })
    }

    useEscapeKey(true, onClose)
    if (isLoading || !recipe) {
        return (
            <div className="modal-overlay" onClick={onClose}>
                <div className="modal-content" onClick={e => e.stopPropagation()}><div className="empty-text">Loading...</div></div>
            </div>
        )
    }

    const v = (key: keyof typeof edits, fallback: string | number | undefined) =>
        edits[key] !== undefined ? edits[key] as string : (fallback != null ? String(fallback) : '')

    const linked = recipe.ingredients ?? []

    return (
        <div className="modal-overlay" onClick={onClose}>
            <div className="modal-content" style={{ maxWidth: 600, maxHeight: '85vh', overflowY: 'auto' }} onClick={e => e.stopPropagation()}>
                <h3>Edit Recipe</h3>

                <input className="form-input" placeholder="Name" value={v('name', recipe.name)} onChange={e => setEdits({ ...edits, name: e.target.value })} />
                <input className="form-input" placeholder="Description" value={v('description', recipe.description)} onChange={e => setEdits({ ...edits, description: e.target.value })} style={{ marginTop: 8 }} />
                <textarea className="form-input" placeholder="Instructions" rows={4} value={v('instructions', recipe.instructions)} onChange={e => setEdits({ ...edits, instructions: e.target.value })} style={{ marginTop: 8 }} />
                <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                    <select className="form-input" value={v('difficulty', recipe.difficulty)} onChange={e => setEdits({ ...edits, difficulty: e.target.value })} style={{ flex: 1 }}>
                        {DIFFICULTIES.map(d => <option key={d} value={d}>{d}</option>)}
                    </select>
                    <input className="form-input" type="number" placeholder="Prep (min)" value={v('prep_time_minutes', recipe.prep_time_minutes)} onChange={e => setEdits({ ...edits, prep_time_minutes: e.target.value })} style={{ flex: 1 }} />
                </div>

                <h4 style={{ marginTop: 16 }}>Ingredients</h4>
                {linked.length === 0 ? (
                    <div className="item-meta">No ingredients linked yet.</div>
                ) : (
                    <ul className="item-list">
                        {linked.map(line => (
                            <li key={line.ingredient_id} className="item-row">
                                <div className="item-info">
                                    <strong>{line.ingredient_name ?? `#${line.ingredient_id}`}</strong>
                                    <span className="item-meta">{line.quantity} {line.unit}</span>
                                </div>
                                <button className="delete-btn" onClick={() => handleRemoveIngredient(line.ingredient_id, line.ingredient_name ?? 'ingredient')} aria-label={`Remove ${line.ingredient_name ?? 'ingredient'}`}><Icon name="delete" size={16} label={`Remove ${line.ingredient_name ?? 'ingredient'}`} /></button>
                            </li>
                        ))}
                    </ul>
                )}

                <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                    <select className="form-input" value={newIng.ingredient_id} onChange={e => onSelectIngredient(e.target.value)} style={{ flex: 2 }}>
                        <option value="">Add ingredient...</option>
                        {ingredients.map(i => <option key={i.id} value={i.id}>{i.name}</option>)}
                    </select>
                    <input className="form-input" type="number" step="0.01" placeholder="Qty" value={newIng.quantity} onChange={e => setNewIng({ ...newIng, quantity: e.target.value })} style={{ flex: 1 }} />
                    <input className="form-input" placeholder="Unit" value={newIng.unit} onChange={e => setNewIng({ ...newIng, unit: e.target.value })} style={{ flex: 1 }} />
                    <button className="btn btn-primary" onClick={handleAddIngredient} disabled={addIng.isPending}>+ Add</button>
                </div>

                {availability && linked.length > 0 && (
                    <div style={{ marginTop: 12, fontSize: 13 }}>
                        <strong>Availability:</strong>{' '}
                        {availability.can_make
                            ? <span className="icon-text" style={{ color: 'var(--success)' }}><Icon name="check" size={16} /> All ingredients available</span>
                            : <span style={{ color: '#ef4444' }}>
                                {availability.missing.length > 0 && `Missing: ${availability.missing.map(i => i.ingredient_name).join(', ')}. `}
                                {availability.low.length > 0 && `Low: ${availability.low.map(i => i.ingredient_name).join(', ')}.`}
                            </span>}
                    </div>
                )}

                <div className="modal-actions">
                    <button className="btn btn-primary" onClick={handleSave} disabled={updateRecipe.isPending}>{updateRecipe.isPending ? 'Saving...' : 'Save'}</button>
                    <button className="btn" onClick={onClose}>Close</button>
                </div>
            </div>
        </div>
    )
}
