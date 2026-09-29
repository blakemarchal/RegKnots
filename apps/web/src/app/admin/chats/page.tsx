'use client'

import { useSearchParams } from 'next/navigation'
import { useAdmin } from '../_lib/AdminContext'
import { ChatsTab } from '../_components/ChatsPanel'
import { Page } from '../_components/ui'

export default function AdminChatsPage() {
  const params = useSearchParams()
  const { excludeInternal } = useAdmin()
  return (
    <Page
      title="Conversations"
      description="Every conversation with its forensic detail: model, citations, unverified cites and hedges. Open one to see it exactly as the user did."
    >
      <ChatsTab initialChatId={params.get('conversation_id')} defaultExcludeInternal={excludeInternal} />
    </Page>
  )
}
