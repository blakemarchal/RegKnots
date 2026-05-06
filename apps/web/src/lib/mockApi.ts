import type { ApiResponse, CitedRegulation } from '@/types/chat'
import { apiRequest } from './api'
import { useAuthStore } from './auth'

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

export async function sendMessage(
  query: string,
  conversationId: string | null,
  vesselId?: string | null,
  workspaceId?: string | null,
): Promise<ApiResponse> {
  return apiRequest<ApiResponse>('/chat', {
    method: 'POST',
    body: JSON.stringify({
      query,
      ...(conversationId ? { conversation_id: conversationId } : {}),
      ...(vesselId ? { vessel_id: vesselId } : {}),
      ...(workspaceId ? { workspace_id: workspaceId } : {}),
    }),
  })
}

export interface ChatStreamDone {
  answer: string
  cited_regulations: CitedRegulation[]
  conversation_id: string
  model_used: string
  input_tokens: number
  output_tokens: number
  vessel_update?: Record<string, unknown> | null
  // Sprint D6.48 Phase 2 — populated only when the corpus genuinely
  // missed AND web fallback found a verified verbatim quote on a
  // trusted regulator domain.
  web_fallback?: import('@/types/chat').WebFallbackCard | null
}

/**
 * POST /chat/stream — server-sent events variant of sendMessage.
 *
 * Calls onStatus(message) for each progress event during processing, then
 * calls onDone(payload) once with the complete answer. Throws on auth/billing
 * errors before the stream starts (status returned in the thrown Error message).
 *
 * Auth: attaches the bearer token from the auth store. On 401, calls
 * refreshAuth() and retries once. A second 401 redirects to /login.
 */
export async function sendMessageStream(
  query: string,
  conversationId: string | null,
  vesselId: string | null | undefined,
  onStatus: (message: string) => void,
  onDone: (data: ChatStreamDone) => void,
  onStarted?: (conversationId: string) => void,
  // Sprint D6.34 — per-message verbosity override. Undefined = use the
  // user's saved preference. "brief" / "standard" / "detailed" override
  // for this turn only.
  verbosity?: 'brief' | 'standard' | 'detailed',
  // Sprint D6.49 — workspace context. Undefined/null = personal chat
  // (legacy behavior). Set to a workspace UUID to bind this turn to
  // that workspace. The user must already be a member; the API
  // validates and 403s otherwise.
  workspaceId?: string | null,
  // Sprint D6.68 — token-by-token streaming. Each `delta` event from
  // the backend carries a chunk of the answer text; caller appends to
  // the assistant message in real time. `delta_reset` clears the
  // accumulated text (fired when Claude streaming fails and we fall
  // back to OpenAI mid-flight). Both are optional — callers that
  // don't pass onDelta will get the same final-answer-only behavior
  // as before, since onDone always carries the full cleaned answer.
  onDelta?: (chunkText: string) => void,
  onDeltaReset?: () => void,
): Promise<void> {
  const body = JSON.stringify({
    query,
    ...(conversationId ? { conversation_id: conversationId } : {}),
    ...(vesselId ? { vessel_id: vesselId } : {}),
    ...(verbosity ? { verbosity } : {}),
    ...(workspaceId ? { workspace_id: workspaceId } : {}),
  })

  const doFetch = (token: string | null): Promise<Response> =>
    fetch(`${API_URL}/chat/stream`, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body,
    })

  const store = useAuthStore.getState()
  let token = store.accessToken
  let response = await doFetch(token)

  // 401 → refresh token, retry once
  if (response.status === 401) {
    const refreshed = await store.refreshAuth()
    if (!refreshed) {
      window.location.href = '/login'
      throw new Error('Session expired')
    }
    token = useAuthStore.getState().accessToken
    response = await doFetch(token)
  }

  if (!response.ok) {
    const text = await response.text().catch(() => response.statusText)
    throw new Error(`API error ${response.status}: ${text}`)
  }

  if (!response.body) {
    throw new Error('Streaming response has no body')
  }

  // Parse text/event-stream incrementally
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })

      // SSE events are separated by a blank line
      const events = buffer.split('\n\n')
      buffer = events.pop() ?? ''

      for (const eventStr of events) {
        if (!eventStr.trim()) continue

        let eventType = ''
        let dataLine = ''
        for (const line of eventStr.split('\n')) {
          if (line.startsWith('event: ')) eventType = line.slice(7).trim()
          else if (line.startsWith('data: ')) dataLine = line.slice(6)
        }

        if (!eventType || !dataLine) continue

        if (eventType === 'started') {
          if (onStarted) {
            try {
              const parsed = JSON.parse(dataLine) as { conversation_id?: string }
              if (parsed.conversation_id) onStarted(parsed.conversation_id)
            } catch {
              // ignore — recovery still works without it for existing conversations
            }
          }
        } else if (eventType === 'status') {
          try {
            onStatus(JSON.parse(dataLine) as string)
          } catch {
            onStatus(dataLine)
          }
        } else if (eventType === 'delta') {
          if (onDelta) {
            try {
              onDelta(JSON.parse(dataLine) as string)
            } catch {
              onDelta(dataLine)
            }
          }
        } else if (eventType === 'delta_reset') {
          if (onDeltaReset) onDeltaReset()
        } else if (eventType === 'done') {
          const parsed = JSON.parse(dataLine) as ChatStreamDone
          onDone(parsed)
        } else if (eventType === 'error') {
          let detail = 'Server error during streaming'
          try {
            const err = JSON.parse(dataLine) as { message?: string }
            if (err.message) detail = err.message
          } catch {
            // ignore parse failure
          }
          throw new Error(detail)
        }
      }
    }
  } finally {
    try {
      reader.releaseLock()
    } catch {
      // ignore
    }
  }
}
