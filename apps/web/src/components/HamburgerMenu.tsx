'use client'

import { useEffect, useRef, useState, useTransition } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import { useAuthStore } from '@/lib/auth'
import { useViewMode } from '@/lib/useViewMode'
import { apiRequest } from '@/lib/api'
import { signalNavigation } from './NavigationProgress'

interface Props {
  open: boolean
  onClose: () => void
  onNewChat: () => void
  onOpenVessels: () => void
  onOpenSurvey?: () => void
}

interface MenuItem {
  icon: string
  label: string
  action: string
  path?: string  // route path if this item navigates
}

interface MenuSection {
  label: string | null  // null = no header (e.g., the top "Chat" section can stay unlabelled)
  items: MenuItem[]
}

// Menu organized into 5 conceptual sections so it scans cleanly even at 13+
// items. Order: most-frequent actions first, settings/footer last.
//
// "Certificates" (the static cert reference page) intentionally NOT here —
// it's reference material, accessible from the Reference page. Removing it
// from primary nav reduces clutter and resolves the
// "Certificates vs Credentials" ambiguity.
const MENU_SECTIONS: MenuSection[] = [
  {
    label: 'Chat',
    items: [
      { icon: '\uFF0B', label: 'New Chat', action: 'new', path: '/' },
      { icon: '\u2261', label: 'Chat History', action: 'history', path: '/history' },
    ],
  },
  {
    label: 'My Fleet',
    items: [
      { icon: '\u2693', label: 'My Vessels', action: 'vessels' },
      { icon: '\u24D8', label: 'Vessel Dossier', action: 'vessel-dossier', path: '/vessel-dossier' },
      // D6.49 \u2014 Wheelhouse / crew tier. Visible to all users; the
      // /workspaces page itself shows a friendly "not yet available"
      // message to non-internal accounts during the staged rollout.
      { icon: '\u2693', label: 'Wheelhouse', action: 'wheelhouse', path: '/workspaces' },
    ],
  },
  {
    label: 'My Credentials',
    items: [
      { icon: '\u2299', label: 'Credentials Tracker', action: 'credentials', path: '/credentials' },
      { icon: '\u2693', label: 'Sea-Time Log',         action: 'sea-time',           path: '/sea-time' },
      { icon: '\u270D', label: 'Sea Service Letter',   action: 'sea-service-letter', path: '/sea-service-letter' },
    ],
  },
  {
    label: 'Compliance Tools',
    items: [
      { icon: '\u270E', label: 'Compliance Log', action: 'log', path: '/log' },
      { icon: '\u2611', label: 'PSC Checklist', action: 'psc-checklist', path: '/psc-checklist' },
    ],
  },
  {
    label: 'Study Tools',
    items: [
      // Sprint D6.83 \u2014 Study Tools (quiz + study guide generators).
      // Available to all logged-in users; tier gate happens server-side
      // (free tier sees an upsell on the page itself).
      { icon: '\u2261', label: 'Quizzes & Guides', action: 'study', path: '/study' },
    ],
  },
  {
    label: 'Help & Account',
    items: [
      // D6.63 \u2014 Reference removed: it was an offline-content stub
      // and we don't actually work offline. Re-introduce when (if)
      // we ship a real offline pack.
      { icon: '?', label: 'Help', action: 'help', path: '/support' },
      { icon: '\u2709', label: 'Give Feedback', action: 'feedback' },
      { icon: '\u2665', label: 'Giving Back', action: 'giving', path: '/giving' },
      { icon: '\u25CE', label: 'Account', action: 'account', path: '/account' },
    ],
  },
]

const ADMIN_ITEM: MenuItem = { icon: '\u2318', label: 'Admin', action: 'admin', path: '/admin' }

// D6.55 \u2014 actions hidden from wheelhouse_only users.
//
// Boundary: workspace owns vessel-context tools (vessel particulars,
// dossier, compliance log, PSC checklist); USER owns career-context
// tools (credentials, sea service letter). Wheelhouse-only users
// are guests on a captain's workspace, but their MMC, STCW, and time
// at sea are theirs personally \u2014 they retain access to those.
//
// Hide:
//   vessels, vessel-dossier   (workspace owns the boat)
//   log, psc-checklist        (boat-side compliance, not personal)
//   reference, giving         (UI noise for invited-only users)
// Keep:
//   credentials               (their MMC etc.)
//   sea-service-letter        (their career history)
//   account, help, feedback, signout
//   wheelhouse                (the workspace itself)
//
// Earlier slice (D6.53) over-aggressively hid credentials + sea
// service. Restored here.
const WHEELHOUSE_ONLY_HIDDEN_ACTIONS = new Set<string>([
  'vessels',
  'vessel-dossier',
  'log',
  'psc-checklist',
  'reference',
  'giving',
])

