/**
 * Media Page - Feature-rich modal matching Vanilla JS
 * Supports: Book, Movie, TV Show, Video Game, Podcast, Documentary, Anime, Manga, Music Album, Audiobook
 */

import { useState, useRef } from 'react'
import {
    useMedia,
    useCreateMedia,
    useUpdateMedia,
    useDeleteMedia,
    useBulkImportMedia,
    type MediaCreateInput,
    type MediaItem,
    type MediaStatus,
    type MediaType,
    type MediaUpdateInput,
} from '../api/media'
import { Icon, type IconName } from '../components/Icon'
import { ModuleExportButton } from '../components/BackupActions'
import { QueryErrorState } from '../components/QueryErrorState'

type SortOption = 'title' | 'year' | 'rating'

const mediaTypeLabels: Record<MediaType, string> = {
    book: 'Book', movie: 'Movie', tv_show: 'TV Show', video_game: 'Video Game', podcast: 'Podcast',
    documentary: 'Documentary', anime: 'Anime', manga: 'Manga', music_album: 'Music Album', audiobook: 'Audiobook'
}

const statusLabels: Record<MediaStatus, string> = {
    to_watch: 'Want to Experience', plan_to_watch: 'Planned', watching: 'In Progress',
    completed: 'Completed', on_hold: 'On Hold', dropped: 'Dropped'
}

const mediaIcons: Record<MediaType, IconName> = {
    book: 'book', movie: 'movie', tv_show: 'tv_show', video_game: 'video_game', podcast: 'podcast',
    documentary: 'documentary', anime: 'anime', manga: 'manga', music_album: 'music_album', audiobook: 'audiobook'
}

const progressLabels: Record<string, { current: string; total: string; unit: string }> = {
    movie: { current: 'Minutes watched', total: 'Total minutes', unit: 'min' },
    book: { current: 'Pages read', total: 'Total pages', unit: 'pg' },
    tv_show: { current: 'Episodes watched', total: 'Total episodes', unit: 'ep' },
    anime: { current: 'Episodes watched', total: 'Total episodes', unit: 'ep' },
    manga: { current: 'Chapters read', total: 'Total chapters', unit: 'ch' },
    podcast: { current: 'Episodes heard', total: 'Total episodes', unit: 'ep' },
    documentary: { current: 'Minutes watched', total: 'Total minutes', unit: 'min' },
    video_game: { current: 'Hours played', total: 'Total hours', unit: 'hr' },
    music_album: { current: 'Tracks heard', total: 'Total tracks', unit: 'tr' },
    audiobook: { current: 'Hours listened', total: 'Total hours', unit: 'hr' },
}

const genresByMediaType: Record<string, string[]> = {
    movie: ['Action', 'Comedy', 'Drama', 'Horror', 'Sci-Fi', 'Thriller', 'Romance', 'Animation', 'Documentary', 'Fantasy', 'Mystery', 'Adventure', 'Crime', 'War', 'Musical', 'Western'],
    tv_show: ['Action', 'Comedy', 'Drama', 'Sci-Fi', 'Thriller', 'Romance', 'Animation', 'Documentary', 'Fantasy', 'Mystery', 'Reality', 'Crime', 'Sitcom', 'Anthology', 'Mini-Series'],
    book: ['Fiction', 'Non-Fiction', 'Sci-Fi', 'Fantasy', 'Mystery', 'Romance', 'Thriller', 'Biography', 'Self-Help', 'History', 'Horror', 'Poetry', 'Philosophy', 'Science', 'Business'],
    video_game: ['Action', 'Adventure', 'RPG', 'Strategy', 'Simulation', 'Sports', 'Puzzle', 'Horror', 'FPS', 'Racing', 'Fighting', 'Indie', 'Open World', 'Platformer', 'MMORPG'],
    podcast: ['True Crime', 'Comedy', 'News', 'Education', 'Technology', 'Business', 'Health', 'Science', 'History', 'Culture', 'Sports', 'Interview', 'Storytelling'],
    documentary: ['Nature', 'Science', 'History', 'True Crime', 'Technology', 'Social', 'Political', 'Music', 'Sports', 'Art', 'Space', 'Biography', 'Environment'],
    anime: ['Shonen', 'Shojo', 'Seinen', 'Isekai', 'Mecha', 'Slice of Life', 'Romance', 'Action', 'Horror', 'Comedy', 'Fantasy', 'Sci-Fi', 'Sports'],
    manga: ['Shonen', 'Shojo', 'Seinen', 'Josei', 'Isekai', 'Romance', 'Action', 'Horror', 'Comedy', 'Fantasy', 'Sci-Fi', 'Slice of Life'],
    music_album: ['Pop', 'Rock', 'Hip-Hop', 'R&B', 'Jazz', 'Classical', 'Electronic', 'Country', 'Metal', 'Indie', 'Folk', 'Latin', 'K-Pop'],
    audiobook: ['Fiction', 'Non-Fiction', 'Sci-Fi', 'Fantasy', 'Mystery', 'Romance', 'Thriller', 'Biography', 'Self-Help', 'History', 'Business', 'Science'],
}

