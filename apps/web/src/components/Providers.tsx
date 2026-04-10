'use client'

import { HydrationGate } from './HydrationGate'
import { NavigationProgress } from './NavigationProgress'

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <HydrationGate>
      <NavigationProgress />
      {children}
    </HydrationGate>
  )
}
