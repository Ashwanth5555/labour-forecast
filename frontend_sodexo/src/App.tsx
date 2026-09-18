import { useEffect, useState } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import Overview from './pages/Overview'
import LaborForecasting from './pages/LaborForecasting'
import LaborAnalytics from './pages/LaborAnalytics'
import TimePunchAnalytics from './pages/TimePunchAnalytics'
import AIRecommendations from './pages/AIRecommendations'
import AIAssistant from './pages/AIAssistant'
import DataQuality from './pages/DataQuality'
import Login from './pages/Login'
import { fetchCurrentUser } from './services/api'
import { type AuthUser, getStoredUser, getToken, onSessionEnded } from './services/session'

export default function App() {
  const [user, setUser] = useState<AuthUser | null>(getStoredUser)
  // Only blocks while there is a stored token worth validating; a first-time
  // visitor goes straight to the login form with no flash of a loading state.
  const [validating, setValidating] = useState(() => !!getToken())

  useEffect(() => {
    if (!getToken()) return
    // The token outlives a page reload, so confirm the server still accepts it
    // before rendering the app. Otherwise an expired session lands on a
    // dashboard that fails every request instead of on the login screen.
    fetchCurrentUser()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setValidating(false))
  }, [])

  // Covers both Sign out and a 401 from any request in the app.
  useEffect(() => onSessionEnded(() => setUser(null)), [])

  if (validating) {
    return (
      <div className="flex min-h-screen w-screen items-center justify-center bg-[var(--color-surface-2)] text-sm text-[var(--color-text-muted)]">
        <span className="animate-pulse">Restoring your session…</span>
      </div>
    )
  }

  if (!user) return <Login onSignedIn={setUser} />

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Overview />} />
        <Route path="/labor-analytics" element={<LaborAnalytics />} />
        <Route path="/time-punch-analytics" element={<TimePunchAnalytics />} />
        <Route path="/labor-forecasting" element={<Navigate to="/labor-forecasting/model-training" replace />} />
        <Route path="/labor-forecasting/:section" element={<LaborForecasting />} />
        <Route path="/ai-recommendations" element={<AIRecommendations />} />
        <Route path="/ai-assistant" element={<AIAssistant />} />
        <Route path="/model-performance" element={<Navigate to="/labor-forecasting/model-performance" replace />} />
        <Route path="/data-quality" element={<DataQuality />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
