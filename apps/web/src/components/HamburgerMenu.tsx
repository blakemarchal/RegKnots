'use client'

import { useEffect, useRef, useState, useTransition } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import { useAuthStore } from '@/lib/auth'
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

const BASE_MENU_ITEMS: MenuItem[] = [
  { icon: '\uFF0B', label: 'New Chat', action: 'new', path: '/' },
  { icon: '\u2261', label: 'Chat History', action: 'history', path: '/history' },
  { icon: '\u2693', label: 'My Vessels', action: 'vessels' },
  { icon: '\u25A1', label: 'Certificates', action: 'certificates', path: '/certificates' },
  { icon: '\u2299', label: 'My Credentials', action: 'credentials', path: '/credentials' },
  { icon: '\u270D', label: 'Sea Service Letter', action: 'sea-service-letter', path: '/sea-service-letter' },
  { icon: '\u270E', label: 'Compliance Log', action: 'log', path: '/log' },
  { icon: '\u2611', label: 'PSC Checklist', action: 'psc-checklist', path: '/psc-checklist' },
  { icon: '\u24D8', label: 'Vessel Dossier', action: 'vessel-dossier', path: '/vessel-dossier' },
  { icon: '\u2750', label: 'Reference', action: 'reference', path: '/reference' },
  { icon: '?', label: 'Help', action: 'help', path: '/support' },
  { icon: '\u2709', label: 'Give Feedback', action: 'feedback' },
  { icon: '\u2665', label: 'Giving Back', action: 'giving', path: '/giving' },
  { icon: '\u25CE', label: 'Account', action: 'account', path: '/account' },
]

const ADMIN_ITEM: MenuItem = { icon: '\u2318', label: 'Admin', action: 'admin', path: '/admin' }

export function HamburgerMenu({ open, onClose, onNewChat, onOpenVessels, onOpenSurvey }: Props) {
  const router = useRouter()
  const pathname = usePathname()
  const logout = useAuthStore((s) => s.logout)
  const isAdmin = useAuthStore((s) => s.user?.is_admin ?? false)


  const [pendingAction, setPendingAction] = useState<string | null>(null)
  const [isPending, startTransition] = useTransition()

  // Track `isPending` transitions so we know when a navigation completes.
  const wasPendingRef = useRef(false)

  // Lock body scroll when open
  useEffect(() => {
    if (open) document.body.style.overflow = 'hidden'
    else document.body.style.overflow = ''
    return () => { document.body.style.overflow = '' }
  }, [open])

  // Prefetch all route destinations when the drawer opens so subsequent
  // navigations are near-instant. Cheap — ~5-10 KB per route.
  useEffect(() => {
    if (!open) return
    const allItems = [...BASE_MENU_ITEMS, ...(isAdmin ? [ADMIN_ITEM] : [])]
    allItems.forEach((item) => {
      if (item.path && item.path !== pathname) {
        try { router.prefetch(item.path) } catch { /* noop */ }
      }
    })
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

  const items = [...BASE_MENU_ITEMS, ...(isAdmin ? [ADMIN_ITEM] : [])]

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

        {/* Menu items */}
        <nav className="flex-1 py-2 overflow-y-auto">
          {items.map(item => {
            const isCurrent = item.path && pathname === item.path
            const isLoading = pendingAction === item.action
            return (
              <button
                key={item.action}
                onClick={() => handleItem(item)}
                disabled={isPending}
                className={`w-full flex items-center gap-4 px-5 py-3.5 text-left
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
