'use client'

// 2026-10-16 — admin-lite for a salesperson (Jordan Hall). Gated server-side by
// users.is_sales (apps/api/app/routers/sales.py); here the token's is_sales flag
// decides whether the pages render at all. Admins may look at any code with ?code=.

import { createContext, useContext, useEffect, useState } from 'react'
import Link from 'next/link'
import { usePathname, useSearchParams } from 'next/navigation'
import AuthGuard from '@/components/AuthGuard'
import { AppHeader } from '@/components/AppHeader'
import { apiRequest } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'

export interface SalesMe {
  code: string
  link: string
  short_link: string
  rate: number
  is_admin: boolean
  trial_days: number | null
}

const SalesContext = createContext<{ me: SalesMe | null; codeQuery: string }>({ me: null, codeQuery: '' })
export function useSales() {
  return useContext(SalesContext)
}

const TABS = [
  { href: '/sales', label: 'Overview' },
  { href: '/sales/leads', label: 'Leads' },
  { href: '/sales/kit', label: 'Kit' },
]

function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() ?? ''
  const params = useSearchParams()
  const user = useAuthStore((s) => s.user)
  const code = params.get('code') ?? ''
  const codeQuery = code ? `?code=${encodeURIComponent(code)}` : ''
  const [me, setMe] = useState<SalesMe | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    apiRequest<SalesMe>(`/sales/me${codeQuery}`).then(setMe).catch((e: unknown) => {
      setError(e instanceof Error && /403|404/.test(e.message) ? 'This area is for the sales team.' : 'Could not load.')
    })
  }, [codeQuery])

  return (
    <div className="min-h-screen bg-[#0a0e1a] text-[#f0ece4]">
      <AppHeader title="Sales" />
      <main className="max-w-5xl mx-auto px-4 md:px-8 py-6">
        <nav className="flex gap-1 mb-6 border-b border-white/8" aria-label="Sales sections">
          {TABS.map((t) => {
            const active = t.href === '/sales' ? pathname === '/sales' : pathname.startsWith(t.href)
            return (
              <Link key={t.href} href={`${t.href}${codeQuery}`}
                className={`font-mono text-sm px-3 py-2 -mb-px border-b-2 transition-colors ${
                  active ? 'border-[#2dd4bf] text-[#f0ece4]' : 'border-transparent text-[#8a94ad] hover:text-[#f0ece4]'}`}>
                {t.label}
              </Link>
            )
          })}
          {me?.is_admin && (
            <span className="ml-auto font-mono text-[11px] text-[#6b7594] self-center">admin view · code {me.code}</span>
          )}
        </nav>
        {error ? (
          <p className="font-mono text-sm text-[#8a94ad]">{error}{user?.is_admin ? ' Admins: add ?code=<pilot code>.' : ''}</p>
        ) : (
          <SalesContext.Provider value={{ me, codeQuery }}>{children}</SalesContext.Provider>
        )}
      </main>
    </div>
  )
}

export default function SalesLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGuard>
      <Shell>{children}</Shell>
    </AuthGuard>
  )
}
