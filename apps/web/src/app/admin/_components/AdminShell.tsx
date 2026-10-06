'use client'

// 2026-09-29 — admin navigation. The old /admin crammed ten tabs of mixed
// purpose into one page with three more tools linked from its corner; every
// section now has its own URL, grouped by the job it serves, with counts on
// the items that are waiting for someone.

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useEffect, useState } from 'react'
import { useEscapeKey } from '@/lib/useEscapeKey'
import { useAdmin } from '../_lib/AdminContext'
import { CountBadge, Pill } from './ui'

type BadgeKey = 'tickets' | 'errors' | 'citations' | 'hedged'

interface NavItem {
  href: string
  label: string
  badge?: BadgeKey
}

const NAV: { group: string; items: NavItem[] }[] = [
  { group: 'Overview', items: [{ href: '/admin', label: 'Dashboard' }] },
  {
    group: 'Customers',
    items: [
      { href: '/admin/users', label: 'Users' },
      { href: '/admin/traffic', label: 'Traffic & signups' },
      { href: '/admin/partners', label: 'Partners' },
    ],
  },
  {
    group: 'Answers',
    items: [
      { href: '/admin/chats', label: 'Conversations' },
      { href: '/admin/hedge-audit', label: 'Hedge audit', badge: 'hedged' },
      { href: '/admin/citations', label: 'Citation errors', badge: 'citations' },
      { href: '/admin/documents', label: 'Documents' },
      { href: '/admin/web-fallback', label: 'Web fallback' },
    ],
  },
  {
    group: 'Support',
    items: [
      { href: '/admin/support', label: 'Tickets & surveys', badge: 'tickets' },
      { href: '/admin/email', label: 'Email' },
      { href: '/admin/announcements', label: 'Announcements' },
    ],
  },
  {
    group: 'Platform',
    items: [
      { href: '/admin/system', label: 'System health', badge: 'errors' },
      { href: '/admin/jobs', label: 'Jobs' },
      { href: '/admin/corpus', label: 'Corpus' },
      { href: '/admin/features', label: 'Feature usage' },
      { href: '/admin/data', label: 'Data browser' },
      { href: '/admin/audit-log', label: 'Audit log' },
    ],
  },
]

function isActive(pathname: string, href: string) {
  return href === '/admin' ? pathname === '/admin' : pathname === href || pathname.startsWith(`${href}/`)
}

function useBadges(): Record<BadgeKey, number> {
  const { stats, sentry } = useAdmin()
  return {
    tickets: stats?.support_tickets_open ?? 0,
    errors: sentry?.length ?? 0,
    citations: stats?.citation_errors_7d ?? 0,
    hedged: stats?.retrieval_misses_7d ?? 0,
  }
}

function NavList({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname() ?? '/admin'
  const badges = useBadges()
  return (
    <nav aria-label="Admin sections" className="flex flex-col gap-5">
      {NAV.map((g) => (
        <div key={g.group}>
          <p className="px-3 mb-1.5 font-mono text-[10px] uppercase tracking-[0.14em] text-[#6b7594]">{g.group}</p>
          <ul className="flex flex-col gap-0.5">
            {g.items.map((item) => {
              const active = isActive(pathname, item.href)
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    onClick={onNavigate}
                    aria-current={active ? 'page' : undefined}
                    className={`flex items-center gap-2 rounded-lg px-3 py-2 font-mono text-[13px] transition-colors
                      ${active
                        ? 'bg-[#2dd4bf]/12 text-[#2dd4bf] shadow-[inset_2px_0_0_#2dd4bf]'
                        : 'text-[#f0ece4]/75 hover:text-[#f0ece4] hover:bg-white/5'}`}
                  >
                    <span className="truncate">{item.label}</span>
                    {item.badge && (
                      <CountBadge n={badges[item.badge]} tone={item.badge === 'errors' ? 'red' : 'amber'} />
                    )}
                  </Link>
                </li>
              )
            })}
          </ul>
        </div>
      ))}
    </nav>
  )
}

