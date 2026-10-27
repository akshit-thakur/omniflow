import { Routes, Route, Link, useLocation } from 'react-router-dom'
import { useEffect, useState } from 'react'
import './App.css'
import { TasksPage } from './pages/Tasks'
import { DashboardPage } from './pages/Dashboard'
import { CookbookPage } from './pages/Cookbook'
import { InventoryPage } from './pages/Inventory'
import { MealsPage } from './pages/Meals'
import { GymPage } from './pages/Gym'
import { MediaPage } from './pages/Media'
import { MedicinePage } from './pages/Medicine'
import { DatabaseMapPage } from './pages/DatabaseMap'
import { BackupsPage } from './pages/Backups'
import { ActivityPage } from './pages/Activity'
import { ChatBubble } from './components/ChatBubble'
import { api, storeAuth } from './api/client'

// Page titles mapping
const pageTitles: Record<string, string> = {
  '/': '',
  '/tasks': 'To-Do List',
  '/cookbook': 'Cookbook',
  '/inventory': 'Kitchen Inventory',
  '/meals': 'Meal Planner',
  '/gym': 'Gym Training',
  '/media': 'Media Tracker',
  '/medicine': 'Medicine Tracker',
  '/database-map': 'Database Map',
  '/backups': 'Backups',
  '/activity': 'Recent activity',
}

function App() {
  const location = useLocation()
  const [notifOpen, setNotifOpen] = useState(false)
  const [authenticated, setAuthenticated] = useState<boolean | null>(null)
  const [password, setPassword] = useState('')
  const [loginError, setLoginError] = useState('')
  const [setupRequired, setSetupRequired] = useState(false)
  const [confirmation, setConfirmation] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    void api.get<{ setup_required: boolean; demo: boolean }>('/auth/status').then(status => {
      setSetupRequired(status.setup_required)
      if (status.demo) { setAuthenticated(true); return }
      return api.get('/auth/session').then(() => setAuthenticated(true)).catch(() => setAuthenticated(false))
    }).catch(() => { setLoginError('Unable to reach Omniflow. Reload to retry.'); setAuthenticated(false) })
  }, [])

  if (authenticated !== true) {
    return (
      <main className="main-content" style={{ maxWidth: 420, margin: '20vh auto' }}>
        <h1>{setupRequired ? 'Welcome to Omniflow' : 'Sign in to Omniflow'}</h1>
        <p>{setupRequired ? 'Create your password to finish setup. It stays with this installation across updates.' : 'Enter your password.'}</p>
        <form onSubmit={(event) => {
          event.preventDefault()
          setLoginError('')
          if (setupRequired && password !== confirmation) { setLoginError('Passwords do not match.'); return }
          setBusy(true)
          void api.post<{ access_token: string; csrf_token: string }>(setupRequired ? '/auth/setup' : '/auth/login', { password }).then(result => { storeAuth(result.access_token, result.csrf_token); setPassword(''); setConfirmation(''); setAuthenticated(true) }).catch(error => setLoginError(error instanceof Error ? error.message : 'Unable to sign in.')).finally(() => setBusy(false))
        }}>
          <label className="form-label" htmlFor="operator-password">Password{setupRequired ? ' (at least 16 characters)' : ''}</label>
          <input id="operator-password" className="form-input" type="password" value={password} onChange={event => setPassword(event.target.value)} autoComplete={setupRequired ? 'new-password' : 'current-password'} minLength={setupRequired ? 16 : 1} maxLength={512} required />
          {setupRequired && <><label className="form-label" htmlFor="confirm-password">Confirm password</label><input id="confirm-password" className="form-input" type="password" value={confirmation} onChange={event => setConfirmation(event.target.value)} autoComplete="new-password" required /></>}
          <button className="btn btn-primary" type="submit" disabled={busy || authenticated === null}>{busy ? 'Please wait…' : setupRequired ? 'Create password' : 'Sign in'}</button>
          {loginError && <p role="alert">{loginError}</p>}
        </form>
      </main>
    )
  }

  const pageTitle = pageTitles[location.pathname] || ''

  return (
    <div className="app">
      {/* Skip to content link */}
      <a href="#main-content" className="skip-link">
        Skip to main content
      </a>

      {/* Header with gradient */}
      <header className="header">
        <Link to="/" className="header-brand">
          Omniflow{pageTitle && <span className="header-separator"> | {pageTitle}</span>}
        </Link>
        <div className="header-actions">
          <Link to="/activity">Recent activity</Link>
          <button
            className="notifications-link"
            onClick={() => setNotifOpen(!notifOpen)}
            aria-expanded={notifOpen}
          >
            Notifications
          </button>
          {notifOpen && (
            <div className="notification-dropdown" role="menu">
              <div className="notif-item">No notifications</div>
            </div>
          )}
        </div>
      </header>

      {/* Main content */}
      <main id="main-content" className="main-content" role="main">
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/tasks" element={<TasksPage />} />
          <Route path="/cookbook" element={<CookbookPage />} />
          <Route path="/inventory" element={<InventoryPage />} />
          <Route path="/meals" element={<MealsPage />} />
          <Route path="/gym" element={<GymPage />} />
          <Route path="/media" element={<MediaPage />} />
          <Route path="/medicine" element={<MedicinePage />} />
          <Route path="/database-map" element={<DatabaseMapPage />} />
          <Route path="/backups" element={<BackupsPage />} />
          <Route path="/activity" element={<ActivityPage />} />
        </Routes>
      </main>

      {/* Footer */}
      <footer className="footer">
        © Omniflow - Private, Local, Yours
      </footer>

      {/* Floating AI Chat Bubble */}
      <ChatBubble />
    </div>
  )
}

export default App
