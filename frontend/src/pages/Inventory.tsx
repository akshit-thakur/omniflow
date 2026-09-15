/**
 * Inventory Page (Ingredients Module) - With full CRUD functionality
 */

import { useMemo, useState } from 'react'
import { useInventory, useCreateInventoryItem, useUpdateInventoryItem, useDeleteInventoryItem, type InventoryItem } from '../api/inventory'
import { Icon } from '../components/Icon'
import { ModuleExportButton } from '../components/BackupActions'
import { QueryErrorState } from '../components/QueryErrorState'
import { exactNonNegativeDecimal } from '../utils/decimal'
import { useEscapeKey } from '../utils/useEscapeKey'

type ViewType = 'expiring' | 'low-stock' | 'all'
type SortOption = 'expiry' | 'name' | 'category'

export function InventoryPage() {
    const [view, setView] = useState<ViewType>('all')
    const [search, setSearch] = useState('')
    const [sort, setSort] = useState<SortOption>('expiry')
    const [categoryFilter, setCategoryFilter] = useState('all')
    const [showStats, setShowStats] = useState(false)
    const [showAdd, setShowAdd] = useState(false)
    const [editingItem, setEditingItem] = useState<InventoryItem | null>(null)
    const [form, setForm] = useState({ name: '', quantity: '', unit: '', category: '', expiry_date: '', min_quantity: '' })

    const { data: items = [], isLoading, error: inventoryError } = useInventory()
    const createItem = useCreateInventoryItem()
    const updateItem = useUpdateInventoryItem()
    const deleteItem = useDeleteInventoryItem()

    const resetForm = () => setForm({ name: '', quantity: '', unit: '', category: '', expiry_date: '', min_quantity: '' })

    const openAdd = () => { setEditingItem(null); resetForm(); setShowAdd(true) }

    const openEdit = (item: InventoryItem) => {
        setEditingItem(item)
        setForm({ name: item.name, quantity: String(item.quantity), unit: item.unit, category: item.category || '', expiry_date: item.expiry_date || '', min_quantity: String(item.min_quantity || '') })
        setShowAdd(true)
    }

    const closeModal = () => { setShowAdd(false); setEditingItem(null); resetForm() }

    const handleSave = () => {
        if (!form.name.trim() || !form.quantity || !form.unit.trim()) return
        const quantity = exactNonNegativeDecimal(form.quantity, 8)
        const minQuantity = form.min_quantity ? exactNonNegativeDecimal(form.min_quantity, 8) : undefined
        if (quantity === null || minQuantity === null) return
        const baseData = { name: form.name.trim(), quantity, unit: form.unit.trim(), category: form.category.trim() || undefined, min_quantity: minQuantity }
        if (editingItem) updateItem.mutate({ id: editingItem.id, data: { ...baseData, expiry_date: form.expiry_date || null } }, { onSuccess: closeModal })
        else createItem.mutate({ ...baseData, ...(form.expiry_date ? { expiry_date: form.expiry_date } : {}) }, { onSuccess: closeModal })
    }
    const expiring = items.filter(i => i.is_expiring_soon)
    const lowStock = items.filter(i => i.is_low_stock)
    const scoped = view === 'expiring' ? expiring : view === 'low-stock' ? lowStock : items

    const categories = useMemo(() => {
        const set = new Set<string>()
        items.forEach(i => { if (i.category) set.add(i.category) })
        return Array.from(set).sort()
    }, [items])

    const filtered = useMemo(() => {
        const q = search.trim().toLowerCase()
        let list = scoped.filter((i: InventoryItem) => {
            if (categoryFilter !== 'all' && i.category !== categoryFilter) return false
            if (q && !i.name.toLowerCase().includes(q) && !(i.category || '').toLowerCase().includes(q)) return false
            return true
        })
        list = [...list].sort((a, b) => {
            if (sort === 'name') return a.name.localeCompare(b.name)
            if (sort === 'category') return (a.category || '').localeCompare(b.category || '')
    return (a.expiry_date || '9999-99-99').localeCompare(b.expiry_date || '9999-99-99')
        })
        return list
    }, [scoped, search, categoryFilter, sort])

    useEscapeKey(showAdd, closeModal)
    if (inventoryError) return <QueryErrorState message="Could not load inventory." error={inventoryError} />
    const selectView = (next: ViewType) => {
        setView(next)
        setSearch('')
    }

    const handleDelete = (item: InventoryItem) => {
        if (window.confirm(`Delete "${item.name}" from inventory?`)) {
            deleteItem.mutate(item.id)
        }
    }

    return (
        <div className="page">
            <div className="page-tabs" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div>
                    <h2 style={{ margin: 0 }}>Kitchen Inventory</h2>
                    <div className="empty-text" style={{ marginTop: 2 }}>{items.length} items</div>
                </div>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                    <ModuleExportButton module="kitchen" />
                    <button className="tab-btn secondary" onClick={() => setShowStats(v => !v)}>
                        <Icon name="stats" size={16} /> {showStats ? 'Hide Stats' : 'Stats'}
                    </button>
                </div>
            </div>

            {showStats && (
                <div className="content-card" style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
                    <div><strong>{items.length}</strong> <span className="item-meta">total items</span></div>
                    <div><strong>{expiring.length}</strong> <span className="item-meta">expiring soon</span></div>
                    <div><strong>{lowStock.length}</strong> <span className="item-meta">low stock</span></div>
                </div>
            )}

            <div className="content-card">
                <div className="filter-tabs">
                    <button className={`filter-btn ${view === 'expiring' ? 'active' : ''}`} onClick={() => selectView('expiring')}>
                        <Icon name="warning" size={16} /> Expiring <span className="filter-btn-count">{expiring.length}</span>
                    </button>
                    <button className={`filter-btn ${view === 'low-stock' ? 'active' : ''}`} onClick={() => selectView('low-stock')}>
                        <Icon name="lowStock" size={16} /> Low Stock <span className="filter-btn-count">{lowStock.length}</span>
                    </button>
                    <button className={`filter-btn ${view === 'all' ? 'active' : ''}`} onClick={() => selectView('all')}>
                        <Icon name="package" size={16} /> All <span className="filter-btn-count">{items.length}</span>
                    </button>
                </div>

                <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between' }}>
                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', flex: 1 }}>
                        <input
                            className="form-input"
                            placeholder="Search inventory..."
                            value={search}
                            onChange={e => setSearch(e.target.value)}
                            style={{ width: 'auto', minWidth: 200, flex: '1 1 200px' }}
                        />
                        <select className="form-input" value={categoryFilter} onChange={e => setCategoryFilter(e.target.value)} style={{ width: 'auto', minWidth: 140 }}>
                            <option value="all">Filter: All Categories</option>
                            {categories.map(c => <option key={c} value={c}>{c}</option>)}
                        </select>
                        <select className="form-input" value={sort} onChange={e => setSort(e.target.value as SortOption)} style={{ width: 'auto', minWidth: 150 }}>
                            <option value="expiry">Sort: Expiration Date</option>
                            <option value="name">Sort: Name</option>
                            <option value="category">Sort: Category</option>
                        </select>
                    </div>
                    <button className="btn btn-primary toolbar-action" onClick={openAdd}><Icon name="add" size={16} /> Add Item</button>
                </div>

                <h3>{view === 'all' ? 'Kitchen Inventory' : view === 'expiring' ? 'Expiring Soon' : 'Low Stock Items'}</h3>

                {isLoading ? <div className="empty-state"><div className="empty-text">Loading...</div></div> :
                    filtered.length === 0 ? (
                        <div className="empty-state">
                            <div className="empty-icon"><Icon name="inventory" size={48} /></div>
                            <div className="empty-title">{view === 'all' ? 'No items in inventory' : view === 'expiring' ? 'No expiring items' : 'No low stock items'}</div>
                            <div className="empty-text">{view === 'all' ? 'Add items to track your kitchen stock!' : view === 'expiring' ? 'All items are fresh!' : 'All items well stocked!'}</div>
                        </div>
                    ) : (
                        <ul className="item-list">
                            {filtered.map((item: InventoryItem) => (
                                <li key={item.id} className="item-row">
                                    <div className="item-info">
                                        <strong>{item.name}</strong>
                                        <span className="item-meta">{item.quantity}
                                            {' '}{item.unit} {item.category && `• ${item.category}`} {item.expiry_date && `• Exp: ${new Date(item.expiry_date).toLocaleDateString()}`}
                                        </span>
                                    </div>
                                    {item.is_expiring_soon && <span className="priority-badge high">Expiring</span>}
                                    {item.is_low_stock && <span className="priority-badge medium">Low</span>}
                                    <button className="item-action" onClick={() => openEdit(item)} aria-label={`Edit ${item.name}`}><Icon name="edit" size={16} /></button>
                                    <button className="delete-btn" onClick={() => handleDelete(item)} aria-label={`Delete ${item.name}`}><Icon name="delete" size={16} label={`Delete ${item.name}`} /></button>
                                </li>
                            ))}
                        </ul>
                    )}
            </div>

            {/* Add Item Modal */}
            {showAdd && (
                <div className="modal-overlay" onClick={closeModal}>
                    <div className="modal-content" onClick={e => e.stopPropagation()}>
                        <h3>{editingItem ? 'Edit Inventory Item' : 'Add Inventory Item'}</h3>
                        <div className="form-field">
                            <label htmlFor="inventory-name">Ingredient name <span aria-hidden="true">*</span></label>
                            <input id="inventory-name" className="form-input" placeholder="e.g. Olive oil" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} autoFocus required />
                        </div>
                        <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
                            <div className="form-field" style={{ flex: 1 }}>
                                <label htmlFor="inventory-quantity">Quantity <span aria-hidden="true">*</span></label>
                                <input id="inventory-quantity" className="form-input" placeholder="0" type="number" min="0" step="any" value={form.quantity} onChange={e => setForm({ ...form, quantity: e.target.value })} required />
                            </div>
                            <div className="form-field" style={{ flex: 1 }}>
                                <label htmlFor="inventory-unit">Unit <span aria-hidden="true">*</span></label>
                                <input id="inventory-unit" className="form-input" placeholder="e.g. kg, bottle" value={form.unit} onChange={e => setForm({ ...form, unit: e.target.value })} required />
                            </div>
                        </div>
                        <div className="form-field">
                            <label htmlFor="inventory-category">Category <span>(optional)</span></label>
                            <input id="inventory-category" className="form-input" placeholder="e.g. Pantry, Produce" value={form.category} onChange={e => setForm({ ...form, category: e.target.value })} />
                        </div>
                        <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
                            <div className="form-field" style={{ flex: 1 }}>
                                <label htmlFor="inventory-expiry">Expiry date <span>(optional)</span></label>
                                <input id="inventory-expiry" className="form-input" type="date" value={form.expiry_date} onChange={e => setForm({ ...form, expiry_date: e.target.value })} />
                            </div>
                            <div className="form-field" style={{ flex: 1 }}>
                                <label htmlFor="inventory-min">Low-stock threshold <span>(optional)</span></label>
                                <input id="inventory-min" className="form-input" type="number" min="0" step="any" placeholder="0" value={form.min_quantity} onChange={e => setForm({ ...form, min_quantity: e.target.value })} />
                            </div>
                        </div>
                        <div className="modal-actions">
                            <button className="btn btn-primary" onClick={handleSave} disabled={createItem.isPending || updateItem.isPending}>{createItem.isPending || updateItem.isPending ? 'Saving...' : editingItem ? 'Save Changes' : 'Add Item'}</button>
                            <button className="btn" onClick={closeModal}>Cancel</button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}