function InternalToggle() {
  const { excludeInternal, setExcludeInternal } = useAdmin()
  return (
    <button
      role="switch"
      aria-checked={excludeInternal}
      onClick={() => setExcludeInternal(!excludeInternal)}
      className="w-full flex items-center gap-3 rounded-lg px-3 py-2 hover:bg-white/5 transition-colors text-left"
      title="Leaves out admin, internal and test accounts (Blake, Karynn, test accounts)"
    >
      <span className={`relative flex-shrink-0 w-9 h-5 rounded-full transition-colors ${excludeInternal ? 'bg-[#2dd4bf]' : 'bg-[#6b7594]/40'}`}>
        <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full transition-transform ${excludeInternal ? 'translate-x-4' : ''}`} />
      </span>
      <span className="font-mono text-[11px] leading-tight text-[#f0ece4]/80">
        {excludeInternal ? 'Real users only' : 'Including internal accounts'}
      </span>
    </button>
  )
}

function Brand() {
  const { isOwner, isReadOnly } = useAdmin()
  return (
    <div className="flex items-center gap-2.5 px-3">
      <svg viewBox="0 0 24 24" className="w-7 h-7 text-[#2dd4bf] flex-shrink-0" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
        <circle cx="12" cy="12" r="10" strokeDasharray="1.5 2.5" />
        <path d="M12 3.5 13.3 11 12 12.3 10.7 11Z" fill="currentColor" stroke="none" />
        <path d="M12 20.5 13.3 13 12 11.7 10.7 13Z" fill="currentColor" stroke="none" opacity=".45" />
        <circle cx="12" cy="12" r="1.3" fill="currentColor" stroke="none" />
      </svg>
      <div className="min-w-0">
        <p className="font-display text-lg font-bold tracking-wide text-[#f0ece4] leading-none">RegKnot Admin</p>
        <div className="mt-1">
          <Pill tone={isReadOnly ? 'amber' : isOwner ? 'teal' : 'purple'}>{isReadOnly ? 'Read only' : isOwner ? 'Owner' : 'Admin'}</Pill>
        </div>
      </div>
    </div>
  )
}

export function AdminShell({ children }: { children: React.ReactNode }) {
  const [drawerOpen, setDrawerOpen] = useState(false)
  const pathname = usePathname()
  useEffect(() => setDrawerOpen(false), [pathname])
  useEscapeKey(drawerOpen, () => setDrawerOpen(false))

  const badges = useBadges()

  return (
    <div className="min-h-dvh bg-[#0a0e1a] text-[#f0ece4]">
      {/* Desktop sidebar */}
      <aside className="hidden lg:flex fixed inset-y-0 left-0 w-60 flex-col border-r border-white/8 bg-[#0c1120]">
        <div className="pt-5 pb-4"><Brand /></div>
        <div className="flex-1 overflow-y-auto px-2 pb-4">
          <NavList />
        </div>
        <div className="border-t border-white/8 p-2 flex flex-col gap-0.5">
          <InternalToggle />
          <Link href="/" className="rounded-lg px-3 py-2 font-mono text-[12px] text-[#8b93ad] hover:text-[#f0ece4] hover:bg-white/5">
            ← Back to RegKnot
          </Link>
        </div>
      </aside>

      {/* Mobile top bar + drawer */}
      <div className="lg:hidden sticky top-0 z-30 flex items-center gap-3 border-b border-white/8 bg-[#0c1120]/95 backdrop-blur px-4 h-14">
        <button
          onClick={() => setDrawerOpen(true)}
          aria-label="Open admin menu"
          className="relative w-10 h-10 -ml-2 flex items-center justify-center rounded-lg text-[#f0ece4]/85 hover:bg-white/5"
        >
          <svg viewBox="0 0 24 24" className="w-6 h-6" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
            <path d="M4 7h16M4 12h16M4 17h10" />
          </svg>
          {/* Something in the menu needs a look. */}
          {Object.values(badges).some((n) => n > 0) && (
            <span className="absolute top-2 right-2 w-2 h-2 rounded-full bg-amber-400" aria-hidden="true" />
          )}
        </button>
        {/* The page already carries its own title, so the bar names the app. */}
        <p className="font-display text-lg font-bold tracking-wide truncate">RegKnot Admin</p>
      </div>
      {drawerOpen && (
        <div className="lg:hidden fixed inset-0 z-40" role="dialog" aria-modal="true" aria-label="Admin menu">
          <button className="absolute inset-0 bg-black/60" aria-label="Close admin menu" onClick={() => setDrawerOpen(false)} />
          <div className="absolute inset-y-0 left-0 w-[82%] max-w-xs flex flex-col bg-[#0c1120] border-r border-white/10 shadow-2xl">
            <div className="pt-5 pb-4 flex items-start justify-between pr-3">
              <Brand />
              <button onClick={() => setDrawerOpen(false)} aria-label="Close admin menu"
                className="w-10 h-10 flex items-center justify-center rounded-lg text-[#8b93ad] hover:bg-white/5 text-xl">×</button>
            </div>
            <div className="flex-1 overflow-y-auto px-2 pb-4"><NavList onNavigate={() => setDrawerOpen(false)} /></div>
            <div className="border-t border-white/8 p-2 flex flex-col gap-0.5">
              <InternalToggle />
              <Link href="/" className="rounded-lg px-3 py-2 font-mono text-[12px] text-[#8b93ad] hover:text-[#f0ece4] hover:bg-white/5">
                ← Back to RegKnot
              </Link>
            </div>
          </div>
        </div>
      )}

      <main className="lg:pl-60 min-w-0">{children}</main>
    </div>
  )
}
