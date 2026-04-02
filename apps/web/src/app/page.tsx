import { ChatInterface } from '@/components/ChatInterface'
import AuthGuard from '@/components/AuthGuard'

export default async function Home({
  searchParams,
}: {
  searchParams: Promise<{ conversation_id?: string }>
}) {
  const { conversation_id } = await searchParams
  return (
    <AuthGuard>
      <ChatInterface initialConversationId={conversation_id ?? null} />
    </AuthGuard>
  )
}
