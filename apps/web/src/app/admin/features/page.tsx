'use client'

import { FeaturesTab } from '../_components/FeaturesPanel'
import { Page } from '../_components/ui'

export default function AdminFeaturesPage() {
  return (
    <Page title="Feature usage" description="Which tools people use beyond chat, and who uses them most.">
      <FeaturesTab />
    </Page>
  )
}
