import { authHeaders, formatApiError } from './client'

const BACKUP_BASE_URL = '/api/backups'

export type BackupModule = 'tasks' | 'medications' | 'gym' | 'kitchen' | 'media' | 'ai' | 'all'

export interface RestorePreview {
  module: BackupModule
  exported_at: string | null
  row_counts: Record<string, number>
  total_rows: number
}

async function backupRequest<T>(path: string, body?: string): Promise<T> {
  const response = await fetch(`${BACKUP_BASE_URL}${path}`, {
    method: body === undefined ? 'GET' : 'POST',
    headers: {
      ...authHeaders(),
      ...(body === undefined ? {} : {
      'Content-Type': 'application/json',
      }),
    },
    body,
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({}))
    throw new Error(formatApiError(error.detail || error.error, `HTTP ${response.status}`))
  }
  return response.json() as Promise<T>
}

export async function downloadBackup(module: BackupModule): Promise<void> {
  const response = await fetch(`${BACKUP_BASE_URL}/export/${module}`, { headers: authHeaders() })
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  const filename = response.headers.get('Content-Disposition')?.match(/filename="([^"]+)"/)?.[1]
    ?? `omniflow-${module}-backup.json`
  const url = URL.createObjectURL(await response.blob())
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

// Keep the uploaded snapshot as raw JSON. Re-parsing and re-serializing it in
// JavaScript could round exact inventory quantities before PostgreSQL sees it.
const restoreBody = (snapshotJson: string) => `{"snapshot":${snapshotJson}}`

export function previewBackupRestore(snapshotJson: string): Promise<RestorePreview> {
  return backupRequest<RestorePreview>('/restore/preview', restoreBody(snapshotJson))
}

export function restoreBackup(snapshotJson: string): Promise<RestorePreview & { status: 'restored' }> {
  return backupRequest<RestorePreview & { status: 'restored' }>('/restore', restoreBody(snapshotJson))
}
