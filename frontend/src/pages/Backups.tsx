import { useState, type ChangeEvent } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { downloadBackup, previewBackupRestore, restoreBackup, type BackupModule, type RestorePreview } from '../api/backups'
import { Icon } from '../components/Icon'

const modules: { module: BackupModule; label: string; description: string }[] = [
  { module: 'tasks', label: 'Tasks', description: 'Tasks and completion history' },
  { module: 'medications', label: 'Medication', description: 'Catalog, plans, schedules, and dose history' },
  { module: 'gym', label: 'Gym', description: 'Exercise library, templates, and workout history' },
  { module: 'kitchen', label: 'Kitchen', description: 'Ingredients, recipes, inventory, and meals' },
  { module: 'media', label: 'Media', description: 'Your media library and progress' },
  { module: 'ai', label: 'AI history', description: 'Recorded assistant actions and their audit history' },
]

export function BackupsPage() {
  const [downloading, setDownloading] = useState<BackupModule | null>(null)
  const [snapshotJson, setSnapshotJson] = useState('')
  const [preview, setPreview] = useState<RestorePreview | null>(null)
  const [error, setError] = useState('')
  const [restoring, setRestoring] = useState(false)
  const [restored, setRestored] = useState('')
  const queryClient = useQueryClient()
  const download = async (module: BackupModule) => {
    setError(''); setDownloading(module)
    try { await downloadBackup(module) } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not create backup')
    } finally { setDownloading(null) }
  }
  const selectRestoreFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    setPreview(null); setRestored(''); setError(''); setSnapshotJson('')
    if (!file) return
    try {
      const rawSnapshot = await file.text()
      setPreview(await previewBackupRestore(rawSnapshot))
      setSnapshotJson(rawSnapshot)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'This file could not be checked') }
    event.target.value = ''
  }
  const restore = async () => {
    if (!preview || !snapshotJson || !window.confirm(`Replace all current ${preview.module} data with this backup? This cannot be undone.`)) return
    setError(''); setRestoring(true)
    try {
      const result = await restoreBackup(snapshotJson)
      await queryClient.invalidateQueries()
      setRestored(`${result.total_rows} rows restored to ${result.module}.`)
      setSnapshotJson(''); setPreview(null)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Restore could not be completed') }
    finally { setRestoring(false) }
  }
  return <div className="page backups-page">
    <div className="page-tabs" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
      <div><h2 style={{ margin: 0 }}>Backups</h2><div className="empty-text" style={{ marginTop: 2 }}>Download only the part of Omniflow you need.</div></div>
      <button className="tab-btn secondary" onClick={() => download('all')} disabled={downloading !== null}><Icon name="download" size={16} /> {downloading === 'all' ? 'Preparing...' : 'Export all'}</button>
    </div>
    <section className="content-card" aria-labelledby="module-backups-title">
      <h3 id="module-backups-title">Module backups</h3>
      <div className="backup-module-list">
        {modules.map(({ module, label, description }) => <div className="backup-module-row" key={module}>
          <div><strong>{label}</strong><span>{description}</span></div>
          <button className="tab-btn secondary" onClick={() => download(module)} disabled={downloading !== null}><Icon name="download" size={16} /> {downloading === module ? 'Preparing...' : 'Export'}</button>
        </div>)}
      </div>
    </section>
    <section className="content-card" aria-labelledby="restore-title">
      <h3 id="restore-title">Restore a backup</h3>
      <div className="backup-restore-step">
        <label className="btn" htmlFor="backup-file"><Icon name="upload" size={16} /> Choose backup file</label>
        <input id="backup-file" className="backup-file-input" type="file" accept="application/json,.json" onChange={selectRestoreFile} />
        <span>Step 1: check the file before anything is changed.</span>
      </div>
      {preview && <div className="backup-preview" role="status"><strong>{preview.module} backup checked</strong><span>{preview.total_rows} rows across {Object.keys(preview.row_counts).length} tables.</span><button className="btn btn-primary" onClick={restore} disabled={restoring}><Icon name="upload" size={16} /> {restoring ? 'Restoring...' : `Step 2: Replace ${preview.module} data`}</button></div>}
      {error && <p className="backup-message backup-error" role="alert">{error}</p>}
      {restored && <p className="backup-message backup-success" role="status">{restored}</p>}
    </section>
  </div>
}
