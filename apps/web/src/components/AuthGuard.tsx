'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useAuthStore } from '@/lib/auth'

export default function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const { isAuthenticated, refreshAuth } = useAuthStore()
  const [checked, setChecked] = useState(false)

  useEffect(() => {
    if (isAuthenticated) {
      setChecked(true)
      return
    }

    refreshAuth().then((ok) => {
      if (!ok) {
        router.replace('/login')
      } else {
        setChecked(true)
      }
    })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  if (!checked) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-[--color-navy-950]">
        <div className="flex gap-2">
          <span className="w-2 h-2 rounded-full bg-[--color-teal-400] animate-[bounceDot_1.2s_ease-in-out_0s_infinite]" />
          <span className="w-2 h-2 rounded-full bg-[--color-teal-400] animate-[bounceDot_1.2s_ease-in-out_0.2s_infinite]" />
          <span className="w-2 h-2 rounded-full bg-[--color-teal-400] animate-[bounceDot_1.2s_ease-in-out_0.4s_infinite]" />
        </div>
      </div>
    )
  }

  return <>{children}</>
}
