import { useEffect, useState } from 'react'
import { api } from '../api/client'

type Event = { id: string; created_at: string; actor: string; source: string; action: string; entity_table: string; entity_id: string | null; label: string | null }

export function ActivityPage() {
  const [events, setEvents] = useState<Event[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [more, setMore] = useState(false)
  async function load(before?: string, before_id?: string) {
    setLoading(true); setError('')
    try {
      const rows = await api.get<Event[]>('/activity', { limit: 100, before, before_id })
      setEvents(previous => before ? [...previous, ...rows] : rows)
      setMore(rows.length === 100)
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to load activity.') }
    finally { setLoading(false) }
  }
  useEffect(() => { void load() }, [])
  return <section className="activity-page">
    <h1>Recent activity</h1>
    <p>Changes from the last seven days. AI changes were approved by the operator.</p>
    <button className="btn" disabled={loading} onClick={() => void load()}>Refresh</button>
    {error && <p role="alert">{error}</p>}
    {loading && <p role="status">Loading activity…</p>}
    {!loading && !error && events.length === 0 && <p>No recent changes.</p>}
    <div className="activity-table-wrap"><table><thead><tr><th scope="col">When</th><th scope="col">Who</th><th scope="col">Source</th><th scope="col">Action</th><th scope="col">Record</th></tr></thead>
      <tbody>{events.map(event => <tr key={event.id}>
        <td><time dateTime={event.created_at}>{new Date(event.created_at).toLocaleString()}</time></td>
        <td>{event.actor}</td><td>{event.source === 'ai' ? 'AI approved' : event.source === 'restore' ? 'Backup restore' : 'Manual'}</td>
        <td>{event.action}</td><td>{event.label || event.entity_id || 'Record'} — {event.entity_table}{event.entity_id && ` #${event.entity_id}`}</td>
      </tr>)}</tbody></table></div>
    {more && <button className="btn" disabled={loading} onClick={() => void load(events[events.length - 1].created_at, events[events.length - 1].id)}>Load older changes</button>}
  </section>
}
