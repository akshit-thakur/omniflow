import { useState } from 'react'
import { downloadBackup, type BackupModule } from '../api/backups'
import { Icon } from './Icon'

const moduleLabels: Record<BackupModule, string> = {
  tasks: 'Tasks', medications: 'Medication', gym: 'Gym', kitchen: 'Kitchen', media: 'Media', ai: 'AI history', all: 'All data',
}

export function ModuleExportButton({ module }: { module: BackupModule }) {
  const [error, setError] = useState('')
  const [downloading, setDownloading] = useState(false)
  const download = async () => {
    setError('')
    setDownloading(true)
    try { await downloadBackup(module) } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not create backup')
    } finally { setDownloading(false) }
  }
  return <span className="backup-export-control">
    <button className="tab-btn secondary" onClick={download} disabled={downloading}>
      <Icon name="download" size={16} /> {downloading ? 'Preparing...' : `Export ${moduleLabels[module]}`}
    </button>
    {error && <span className="backup-inline-error" role="alert">{error}</span>}
  </span>
}
