'use client'

import { PartnersPanel } from '@/components/admin/PartnersPanel'
import { Page } from '../_components/ui'

export default function AdminPartnersPage() {
  return (
    <Page title="Partners" description="Charity partners, their accrued share of revenue, and recorded payouts.">
      <PartnersPanel />
    </Page>
  )
}
