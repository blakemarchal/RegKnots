'use client'

import { JobsTab } from '../_components/JobsPanel'
import { Page } from '../_components/ui'

export default function AdminJobsPage() {
  return (
    <Page
      title="Jobs"
      description="Scheduled jobs and one-off triggers: preview or send digests and reminders, run the IMO and NMC checks, and see the Celery Beat schedule."
    >
      <JobsTab />
    </Page>
  )
}
