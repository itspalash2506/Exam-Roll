import { createContext, useContext, useState, useCallback, useEffect } from 'react'
import { login as apiLogin, logout as apiLogout, me as apiMe } from '../api/client.js'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  // Starts true so route guards don't flash a login redirect before the
  // initial "am I already logged in?" check (a valid cookie from a
  // previous visit) has had a chance to resolve.
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    apiMe()
      .then((res) => {
        if (!cancelled) setUser(res.data)
      })
      .catch(() => {
        // No session, or it expired/was revoked — not an error a user
        // needs to see, just means they're logged out.
        if (!cancelled) setUser(null)
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const login = useCallback(async (email, password) => {
    const res = await apiLogin(email, password)
    setUser(res.data)
    return res.data
  }, [])

  const logout = useCallback(async () => {
    try {
      await apiLogout()
    } finally {
      // Clear local state even if the network call fails — the user
      // clicked logout, so the app should behave as logged-out regardless.
      setUser(null)
    }
  }, [])

  return (
    <AuthContext.Provider
      value={{ user, isAuthenticated: !!user, isLoading, login, logout }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
