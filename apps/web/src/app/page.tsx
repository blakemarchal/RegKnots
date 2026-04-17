import { ChatInterface } from '@/components/ChatInterface'
import AuthGuard from '@/components/AuthGuard'
import { OnboardingGate } from '@/components/OnboardingGate'

export default async function Home({
  searchParams,
}: {
  searchParams: Promise<{ conversation_id?: string; q?: string }>
}) {
  const { conversation_id, q } = await searchParams
  return (
    <AuthGuard>
      <OnboardingGate>
        <ChatInterface
          initialConversationId={conversation_id ?? null}
          initialQuery={q ?? null}
        />
      </OnboardingGate>
    </AuthGuard>
  )
}
