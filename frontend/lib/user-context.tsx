'use client'

import { createContext, useContext } from 'react'
import type { User } from '@/lib/types'

interface UserContextValue {
  user: User
}

export const UserContext = createContext<UserContextValue | null>(null)

export function useUser(): User {
  const ctx = useContext(UserContext)
  if (!ctx) throw new Error('useUser must be used inside ProtectedLayout')
  return ctx.user
}
