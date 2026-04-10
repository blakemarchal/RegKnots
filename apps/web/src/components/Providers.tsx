'use client'

import { HydrationGate } from './HydrationGate'
import { NavigationProgress } from './NavigationProgress'
import { useSwUpdate } from '@/hooks/useSwUpdate'

export function Providers({ children }: { children: React.ReactNode }) {
  useSwUpdate()

  return (
    <HydrationGate>
      <NavigationProgress />
      {children}
    </HydrationGate>
  )
}
