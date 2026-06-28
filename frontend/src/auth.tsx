import { createContext, useContext, useEffect, useState, ReactNode } from 'react'
import { api, clearToken, getToken, setToken, User } from './api'

interface AuthCtx {
  user: User | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  register: (email: string, password: string, name: string) => Promise<void>
  logout: () => void
  refreshUser: () => Promise<void>
}

const AuthContext = createContext<AuthCtx | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!getToken()) {
      setLoading(false)
      return
    }
    api.me().then(setUser).catch(() => clearToken()).finally(() => setLoading(false))
  }, [])

  const login = async (email: string, password: string) => {
    const res = await api.login(email, password)
    setToken(res.access_token)
    setUser(res.user)
  }

  const register = async (email: string, password: string, name: string) => {
    const res = await api.register(email, password, name)
    setToken(res.access_token)
    setUser(res.user)
  }

  const logout = () => {
    clearToken()
    setUser(null)
  }

  const refreshUser = async () => {
    if (!getToken()) return
    const u = await api.me()
    setUser(u)
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout, refreshUser }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth outside provider')
  return ctx
}
