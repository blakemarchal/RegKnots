import { useAuthStore } from './auth'

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

async function doFetch(path: string, init: RequestInit, token: string | null): Promise<Response> {
  return fetch(`${API_URL}${path}`, {
    ...init,
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init.headers ?? {}),
    },
  })
}

/**
 * Centralized API client.
 * - Attaches Bearer token from auth store
 * - On 401: calls POST /auth/refresh, retries once
 * - On second 401: redirects to /login
 */
export async function apiRequest<T = unknown>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const store = useAuthStore.getState()
  let token = store.accessToken

  let res = await doFetch(path, init, token)

  if (res.status === 401) {
    const refreshed = await store.refreshAuth()
    if (!refreshed) {
      window.location.href = '/login'
      throw new Error('Session expired')
    }
    token = useAuthStore.getState().accessToken
    res = await doFetch(path, init, token)
  }

  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText)
    throw new Error(`API error ${res.status}: ${detail}`)
  }

  return res.json() as Promise<T>
}
