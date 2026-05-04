import { ChatInterface } from '@/components/ChatInterface'
import AuthGuard from '@/components/AuthGuard'
import { OnboardingGate } from '@/components/OnboardingGate'
import { WheelhouseRedirect } from '@/components/WheelhouseRedirect'

// Sprint D6.23g — force-dynamic on root.
// Without this, Next.js prerenders `/` with `Cache-Control: s-maxage=31536000`.
// Browsers honor that fairly aggressively (~year), so post-deploy users
// kept getting their old HTML for `/` even after the SW kill SW landed.
// `force-dynamic` flips the response to `Cache-Control: no-store`, so
// every navigation to `/` revalidates against the server. The page is
// already client-rendered (AuthGuard + ChatInterface use auth state)
// so there's no real perf loss from disabling prerender.
export const dynamic = 'force-dynamic'

export default async function Home({
  searchParams,
}: {
  searchParams: Promise<{ conversation_id?: string; q?: string }>
}) {
  const { conversation_id, q } = await searchParams
  return (
    <AuthGuard>
      <WheelhouseRedirect>
        <OnboardingGate>
          <ChatInterface
            initialConversationId={conversation_id ?? null}
            initialQuery={q ?? null}
          />
        </OnboardingGate>
      </WheelhouseRedirect>
    </AuthGuard>
  )
}
