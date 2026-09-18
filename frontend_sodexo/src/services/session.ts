/** Where the signed-in session lives on the client.
 *
 *  `sessionStorage`, not `localStorage`: the token is dropped when the browser
 *  tab closes, so opening the app again asks for a sign-in. Switch these two
 *  reads to `localStorage` if you would rather a session survive until the
 *  token expires.
 *
 *  Every access is wrapped: a browser set to block site data throws on the
 *  accessor itself, and a login screen that crashes is worse than one that
 *  simply asks again.
 */
const TOKEN_KEY = 'sodexo.auth.token'
const USER_KEY = 'sodexo.auth.user'

export interface AuthUser {
  username: string
  full_name: string
  role: string
}

export function getToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function getStoredUser(): AuthUser | null {
  try {
    const raw = sessionStorage.getItem(USER_KEY)
    return raw ? (JSON.parse(raw) as AuthUser) : null
  } catch {
    return null
  }
}

export function saveSession(token: string, user: AuthUser): void {
  try {
    sessionStorage.setItem(TOKEN_KEY, token)
    sessionStorage.setItem(USER_KEY, JSON.stringify(user))
  } catch {
    /* Storage unavailable - the session then lasts as long as this page does. */
  }
}

type Listener = () => void
const listeners = new Set<Listener>()

/** Fires when the session ends, whether the user pressed Sign out or the API
 *  rejected a token. Returns its own unsubscribe, for React cleanup. */
export function onSessionEnded(listener: Listener): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** The single way a session ends. Both the Sign out button and the 401
 *  interceptor call this, so there is one place that clears storage and one
 *  place that tells the app to show the login screen. */
export function endSession(): void {
  try {
    sessionStorage.removeItem(TOKEN_KEY)
    sessionStorage.removeItem(USER_KEY)
  } catch {
    /* Nothing to clear. */
  }
  listeners.forEach((listener) => listener())
}
