import type { ApiResponse } from '@/types/chat'
import { apiRequest } from './api'

export async function sendMessage(
  query: string,
  conversationId: string | null,
  vesselId?: string | null,
): Promise<ApiResponse> {
  return apiRequest<ApiResponse>('/chat', {
    method: 'POST',
    body: JSON.stringify({
      query,
      ...(conversationId ? { conversation_id: conversationId } : {}),
      ...(vesselId ? { vessel_id: vesselId } : {}),
    }),
  })
}
