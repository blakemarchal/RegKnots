'use client'

import { AuditLogSection } from '../_components/AuditLogPanel'
import { Page } from '../_components/ui'

export default function AdminAuditLogPage() {
  return (
    <Page title="Audit log" description="Admin actions, newest first: who did what, to which account, and when.">
      <AuditLogSection />
    </Page>
  )
}
