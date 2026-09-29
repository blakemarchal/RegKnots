'use client'

import { DataTab } from '../_components/DataBrowser'
import { Page } from '../_components/ui'

export default function AdminDataPage() {
  return (
    <Page title="Data browser" description="Read-only access to whitelisted tables. Sensitive columns such as password hashes and tokens are left out.">
      <DataTab />
    </Page>
  )
}