const toIST = (dateStr?: string | null) => {
    if (!dateStr) return null
    return new Date(dateStr).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', dateStyle: 'medium', timeStyle: 'short' })
}

interface MediaForm {
    title: string
    media_type: MediaType
    status: MediaStatus
    author_creator: string
    genre: string
    release_year: string
    progress_current: string
    progress_total: string
    rating: string
    notes: string
    is_favorite: boolean
}

const emptyForm: MediaForm = {
    title: '', media_type: 'movie', status: 'to_watch', author_creator: '', genre: '',
    release_year: '', progress_current: '', progress_total: '', rating: '', notes: '',
    is_favorite: false,
}

function parseBulkData(text: string, filename: string): Array<Record<string, string>> {
    const ext = filename.split('.').pop()?.toLowerCase()
    if (ext === 'json') {
        const parsed = JSON.parse(text)
        const rows: unknown[] = Array.isArray(parsed) ? parsed : [parsed]
        return rows.map(row => {
            if (!row || typeof row !== 'object' || Array.isArray(row)) return {}
            return Object.fromEntries(
                Object.entries(row).map(([key, value]) => [key, value == null ? '' : String(value)])
            )
        })
    }
    const sep = ext === 'tsv' ? '\t' : ','
    const lines = text.trim().split('\n')
    if (lines.length < 2) return []
    const headers = lines[0].split(sep).map(h => h.trim().replace(/^["']|["']$/g, ''))
    return lines.slice(1).map(line => {
        const values = line.split(sep).map(v => v.trim().replace(/^["']|["']$/g, ''))
        const obj: Record<string, string> = {}
        headers.forEach((h, i) => { obj[h] = values[i] || '' })
        return obj
    })
}

export function MediaPage() {
    const [search, setSearch] = useState('')
    const [sort, setSort] = useState<SortOption>('title')
    const [filter, setFilter] = useState<MediaType | ''>('')
    const [statusFilter, setStatusFilter] = useState<MediaStatus | ''>('')
    const [showStats, setShowStats] = useState(false)
    const [showModal, setShowModal] = useState(false)
    const [showBulkModal, setShowBulkModal] = useState(false)
    const [editingId, setEditingId] = useState<number | null>(null)
    const [form, setForm] = useState<MediaForm>(emptyForm)
    const [showAdvanced, setShowAdvanced] = useState(false)
    const [bulkPreview, setBulkPreview] = useState<Array<Record<string, string>>>([])
    const [bulkError, setBulkError] = useState('')
    const fileInputRef = useRef<HTMLInputElement>(null)

    const { data: allMedia = [], isLoading, error: mediaError } = useMedia()
    const createMedia = useCreateMedia()
    const updateMedia = useUpdateMedia()
    const deleteMedia = useDeleteMedia()
    const bulkImport = useBulkImportMedia()

    const resetForm = () => { setForm(emptyForm); setEditingId(null); setShowAdvanced(false) }

    const openAddModal = () => { resetForm(); setShowModal(true) }

    const openEditModal = (item: MediaItem) => {
        setForm({
            title: item.title,
            media_type: item.media_type,
            status: item.status,
            author_creator: item.author_creator || '',
            genre: item.genre || '',
            release_year: item.release_year?.toString() || '',
            progress_current: item.progress_current?.toString() || '',
            progress_total: item.progress_total?.toString() || '',
            rating: item.rating?.toString() || '',
            notes: item.notes || '',
            is_favorite: item.is_favorite,
        })
        setEditingId(item.id)
        setShowModal(true)
    }

    const closeModal = () => { setShowModal(false); resetForm() }

    const handleSubmit = () => {
        if (!form.title.trim()) return
        const data: MediaCreateInput = {
            title: form.title,
            media_type: form.media_type,
            genre: form.genre || undefined,
            status: form.status,
            author_creator: form.author_creator || undefined,
            release_year: form.release_year ? parseInt(form.release_year) : undefined,
            notes: form.notes || undefined,
            progress_current: form.progress_current ? parseInt(form.progress_current) : undefined,
            progress_total: form.progress_total ? parseInt(form.progress_total) : undefined,
            is_favorite: form.is_favorite
        }

        if (editingId) {
            const update: MediaUpdateInput = {
                ...data,
                rating: form.rating ? parseInt(form.rating) : undefined,
            }
            updateMedia.mutate({ id: editingId, data: update }, { onSuccess: closeModal })
        } else {
            createMedia.mutate(data, { onSuccess: closeModal })
        }
    }

    const handleBulkFile = (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0]
        if (!file) return
        setBulkError('')
        const reader = new FileReader()
        reader.onload = (ev) => {
            try {
                const rows = parseBulkData(ev.target?.result as string, file.name)
                if (rows.length === 0) { setBulkError('No data rows found'); return }
                if (rows.length > 500) { setBulkError('Maximum 500 items per import'); return }
                setBulkPreview(rows)
            } catch {
                setBulkError('Failed to parse file. Ensure it is valid CSV, TSV, or JSON.')
            }
        }
        reader.readAsText(file)
    }

    const handleBulkImport = () => {
        const items: MediaCreateInput[] = []
        const invalidRows: number[] = []
        bulkPreview.forEach((row, index) => {
            const title = row.title || row.Title || ''
            if (!title) return
            const rawType = (row.media_type || row.type || row.Type || 'movie').toLowerCase().replace(/ /g, '_')
            const rawStatus = (row.status || row.Status || 'to_watch').toLowerCase().replace(/ /g, '_')
            if (!Object.prototype.hasOwnProperty.call(mediaTypeLabels, rawType)
                || !Object.prototype.hasOwnProperty.call(statusLabels, rawStatus)) {
                invalidRows.push(index + 1)
                return
            }
            items.push({
                title,
                media_type: rawType as MediaType,
                genre: row.genre || row.Genre || undefined,
                status: rawStatus as MediaStatus,
                author_creator: row.author_creator || row.author || row.Author || row.creator || undefined,
                release_year: row.release_year || row.year || row.Year ? parseInt(row.release_year || row.year || row.Year) : undefined,
                progress_current: row.progress_current ? parseInt(row.progress_current) : undefined,
                progress_total: row.progress_total ? parseInt(row.progress_total) : undefined,
                is_favorite: row.is_favorite === 'true' || row.is_favorite === '1',
            })
        })

        if (items.length === 0) { setBulkError('No valid items found'); return }
        if (invalidRows.length > 0) {
            setBulkError(`Invalid media type or status in row${invalidRows.length === 1 ? '' : 's'} ${invalidRows.join(', ')}`)
            return
        }
        bulkImport.mutate(items, {
            onSuccess: () => { setShowBulkModal(false); setBulkPreview([]); setBulkError('') },
            onError: (error: Error) => setBulkError(error.message || 'Import failed')
        })
    }

    // Filtering + sorting
    const q = search.trim().toLowerCase()
    const filtered = allMedia
        .filter(m => {
            if (filter && m.media_type !== filter) return false
            if (statusFilter && m.status !== statusFilter) return false
            if (q && !m.title.toLowerCase().includes(q) && !(m.author_creator || '').toLowerCase().includes(q)) return false
            return true
        })
        .sort((a, b) => {
            if (sort === 'rating') return (b.rating ?? -1) - (a.rating ?? -1)
            if (sort === 'year') return (b.release_year ?? 0) - (a.release_year ?? 0)
            return a.title.localeCompare(b.title)
        })

    // Stats
    const stats = {
        total: allMedia.length,
        watching: allMedia.filter(m => m.status === 'watching').length,
        completed: allMedia.filter(m => m.status === 'completed').length,
        planned: allMedia.filter(m => m.status === 'to_watch' || m.status === 'plan_to_watch').length
    }

    const byType = Object.entries(mediaTypeLabels).map(([type]) => ({
        type: type as MediaType,
        count: allMedia.filter(m => m.media_type === type).length
    })).filter(t => t.count > 0)

    const progressInfo = progressLabels[form.media_type] || progressLabels.movie
    const genreOptions = genresByMediaType[form.media_type] || []

    if (mediaError) return <QueryErrorState message="Could not load media." error={mediaError} />

    return (
        <div className="page">
            <div className="page-tabs" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div>
                    <h2 style={{ margin: 0 }}>Media Tracker</h2>
                    <div className="empty-text" style={{ marginTop: 2 }}>{allMedia.length} items</div>
                </div>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                    <ModuleExportButton module="media" />
                    <button className="tab-btn secondary" onClick={() => setShowStats(v => !v)}>
                        <Icon name="stats" size={16} /> {showStats ? 'Hide Stats' : 'Stats'}
                    </button>
                </div>
            </div>

            {showStats && (
                <div className="content-card">
                    <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
                        <div><strong>{stats.total}</strong> <span className="item-meta">total</span></div>
                        <div><strong>{stats.watching}</strong> <span className="item-meta">in progress</span></div>
                        <div><strong>{stats.completed}</strong> <span className="item-meta">completed</span></div>
                        <div><strong>{stats.planned}</strong> <span className="item-meta">planned</span></div>
                    </div>
                    {byType.length > 0 && (
                        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginTop: 12, paddingTop: 12, borderTop: '1px solid var(--border)' }}>
                            {byType.map(t => (
                                <span key={t.type} className="icon-text" style={{ fontSize: 13 }}>
                                    <Icon name={mediaIcons[t.type]} size={14} /> {mediaTypeLabels[t.type]}: {t.count}
                                </span>
                            ))}
                        </div>
                    )}
                </div>
            )}

            <div className="content-card">
                <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between' }}>
                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', flex: 1 }}>
                        <input
                            className="form-input"
                            placeholder="Search media..."
                            value={search}
                            onChange={e => setSearch(e.target.value)}
                            style={{ width: 'auto', minWidth: 200, flex: '1 1 200px' }}
                        />
                        <select className="form-input" value={filter} onChange={e => setFilter(e.target.value as MediaType | '')} style={{ width: 'auto' }}>
                            <option value="">All Types</option>
                            {Object.entries(mediaTypeLabels).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                        </select>
                        <select className="form-input" value={statusFilter} onChange={e => setStatusFilter(e.target.value as MediaStatus | '')} style={{ width: 'auto' }}>
                            <option value="">All Status</option>
                            {Object.entries(statusLabels).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                        </select>
                        <select className="form-input" value={sort} onChange={e => setSort(e.target.value as SortOption)} style={{ width: 'auto' }}>
                            <option value="title">Sort: Title</option>
                            <option value="year">Sort: Release Year</option>
                            <option value="rating">Sort: Rating</option>
                        </select>
                    </div>
                    <div style={{ display: 'flex', gap: 8 }}>
                        <button className="btn btn-primary toolbar-action" onClick={openAddModal}><Icon name="add" size={16} /> Add Media</button>
                        <button className="tab-btn secondary" onClick={() => { setShowBulkModal(true); setBulkPreview([]); setBulkError('') }}><Icon name="import" size={16} /> Import</button>
                    </div>
                </div>

                {isLoading ? <div className="empty-state"><div className="empty-text">Loading...</div></div> :
                    filtered.length === 0 ? (
                        <div className="empty-state">
                            <div className="empty-icon"><Icon name="tv_show" size={48} /></div>
                            <div className="empty-title">No media found</div>
                            <div className="empty-text">Start building your media library!</div>
                        </div>
                    ) : (
                        <ul className="item-list">
                            {filtered.map((item: MediaItem) => {
                                    const pInfo = progressLabels[item.media_type] || progressLabels.movie
                                    const hasProg = item.progress_current != null && item.progress_total != null && item.progress_total > 0
                                    return (
                                        <li key={item.id} className="item-row" style={{ alignItems: 'flex-start' }}>
                                            <span style={{ marginRight: 12, color: 'var(--text-secondary)', display: 'inline-flex' }}>
                                                <Icon name={mediaIcons[item.media_type as MediaType] ?? 'package'} size={24} />
                                            </span>
                                            <div className="item-info" style={{ flex: 1 }}>
                                                <strong>{item.title}</strong>
                                                <span className="item-meta">
                                                    {mediaTypeLabels[item.media_type as MediaType] || item.media_type}
                                                    {item.release_year && ` (${item.release_year})`}
                                                    {item.author_creator && ` • ${item.author_creator}`}
                                                    {item.genre && ` • ${item.genre}`}
                                                </span>
                                                {hasProg && (
                                                    <span className="item-meta">
                                                        {item.progress_current}/{item.progress_total} {pInfo.unit}
                                                        {' '}({Math.round((item.progress_current! / item.progress_total!) * 100)}%)
                                                    </span>
                                                )}
                                                {item.completion_date && <span className="item-meta">Completed: {toIST(item.completion_date)}</span>}
                                            </div>
                                            <span className={`status-badge ${item.status}`}>{statusLabels[item.status]}</span>
                                            <button className="item-action" onClick={() => openEditModal(item)} title="Edit" aria-label="Edit item"><Icon name="edit" size={16} /></button>
                                            <button onClick={() => { if (window.confirm(`Delete "${item.title}"?`)) deleteMedia.mutate(item.id) }} title="Delete" style={{ padding: '4px 8px', background: 'transparent', border: '1px solid var(--border)', borderRadius: 6, cursor: 'pointer', opacity: 0.6, fontSize: 13, marginLeft: 4, transition: 'opacity 0.2s' }} onMouseEnter={e => (e.currentTarget.style.opacity = '1')} onMouseLeave={e => (e.currentTarget.style.opacity = '0.6')} aria-label={`Delete ${item.title}`}><Icon name="delete" size={16} label={`Delete ${item.title}`} /></button>
                                        </li>
                                    )
                                })}
                            </ul>
                        )}
            </div>

            {/* Add/Edit Modal */}
            {showModal && (
                <div className="modal-overlay" onClick={closeModal}>
                    <div className="modal-content media-modal" onClick={e => e.stopPropagation()} style={{ maxWidth: 500, maxHeight: '90vh', overflow: 'auto' }}>
                        <h3>{editingId ? 'Edit Media' : 'Add New Media'}</h3>

                        <label className="form-label">Title *</label>
                        <input className="form-input" placeholder="Title" value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} autoFocus />

                        <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
                            <div style={{ flex: 1 }}>
                                <label className="form-label">Type</label>
                                <select className="form-input" value={form.media_type} onChange={e => setForm({ ...form, media_type: e.target.value as MediaType, genre: '' })}>
                                    {Object.entries(mediaTypeLabels).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                                </select>
                            </div>
                            <div style={{ flex: 1 }}>
                                <label className="form-label">Status</label>
                                <select className="form-input" value={form.status} onChange={e => setForm({ ...form, status: e.target.value as MediaStatus })}>
                                    {Object.entries(statusLabels).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                                </select>
                            </div>
                        </div>

                        <label className="form-label" style={{ marginTop: 12 }}>Author/Creator/Director</label>
                        <input className="form-input" placeholder="Creator name" value={form.author_creator} onChange={e => setForm({ ...form, author_creator: e.target.value })} />

                        <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
                            <div style={{ flex: 1 }}>
                                <label className="form-label">Genre</label>
                                <select className="form-input" value={form.genre} onChange={e => setForm({ ...form, genre: e.target.value })}>
                                    <option value="">Select genre</option>
                                    {genreOptions.map(g => <option key={g} value={g}>{g}</option>)}
                                </select>
                            </div>
                            <div style={{ flex: 1 }}>
                                <label className="form-label">Year</label>
                                <input className="form-input" type="number" min="1000" max="9999" placeholder="2024" value={form.release_year} onChange={e => setForm({ ...form, release_year: e.target.value })} />
                            </div>
                        </div>

                        {/* Progress tracking with type-specific hints */}
                        <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
                            <div style={{ flex: 1 }}>
                                <label className="form-label">{progressInfo.current}</label>
                                <input className="form-input" type="number" min="0" placeholder={`e.g. 5 ${progressInfo.unit}`} value={form.progress_current} onChange={e => setForm({ ...form, progress_current: e.target.value })} />
                            </div>
                            <div style={{ flex: 1 }}>
                                <label className="form-label">{progressInfo.total}</label>
                                <input className="form-input" type="number" min="0" placeholder={`e.g. 120 ${progressInfo.unit}`} value={form.progress_total} onChange={e => setForm({ ...form, progress_total: e.target.value })} />
                            </div>
                        </div>

                        <button className="btn btn-sm media-options-toggle" style={{ marginTop: 12 }} onClick={() => setShowAdvanced(!showAdvanced)}>
                            <span className="icon-text">
                                <Icon name={showAdvanced ? 'up' : 'down'} size={16} />
                                {showAdvanced ? 'Less Options' : 'More Options'}
                            </span>
                        </button>

                        {showAdvanced && (
                            <>
                                {editingId !== null && (
                                    <div style={{ marginTop: 12 }}>
                                        <label className="form-label">Rating (1-10)</label>
                                        <input className="form-input" type="number" min="1" max="10" placeholder="8" value={form.rating} onChange={e => setForm({ ...form, rating: e.target.value })} />
                                    </div>
                                )}

                                <label className="form-label" style={{ marginTop: 12 }}>Notes</label>
                                <textarea className="form-input" placeholder="Notes..." value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} style={{ minHeight: 60 }} />

                                <div style={{ marginTop: 12 }}>
                                    <button
                                        type="button"
                                        className={form.is_favorite ? 'favorite-toggle active' : 'favorite-toggle'}
                                        onClick={() => setForm({ ...form, is_favorite: !form.is_favorite })}
                                        aria-pressed={form.is_favorite}
                                    >
                                        <Icon name="favorite" size={17} />
                                        {form.is_favorite ? 'Favorited' : 'Add to favorites'}
                                    </button>
                                </div>
                            </>
                        )}

                        <div className="modal-actions">
                            <button className="btn btn-primary" onClick={handleSubmit} disabled={createMedia.isPending || updateMedia.isPending}>
                                {(createMedia.isPending || updateMedia.isPending) ? 'Saving...' : (editingId ? 'Update Media' : 'Add Media')}
                            </button>
                            <button className="btn" onClick={closeModal}>Cancel</button>
                        </div>
                    </div>
                </div>
            )}

            {/* Bulk Import Modal */}
            {showBulkModal && (
                <div className="modal-overlay" onClick={() => setShowBulkModal(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 600, maxHeight: '90vh', overflow: 'auto' }}>
                        <h3 className="icon-text"><Icon name="import" size={20} /> Bulk Import Media</h3>
                        <p style={{ color: 'var(--text-secondary)', marginBottom: 16, fontSize: 14 }}>
                            Upload a CSV, TSV, or JSON file. Expected columns: <strong>title</strong>, media_type, genre, status, author_creator, release_year, progress_current, progress_total, is_favorite
                        </p>

                        <input
                            ref={fileInputRef}
                            type="file"
                            accept=".csv,.tsv,.json"
                            onChange={handleBulkFile}
                            style={{ marginBottom: 16 }}
                        />

                        {bulkError && <p style={{ color: '#ef4444', marginBottom: 12 }}>{bulkError}</p>}

                        {bulkPreview.length > 0 && (
                            <>
                                <p style={{ marginBottom: 8 }}><strong>{bulkPreview.length}</strong> items found. Preview:</p>
                                <div style={{ maxHeight: 300, overflow: 'auto', border: '1px solid var(--border)', borderRadius: 8, marginBottom: 16 }}>
                                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                                        <thead>
                                            <tr style={{ background: 'var(--bg-secondary)' }}>
                                                <th style={{ padding: '6px 8px', textAlign: 'left' }}>Title</th>
                                                <th style={{ padding: '6px 8px', textAlign: 'left' }}>Type</th>
                                                <th style={{ padding: '6px 8px', textAlign: 'left' }}>Genre</th>
                                                <th style={{ padding: '6px 8px', textAlign: 'left' }}>Status</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {bulkPreview.slice(0, 10).map((row, i) => (
                                                <tr key={i} style={{ borderTop: '1px solid var(--border)' }}>
                                                    <td style={{ padding: '6px 8px' }}>{row.title || row.Title || '—'}</td>
                                                    <td style={{ padding: '6px 8px' }}>{row.media_type || row.type || row.Type || '—'}</td>
                                                    <td style={{ padding: '6px 8px' }}>{row.genre || row.Genre || '—'}</td>
                                                    <td style={{ padding: '6px 8px' }}>{row.status || row.Status || '—'}</td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                    {bulkPreview.length > 10 && <p style={{ padding: 8, color: 'var(--text-secondary)', fontSize: 13 }}>...and {bulkPreview.length - 10} more</p>}
                                </div>
                            </>
                        )}

                        <div className="modal-actions">
                            <button className="btn btn-primary" onClick={handleBulkImport} disabled={bulkImport.isPending || bulkPreview.length === 0}>
                                {bulkImport.isPending ? 'Importing...' : `Import ${bulkPreview.length} Items`}
                            </button>
                            <button className="btn" onClick={() => setShowBulkModal(false)}>Cancel</button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}
