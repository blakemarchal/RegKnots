/**
 * Return-path handling for sign-in and sign-up (2026-09-27).
 *
 * The fleet plan's "Start Free Trial" goes to /workspaces, which sent a
 * visitor without a session to /login with no way back, and every new
 * registration landed in chat. `?next=/workspaces` now survives the detour.
 * Only same-site paths are honored, so the parameter can't be used as an
 * open redirect.
 */
export function safeNext(raw: string | null | undefined): string | null {
  if (!raw || raw.length > 200) return null
  if (!raw.startsWith('/') || raw.startsWith('//') || raw.startsWith('/\\')) return null
  return raw
}

/** `path` with `?next=` appended when there is a safe return path. */
export function withNext(path: string, next: string | null): string {
  return next ? `${path}?next=${encodeURIComponent(next)}` : path
}
