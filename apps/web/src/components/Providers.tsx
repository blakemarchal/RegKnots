'use client'

import { HydrationGate } from './HydrationGate'

export function Providers({ children }: { children: React.ReactNode }) {
  return <HydrationGate>{children}</HydrationGate>
}
