import { createContext, useContext, useState } from 'react'
import type { ReactNode } from 'react'

interface AuthCtx { token: string; login: (t: string) => void; logout: () => void }
const Ctx = createContext<AuthCtx>({} as AuthCtx)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState(localStorage.getItem('token') || '')
  const login = (t: string) => { localStorage.setItem('token', t); setToken(t) }
  const logout = () => { localStorage.removeItem('token'); setToken('') }
  return <Ctx.Provider value={{ token, login, logout }}>{children}</Ctx.Provider>
}

export const useAuth = () => useContext(Ctx)
