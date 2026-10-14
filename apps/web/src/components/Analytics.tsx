'use client'

// 2026-10-14 — PostHog, loaded only when NEXT_PUBLIC_POSTHOG_KEY is set
// (src/lib/analytics.ts has the privacy settings and the URL scrubber).
// Signed-in users are identified by their user id, never their email, so the
// API's funnel events (app/events.py) land on the same person. Admin
// accounts opt out on their device so internal use stays out of the numbers.

import { useEffect, useRef } from 'react'
import type { PostHog } from 'posthog-js'
import { useAuthStore } from '@/lib/auth'
import { POSTHOG_HOST, POSTHOG_KEY, scrubEventProperties } from '@/lib/analytics'

let client: Promise<PostHog | null> | null = null

function load(): Promise<PostHog | null> {
  if (!POSTHOG_KEY || typeof window === 'undefined') return Promise.resolve(null)
  if (!client) {
    client = import('posthog-js')
      .then(({ default: posthog }) => {
        posthog.init(POSTHOG_KEY, {
          api_host: POSTHOG_HOST,
          persistence: 'localStorage',
          person_profiles: 'identified_only',
          autocapture: false,
          capture_pageview: 'history_change',
          capture_pageleave: true,
          disable_session_recording: true,
          disable_surveys: true,
          respect_dnt: true,
          before_send: (event) => {
            if (!event) return event
            scrubEventProperties(event.properties)
            scrubEventProperties(event.$set as Record<string, unknown> | undefined)
            scrubEventProperties(event.$set_once as Record<string, unknown> | undefined)
            return event
          },
        })
        return posthog
      })
      .catch(() => null)
  }
  return client
}

export function Analytics() {
  const user = useAuthStore((s) => s.user)
  const identified = useRef<string | null>(null)

  useEffect(() => {
    void load()
  }, [])

  useEffect(() => {
    void load().then((posthog) => {
      if (!posthog) return
      if (user) {
        if (user.is_admin) {
          posthog.opt_out_capturing()
          return
        }
        if (identified.current !== user.id) {
          posthog.identify(user.id, { role: user.role })
          identified.current = user.id
        }
      } else if (identified.current) {
        posthog.reset()
        identified.current = null
      }
    })
  }, [user])

  return null
}
