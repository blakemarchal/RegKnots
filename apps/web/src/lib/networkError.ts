/**
 * Network error diagnosis utility.
 *
 * When a fetch() call throws a TypeError (network-level failure), this module
 * tries to figure out *why* — offline, corporate firewall, server down, etc.
 * — and returns user-friendly, maritime-specific messaging.
 */

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

export type NetworkDiagnosis =
  | 'offline'
  | 'firewall_blocked'
  | 'server_down'
  | 'unknown'

export interface NetworkErrorMessage {
  title: string
  message: string
  action?: string
}

/**
 * Probe the network to determine the most likely cause of a fetch failure.
 *
 * 1. navigator.onLine === false  →  offline
 * 2. Can reach a public endpoint (google) but NOT the API  →  firewall_blocked
 * 3. Cannot reach anything  →  offline (or very restricted network)
 * 4. Fallback  →  unknown
 */
export async function diagnoseNetworkError(): Promise<NetworkDiagnosis> {
  // Quick check: browser says we're offline
  if (typeof navigator !== 'undefined' && !navigator.onLine) {
    return 'offline'
  }

  // Probe a well-known public URL (tiny, fast, no CORS issues with opaque response)
  const canReachPublic = await probe('https://www.google.com/generate_204')

  // Probe our own API health endpoint
  const canReachApi = await probe(`${API_URL}/health`)

  if (canReachApi) {
    // API is reachable — the original error was transient
    return 'unknown'
  }

  if (canReachPublic && !canReachApi) {
    // Internet works but our API is blocked
    return 'firewall_blocked'
  }

  if (!canReachPublic && !canReachApi) {
    return 'offline'
  }

  return 'unknown'
}

/** Fire-and-forget fetch with a tight timeout. Returns true if *any* response comes back. */
async function probe(url: string): Promise<boolean> {
  try {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), 4000)
    await fetch(url, { method: 'HEAD', mode: 'no-cors', signal: controller.signal })
    clearTimeout(timer)
    return true
  } catch {
    return false
  }
}

/**
 * Return user-facing copy for a given diagnosis.
 */
export function getNetworkErrorMessage(diagnosis: NetworkDiagnosis): NetworkErrorMessage {
  switch (diagnosis) {
    case 'offline':
      return {
        title: 'No internet connection',
        message:
          'Your device appears to be offline. Check your Wi-Fi or cellular connection and try again.',
        action: 'Retry when connected',
      }

    case 'firewall_blocked':
      return {
        title: 'Connection blocked',
        message:
          'Your network can reach the internet but RegKnot is being blocked — likely by a shipboard firewall or corporate network filter.',
        action: 'Ask your IT administrator to whitelist regknots.com',
      }

    case 'server_down':
      return {
        title: 'Service temporarily unavailable',
        message:
          'The RegKnot server is not responding. This is usually brief — please try again in a few minutes.',
        action: 'Try again shortly',
      }

    case 'unknown':
    default:
      return {
        title: 'Connection error',
        message:
          'Unable to reach RegKnot. Please check your connection and try again.',
        action: 'Retry',
      }
  }
}

/** Whitelist text for IT / firewall administrators. */
export const WHITELIST_TEXT = `RegKnot Maritime Compliance Platform — Firewall Whitelist Request

Please allow outbound HTTPS (port 443) traffic to the following domain:

  • regknots.com

This is required for the RegKnot maritime compliance application used by crew onboard. The service uses standard HTTPS only — no unusual ports or protocols.

If you use domain-based filtering, add:
  regknots.com
  *.regknots.com

If you use IP-based filtering, the current server IP is:
  68.183.130.3

For questions, contact support@regknots.com`
