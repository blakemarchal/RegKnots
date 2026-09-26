/**
 * Vessel flag options (2026-09-26).
 *
 * Retrieval scopes answers to the vessel's flag (rag/jurisdiction.py
 * flag_to_jurisdiction matches these names). Vessels were created with flag
 * "Unknown" until now, which switches that scoping off.
 */

export const FLAG_OPTIONS: readonly string[] = [
  'United States',
  'Antigua and Barbuda',
  'Australia',
  'Bahamas',
  'Belgium',
  'Bermuda',
  'Canada',
  'Cayman Islands',
  'China',
  'Cyprus',
  'Denmark',
  'France',
  'Germany',
  'Gibraltar',
  'Greece',
  'Hong Kong',
  'India',
  'Ireland',
  'Isle of Man',
  'Italy',
  'Japan',
  'Liberia',
  'Malta',
  'Marshall Islands',
  'Netherlands',
  'New Zealand',
  'Norway',
  'Panama',
  'Philippines',
  'Portugal',
  'Singapore',
  'South Korea',
  'Spain',
  'United Kingdom',
]

/** The user's primary jurisdiction (users.jurisdiction_focus) as a flag. */
const FOCUS_TO_FLAG: Record<string, string> = {
  us: 'United States',
  uk: 'United Kingdom',
  au: 'Australia',
  no: 'Norway',
  sg: 'Singapore',
  hk: 'Hong Kong',
  bs: 'Bahamas',
  lr: 'Liberia',
  mh: 'Marshall Islands',
}

export function flagForFocus(focus: string | null | undefined): string | null {
  return (focus && FOCUS_TO_FLAG[focus]) || null
}

export function isFlagUnknown(flag: string | null | undefined): boolean {
  const f = (flag ?? '').trim().toLowerCase()
  return !f || ['unknown', 'none', 'n/a', 'tbd', '?'].includes(f)
}

/** "Not now" on the chat's flag prompt, remembered per vessel in this browser. */
function dismissKey(vesselId: string): string {
  return `rk_flag_prompt_dismissed:${vesselId}`
}

export function readFlagPromptDismissed(vesselId: string): boolean {
  if (typeof window === 'undefined') return false
  try {
    return window.localStorage.getItem(dismissKey(vesselId)) === '1'
  } catch {
    return false
  }
}

export function writeFlagPromptDismissed(vesselId: string): void {
  try {
    window.localStorage.setItem(dismissKey(vesselId), '1')
  } catch {
    // private mode / blocked storage: the prompt stays dismissed for this session only
  }
}
