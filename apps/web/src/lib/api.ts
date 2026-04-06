import { useAuthStore } from './auth'
import { diagnoseNetworkError, getNetworkErrorMessage } from './networkError'

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

  let res: Response
  try {
    res = await doFetch(path, init, token)
  } catch (err) {
    if (err instanceof TypeError) {
      const diag = await diagnoseNetworkError()
      const msg = getNetworkErrorMessage(diag)
      throw new Error(`${msg.title}: ${msg.message}`)
    }
    throw err
  }

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

  if (res.status === 204) return undefined as T

  return res.json() as Promise<T>
}

/**
 * Upload a file via multipart/form-data.
 * Does NOT set Content-Type — the browser handles the boundary.
 */
export async function apiUpload<T = unknown>(
  path: string,
  formData: FormData,
): Promise<T> {
  const store = useAuthStore.getState()
  let token = store.accessToken

  const doUpload = (t: string | null) =>
    fetch(`${API_URL}${path}`, {
      method: 'POST',
      credentials: 'include',
      headers: t ? { Authorization: `Bearer ${t}` } : {},
      body: formData,
    })

  let res = await doUpload(token)

  if (res.status === 401) {
    const refreshed = await store.refreshAuth()
    if (!refreshed) {
      window.location.href = '/login'
      throw new Error('Session expired')
    }
    token = useAuthStore.getState().accessToken
    res = await doUpload(token)
  }

  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText)
    throw new Error(`API error ${res.status}: ${detail}`)
  }

  return res.json() as Promise<T>
}
