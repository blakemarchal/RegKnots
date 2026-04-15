import { useAuthStore } from './auth'
import { diagnoseNetworkError, getNetworkErrorMessage } from './networkError'

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

/**
 * Thrown when the API returns a non-2xx response. Preserves status code and
 * parsed body (if JSON) so callers can branch on structured error detail
 * without string-parsing the message.
 */
export class ApiError extends Error {
  status: number
  body: unknown          // parsed JSON if available, otherwise the raw text
  bodyText: string       // raw text body for fallback

  constructor(status: number, bodyText: string, body: unknown) {
    // Prefer a human-readable message from body.detail when available.
    let message: string = `API error ${status}`
    if (body && typeof body === 'object' && 'detail' in (body as Record<string, unknown>)) {
      const d = (body as { detail: unknown }).detail
      if (typeof d === 'string') {
        message = d
      } else if (d && typeof d === 'object' && 'detail' in (d as Record<string, unknown>)) {
        const inner = (d as { detail: unknown }).detail
        if (typeof inner === 'string') message = inner
      }
    } else if (bodyText) {
      message = `${message}: ${bodyText}`
    }
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.body = body
    this.bodyText = bodyText
  }
}

async function doFetch(
  path: string,
  init: RequestInit,
  token: string | null,
): Promise<Response> {
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
 * - On non-2xx: throws `ApiError` with `status` and parsed `body`
 * - Supports AbortSignal via init.signal for cancellation
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
    // Preserve AbortError so callers can distinguish cancellation.
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw err
    }
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
    const bodyText = await res.text().catch(() => res.statusText)
    let parsed: unknown = bodyText
    try {
      parsed = JSON.parse(bodyText)
    } catch {
      // leave as text
    }
    throw new ApiError(res.status, bodyText, parsed)
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
    const bodyText = await res.text().catch(() => res.statusText)
    let parsed: unknown = bodyText
    try {
      parsed = JSON.parse(bodyText)
    } catch {
      // leave as text
    }
    throw new ApiError(res.status, bodyText, parsed)
  }

  return res.json() as Promise<T>
}
