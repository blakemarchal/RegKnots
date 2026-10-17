'use client'

// 2026-10-16 — shared by the /sales layout and its pages. A Next.js layout may
// not export anything else, so the context lives here.

import { createContext, useContext } from 'react'

export interface SalesMe {
  code: string
  link: string
  short_link: string
  rate: number
  is_admin: boolean
  trial_days: number | null
}

export const SalesContext = createContext<{ me: SalesMe | null; codeQuery: string }>({ me: null, codeQuery: '' })

export function useSales() {
  return useContext(SalesContext)
}
