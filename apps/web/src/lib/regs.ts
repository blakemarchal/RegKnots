// 2026-10-14 — the public regulation pages (/regs): server-side reads of the
// API's /public/regs endpoints (apps/api/app/routers/public_regs.py). Pages
// are cached and refreshed hourly (ISR); a failed read renders "not found"
// for a page and an empty list for an index, never an error page.

// On the server the API is reached directly (same host in production); the
// public URL is the fallback for local development.
const API = process.env.API_INTERNAL_URL
  || (process.env.NODE_ENV === 'production' ? 'http://127.0.0.1:8000' : process.env.NEXT_PUBLIC_API_URL)
  || 'http://localhost:8000'

export const REVALIDATE_SECONDS = 3600

export interface RegCollection {
  slug: string
  title: string
  blurb: string
  pages: number
}

export interface RegSummary {
  slug: string
  title: string
  display_number: string
  collection: string
  meta_description: string | null
  updated_at: string
}

export interface RegRequirement {
  statement: string
  quote: string
  paragraph: string
}

export interface RegFaq {
  question: string
  answer: string
  quote: string
}

export interface RegPage {
  slug: string
  title: string
  display_number: string
  section_number: string
  section_title: string | null
  collection: string
  collection_title: string
  meta_description: string | null
  content: {
    topic: string
    summary: string
    applies_to: string
    requirements: RegRequirement[]
    faqs: RegFaq[]
    related_sections: string[]
  }
  source_text: string
  source_label: string
  source_url: string | null
  up_to_date_as_of: string | null
  updated_at: string
  related: { section_number: string; slug: string | null; url: string | null }[]
  previous: RegSummary | null
  next: RegSummary | null
}

async function get<T>(path: string): Promise<T | null> {
  try {
    const res = await fetch(`${API}${path}`, { next: { revalidate: REVALIDATE_SECONDS } })
    if (!res.ok) return null
    return (await res.json()) as T
  } catch {
    return null
  }
}

export const getCollections = async () => (await get<RegCollection[]>('/public/regs/collections')) ?? []
export const getPages = async (collection?: string) =>
  (await get<RegSummary[]>(`/public/regs${collection ? `?collection=${encodeURIComponent(collection)}` : ''}`)) ?? []
export const getPage = (slug: string) => get<RegPage>(`/public/regs/page/${encodeURIComponent(slug)}`)

/** Sign-up from a regulation page; attribution src=regs, utm_content = the page. */
export function regsSignupHref(slug: string): string {
  return `/register?src=regs&utm_content=${encodeURIComponent(slug)}`
}
