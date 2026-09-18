import { useState } from 'react'
import { Loader2, Lock, LogIn, User } from 'lucide-react'
import logo from '../assets/sodexo-logo.png'
import { signIn } from '../services/api'
import type { AuthUser } from '../services/session'

export default function Login({ onSignedIn }: { onSignedIn: (user: AuthUser) => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (submitting || !username.trim() || !password) return
    setSubmitting(true)
    setError(null)
    try {
      onSignedIn(await signIn(username.trim(), password))
    } catch (err: any) {
      // The API deliberately returns the same message for an unknown username
      // and a wrong password, so this is shown as-is rather than guessing at
      // which field was wrong.
      setError(err?.response?.data?.detail ?? 'Unable to sign in. Is the backend running?')
      setPassword('')
      setSubmitting(false)
    }
  }

  const fieldClass =
    'w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] py-2 pl-9 pr-3 text-sm ' +
    'text-[var(--color-text)] outline-none placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-primary)]'

  return (
    <div className="flex min-h-screen w-screen items-center justify-center bg-[var(--color-surface-2)] p-6">
      <div className="w-full max-w-sm">
        <div className="mb-5 flex flex-col items-center gap-3 text-center">
          <img src={logo} alt="Sodexo" className="h-9 object-contain" />
          <div>
            <h1 className="text-base font-semibold tracking-tight text-[var(--color-text)]">
              Workforce Forecasting
            </h1>
            <p className="mt-0.5 text-xs text-[var(--color-text-muted)]">
              Sign in to continue to the dashboard
            </p>
          </div>
        </div>

        <form
          onSubmit={submit}
          className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5 shadow-[var(--shadow-sm)]"
        >
          <label className="mb-3 block">
            <span className="mb-1 block text-[11px] font-medium text-[var(--color-text-muted)]">Username</span>
            <span className="relative block">
              <User size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-text-muted)]" />
              <input
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoFocus
                autoComplete="username"
                spellCheck={false}
                placeholder="Enter your username"
                className={fieldClass}
              />
            </span>
          </label>

          <label className="block">
            <span className="mb-1 block text-[11px] font-medium text-[var(--color-text-muted)]">Password</span>
            <span className="relative block">
              <Lock size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-text-muted)]" />
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                placeholder="Enter your password"
                className={fieldClass}
              />
            </span>
          </label>

          {error && (
            <div
              role="alert"
              className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[11px] text-red-700"
            >
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={submitting || !username.trim() || !password}
            className="mt-4 flex w-full items-center justify-center gap-2 rounded-lg bg-[var(--color-primary)] py-2 text-sm font-medium text-white transition-colors hover:bg-[var(--color-primary-dark)] disabled:opacity-40"
          >
            {submitting ? <Loader2 size={14} className="animate-spin" /> : <LogIn size={14} />}
            {submitting ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        <p className="mt-4 text-center text-[10px] text-[var(--color-text-muted)]">
          Your session ends when you close this tab or sign out.
        </p>
      </div>
    </div>
  )
}
