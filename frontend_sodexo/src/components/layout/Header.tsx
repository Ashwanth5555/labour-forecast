import { useState } from 'react'
import { LogOut } from 'lucide-react'
import { signOut } from '../../services/api'
import { getStoredUser } from '../../services/session'

const ROLE_LABELS: Record<string, string> = {
  ADMIN: 'Administrator',
  LOCATION_MANAGER: 'Location Manager',
  DATA_ANALYST: 'Data Analyst',
}

/** Read from storage rather than passed down: the signed-in user cannot change
 *  during a session, so every page would otherwise have to thread it through
 *  PageContainer just to reach this header. */
function UserMenu() {
  const user = getStoredUser()
  const [signingOut, setSigningOut] = useState(false)
  if (!user) return null

  return (
    <div className="flex items-center gap-3">
      <div className="hidden text-right sm:block">
        <div className="text-xs font-medium leading-tight text-[var(--color-text)]">{user.full_name}</div>
        <div className="text-[10px] leading-tight text-[var(--color-text-muted)]">
          {ROLE_LABELS[user.role] ?? user.role}
        </div>
      </div>
      <div
        aria-hidden
        className="flex h-8 w-8 items-center justify-center rounded-full bg-[var(--color-primary)]/10 text-[11px] font-semibold text-[var(--color-primary)]"
      >
        {user.full_name
          .split(' ')
          .map((part) => part[0])
          .slice(0, 2)
          .join('')
          .toUpperCase()}
      </div>
      <button
        onClick={() => {
          setSigningOut(true)
          // No re-enable on failure: signOut clears the session either way, so
          // the app is already on its way back to the login screen.
          void signOut()
        }}
        disabled={signingOut}
        title="Sign out"
        className="flex items-center gap-1.5 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] px-2.5 py-1.5 text-xs text-[var(--color-text-muted)] transition-colors hover:border-[var(--color-primary)] hover:text-[var(--color-text)] disabled:opacity-50"
      >
        <LogOut size={13} />
        <span className="hidden sm:inline">{signingOut ? 'Signing out…' : 'Sign out'}</span>
      </button>
    </div>
  )
}

export function Header({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <header className="flex items-center justify-between gap-4 border-b border-[var(--color-border)] bg-[var(--color-surface)] px-6 py-4 shadow-[var(--shadow-sm)]">
      <div>
        <h1 className="text-lg font-semibold tracking-tight text-[var(--color-text)]">{title}</h1>
        {subtitle && <p className="text-xs text-[var(--color-text-muted)]">{subtitle}</p>}
      </div>
      <UserMenu />
    </header>
  )
}