export function HamburgerMenu({ open, onClose, onNewChat, onOpenVessels, onOpenSurvey }: Props) {
  const router = useRouter()
  const pathname = usePathname()
  const logout = useAuthStore((s) => s.logout)
  const isAdmin = useAuthStore((s) => s.user?.is_admin ?? false)
  // D6.53 — wheelhouse_only users see a filtered menu (no personal-
  // context tools) and have New Chat / Chat History rerouted into
  // the workspace context.
  const { viewMode } = useViewMode()
  const isWheelhouseOnly = viewMode?.mode === 'wheelhouse_only'
  const primaryWorkspaceId = viewMode?.primary_workspace_id ?? null

  const [pendingAction, setPendingAction] = useState<string | null>(null)
  const [isPending, startTransition] = useTransition()

  // Sprint D6.83 follow-up — Study Tools nav visibility. The backend
  // resolves the boolean (explicit user choice > persona default >
  // false). Fetched once when the drawer first opens; cheap GET that
  // also primes future renders if the user toggles in the Account
  // page mid-session. Defaults to false on fetch failure so we err
  // on the side of hiding rather than showing an unwanted entry.
  const [studyToolsEnabled, setStudyToolsEnabled] = useState<boolean>(false)
  const [studyPrefLoaded, setStudyPrefLoaded] = useState(false)
  useEffect(() => {
    if (!open || studyPrefLoaded) return
    let cancelled = false
    apiRequest<{ study_tools_enabled?: boolean }>('/onboarding/persona')
      .then((r) => {
        if (!cancelled) setStudyToolsEnabled(r.study_tools_enabled === true)
      })
      .catch(() => { /* silent — leave default false */ })
      .finally(() => { if (!cancelled) setStudyPrefLoaded(true) })
    return () => { cancelled = true }
  }, [open, studyPrefLoaded])

  // Track `isPending` transitions so we know when a navigation completes.
  const wasPendingRef = useRef(false)

  // Lock body scroll when open
  useEffect(() => {
    if (open) document.body.style.overflow = 'hidden'
    else document.body.style.overflow = ''
    return () => { document.body.style.overflow = '' }
  }, [open])

  // Flatten the grouped sections into a single list of items for prefetch
  // and admin appending. Filters out wheelhouse_only-hidden items so we
  // don't waste prefetch on routes we won't show.
  const allItems = (() => {
    const flat = MENU_SECTIONS.flatMap((s) => s.items).filter(
      (it) => !isWheelhouseOnly || !WHEELHOUSE_ONLY_HIDDEN_ACTIONS.has(it.action),
    )
    return isAdmin ? [...flat, ADMIN_ITEM] : flat
  })()

  // Prefetch all route destinations when the drawer opens so subsequent
  // navigations are near-instant. Cheap — ~5-10 KB per route.
  useEffect(() => {
    if (!open) return
    allItems.forEach((item) => {
      if (item.path && item.path !== pathname) {
        try { router.prefetch(item.path) } catch { /* noop */ }
      }
    })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, isAdmin, router, pathname])

  // When a pending navigation completes, close the drawer + clear pending state.
  useEffect(() => {
    if (wasPendingRef.current && !isPending) {
      setPendingAction(null)
      onClose()
    }
    wasPendingRef.current = isPending
  }, [isPending, onClose])

  if (!open) return null

  function navigateTo(action: string, path: string) {
    // Same page — just close silently.
    if (pathname === path) {
      onClose()
      return
    }
    signalNavigation()
    setPendingAction(action)
    startTransition(() => {
      router.push(path)
    })
  }

  function handleItem(item: MenuItem) {
    const action = item.action

    // D6.53/D6.55 — wheelhouse_only override: New Chat and Chat History
    // route to workspace-scoped surfaces.
    //
    // CRITICAL: New Chat must use a HARD navigation (window.location.href)
    // not Next.js soft routing. Two reasons:
    //   1. If we're already at `/?workspace=<id>` (e.g. resumed a chat
    //      from history), navigateTo's same-pathname check short-circuits
    //      and nothing happens.
    //   2. ChatInterface initializes its conversation_id state from the
    //      URL's `?conversation_id=` ONCE on mount; soft routing won't
    //      reset that state. Hard nav fully reloads.
    // The non-wheelhouse path uses window.location.href = '/' for the
    // same reason — we're matching that pattern.
    if (isWheelhouseOnly && primaryWorkspaceId) {
      if (action === 'new') {
        onClose()
        window.location.href = `/?workspace=${primaryWorkspaceId}`
        return
      }
      if (action === 'history') {
        navigateTo('history', `/history?workspace=${primaryWorkspaceId}`)
        return
      }
    }

    // Non-nav actions close immediately.
    if (action === 'new') { onNewChat(); onClose(); return }
    if (action === 'vessels') { onOpenVessels(); return } // onOpenVessels handles its own close
    if (action === 'feedback') { onClose(); onOpenSurvey?.(); return }
    if (action === 'signout') {
      onClose()
      logout().then(() => router.replace('/login'))
      return
    }

    if (item.path) {
      navigateTo(action, item.path)
    }
  }

  // Filter out items hidden for wheelhouse_only users, and drop any
  // section that ends up empty so we don't render dangling section
  // headers.
  // Sprint D6.83 follow-up — also drop the Study Tools entry when the
  // user has it toggled off. We hide the row, not the whole section,
  // and the empty-section filter at the end drops the "Study Tools"
  // header automatically once the only entry is gone.
  const filteredSections: MenuSection[] = MENU_SECTIONS
    .map((s) => ({
      ...s,
      items: s.items
        .filter(
          (it) =>
            !isWheelhouseOnly || !WHEELHOUSE_ONLY_HIDDEN_ACTIONS.has(it.action),
        )
        .filter((it) => it.action !== 'study' || studyToolsEnabled),
    }))
    .filter((s) => s.items.length > 0)

  // Append the admin item as its own section so it gets the same visual
  // treatment as the rest of the menu when present.
  const sections: MenuSection[] = isAdmin
    ? [...filteredSections, { label: 'Admin', items: [ADMIN_ITEM] }]
    : filteredSections

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* Backdrop */}
      <div
        className={`absolute inset-0 bg-[#0a0e1a]/70 backdrop-blur-sm transition-opacity duration-200 ${
          isPending ? 'opacity-100' : ''
        }`}
        onClick={isPending ? undefined : onClose}
        aria-hidden="true"
      />

      {/* Drawer */}
      <div className={`relative w-72 h-full bg-[#111827] border-l border-white/8
        flex flex-col animate-[slideInRight_0.25s_ease-out] transition-opacity duration-200
        ${isPending ? 'opacity-90' : ''}`}>

        {/* Drawer header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-white/8">
          <span className="font-display text-2xl font-bold text-[#f0ece4] tracking-wide">
            RegKnot
          </span>
          <button
            onClick={onClose}
            disabled={isPending}
            className="w-8 h-8 flex items-center justify-center rounded-lg
              text-[#6b7594] hover:text-[#f0ece4] hover:bg-white/8
              disabled:opacity-40 disabled:cursor-not-allowed
              transition-colors duration-150"
            aria-label="Close menu"
          >
            <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        {/* Menu items, grouped into sections */}
        <nav className="flex-1 py-1 overflow-y-auto">
          {sections.map((section, sIdx) => (
            <div key={section.label ?? `section-${sIdx}`} className={sIdx > 0 ? 'mt-2 pt-2 border-t border-white/8' : 'pt-2'}>
              {section.label && (
                <p className="px-5 pb-1 font-mono text-[10px] uppercase tracking-wider text-[#6b7594]">
                  {section.label}
                </p>
              )}
              {section.items.map((item) => {
                const isCurrent = item.path && pathname === item.path
                const isLoading = pendingAction === item.action
                return (
                  <button
                    key={item.action}
                    onClick={() => handleItem(item)}
                    disabled={isPending}
                    className={`w-full flex items-center gap-4 px-5 py-2.5 text-left
                      transition-colors duration-150 disabled:cursor-wait
                      ${isCurrent
                        ? 'text-[#2dd4bf] bg-[#2dd4bf]/5'
                        : 'text-[#f0ece4]/80 hover:text-[#f0ece4] hover:bg-white/5'
                      }
                      ${isPending && !isLoading ? 'opacity-50' : ''}`}
                  >
                    <span className="w-5 text-teal/70 text-base leading-none text-center" aria-hidden="true">
                      {item.icon}
                    </span>
                    <span className="text-sm font-medium flex-1">{item.label}</span>
                    {isLoading && (
                      <svg className="w-4 h-4 text-[#2dd4bf] animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                      </svg>
                    )}
                  </button>
                )
              })}
            </div>
          ))}
        </nav>

        {/* Sign out */}
        <div className="border-t border-white/8 pb-8">
          <button
            onClick={() => handleItem({ icon: '', label: '', action: 'signout' })}
            disabled={isPending}
            className="w-full flex items-center gap-4 px-5 py-3.5 text-left
              text-[#6b7594] hover:text-red-400/80 hover:bg-white/5
              disabled:opacity-40 disabled:cursor-not-allowed
              transition-colors duration-150"
          >
            <span className="w-5 text-center text-base leading-none" aria-hidden="true">↪</span>
            <span className="text-sm font-medium">Sign Out</span>
          </button>
        </div>
      </div>
    </div>
  )
}
