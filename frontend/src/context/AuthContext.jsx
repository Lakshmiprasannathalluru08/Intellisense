import { createContext, useContext, useCallback, useState } from 'react'

const AuthContext = createContext(null)

/**
 * Holds the JWT and current user in memory only (React state).
 * Nothing is persisted to localStorage, so a page refresh logs the
 * user out by design.
 */
export function AuthProvider({ children }) {
  const [token, setToken] = useState(null)
  const [user, setUser] = useState(null)

  const login = useCallback((newToken, newUser) => {
    setToken(newToken)
    setUser(newUser)
  }, [])

  const logout = useCallback(() => {
    setToken(null)
    setUser(null)
  }, [])

  return (
    <AuthContext.Provider value={{ token, user, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
