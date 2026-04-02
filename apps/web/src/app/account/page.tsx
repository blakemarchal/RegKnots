'use client'

import { useRouter } from 'next/navigation'
import AuthGuard from '@/components/AuthGuard'
import { useAuthStore } from '@/lib/auth'

const ROLE_LABELS: Record<string, string> = {
  captain: 'Captain / Master',
  mate: 'Chief Mate / Officer',
  engineer: 'Engineer',
  other: 'Other / Shore-side',
}

function AccountContent() {
  const router = useRouter()
  const { user, logout } = useAuthStore()

  async function handleSignOut() {
    await logout()
    router.replace('/login')
  }

  return (
    <div className="flex flex-col h-dvh bg-[#0a0e1a]">
      {/* Header */}
      <header className="flex-shrink-0 flex items-center gap-3 px-4 py-3
        bg-[#111827]/95 backdrop-blur-md border-b border-white/8">
        <button
          onClick={() => router.back()}
          className="w-9 h-9 flex items-center justify-center rounded-lg
            text-[#6b7594] hover:text-[#f0ece4] transition-colors duration-150"
          aria-label="Back"
        >
          <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M19 12H5M12 5l-7 7 7 7" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
        <h1 className="font-display text-xl font-bold text-[#f0ece4] tracking-wide leading-none">
          Account
        </h1>
      </header>

      {/* Content */}
      <main className="flex-1 overflow-y-auto px-4 py-6">
        <div className="max-w-sm mx-auto flex flex-col gap-4">

          {/* Profile card */}
          <div className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-4">
            {user?.full_name && (
              <div className="flex flex-col gap-1">
                <p className="font-mono text-xs text-[#6b7594] uppercase tracking-wider">Name</p>
                <p className="font-mono text-sm text-[#f0ece4]">{user.full_name}</p>
              </div>
            )}
            <div className="flex flex-col gap-1">
              <p className="font-mono text-xs text-[#6b7594] uppercase tracking-wider">Email</p>
              <p className="font-mono text-sm text-[#f0ece4]">{user?.email ?? '—'}</p>
            </div>
            <div className="flex flex-col gap-1">
              <p className="font-mono text-xs text-[#6b7594] uppercase tracking-wider">Role</p>
              <p className="font-mono text-sm text-[#f0ece4]">
                {ROLE_LABELS[user?.role ?? ''] ?? user?.role ?? '—'}
              </p>
            </div>
          </div>

          {/* Sign out */}
          <button
            onClick={handleSignOut}
            className="w-full font-mono text-sm text-red-400/70 hover:text-red-400
              border border-red-400/20 hover:border-red-400/40
              rounded-xl py-3 transition-colors duration-150"
          >
            Sign Out
          </button>

        </div>
      </main>
    </div>
  )
}

export default function AccountPage() {
  return (
    <AuthGuard>
      <AccountContent />
    </AuthGuard>
  )
}
