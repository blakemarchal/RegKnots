'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuthStore } from '@/lib/auth'

interface Props {
  open: boolean
  onClose: () => void
  onNewChat: () => void
  onOpenVessels: () => void
}

const MENU_ITEMS = [
  { icon: '＋', label: 'New Chat', action: 'new' },
  { icon: '≡', label: 'Chat History', action: 'history' },
  { icon: '⚓', label: 'My Vessels', action: 'vessels' },
  { icon: '◎', label: 'Account', action: 'account' },
]

export function HamburgerMenu({ open, onClose, onNewChat, onOpenVessels }: Props) {
  const router = useRouter()
  const logout = useAuthStore((s) => s.logout)

  // Lock body scroll when open
  useEffect(() => {
    if (open) document.body.style.overflow = 'hidden'
    else document.body.style.overflow = ''
    return () => { document.body.style.overflow = '' }
  }, [open])

  if (!open) return null

  function handleItem(action: string) {
    if (action === 'new') onNewChat()
    if (action === 'history') router.push('/history')
    if (action === 'vessels') onOpenVessels()
    if (action === 'account') { onClose(); router.push('/account') }
    if (action === 'signout') {
      logout().then(() => router.replace('/login'))
    }
    onClose()
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-[#0a0e1a]/70 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Drawer */}
      <div className="relative w-72 h-full bg-[#111827] border-l border-white/8
        flex flex-col animate-[slideInRight_0.25s_ease-out]">

        {/* Drawer header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-white/8">
          <span className="font-display text-2xl font-bold text-[#f0ece4] tracking-wide">
            RegKnots
          </span>
          <button
            onClick={onClose}
            className="w-8 h-8 flex items-center justify-center rounded-lg
              text-[#6b7594] hover:text-[#f0ece4] hover:bg-white/8
              transition-colors duration-150"
            aria-label="Close menu"
          >
            <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        {/* Menu items */}
        <nav className="flex-1 py-2">
          {MENU_ITEMS.map(item => (
            <button
              key={item.action}
              onClick={() => handleItem(item.action)}
              className="w-full flex items-center gap-4 px-5 py-3.5 text-left
                text-[#f0ece4]/80 hover:text-[#f0ece4] hover:bg-white/5
                transition-colors duration-150"
            >
              <span className="w-5 text-teal/70 text-base leading-none text-center" aria-hidden="true">
                {item.icon}
              </span>
              <span className="text-sm font-medium">{item.label}</span>
            </button>
          ))}
        </nav>

        {/* Sign out */}
        <div className="border-t border-white/8 pb-8">
          <button
            onClick={() => handleItem('signout')}
            className="w-full flex items-center gap-4 px-5 py-3.5 text-left
              text-[#6b7594] hover:text-red-400/80 hover:bg-white/5
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
