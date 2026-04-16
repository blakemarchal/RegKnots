import { ChatInterface } from '@/components/ChatInterface'
import AuthGuard from '@/components/AuthGuard'

export default async function Home({
  searchParams,
}: {
  searchParams: Promise<{ conversation_id?: string; q?: string }>
}) {
  const { conversation_id, q } = await searchParams
  return (
    <AuthGuard>
      <ChatInterface
        initialConversationId={conversation_id ?? null}
        initialQuery={q ?? null}
      />
    </AuthGuard>
  )
}
