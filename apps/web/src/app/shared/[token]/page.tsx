'use client'

import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface SharedProfile {
  vessel_name: string
  vessel_type: string
  gross_tonnage: number | null
  route_types: string[]
  flag_state: string | null
  subchapter: string | null
  manning_requirement: string | null
  route_limitations: string | null
  inspection_certificate_type: string | null
  official_number: string | null
  call_sign: string | null
  expiration_date: string | null
  max_persons: string | null
}

const ROUTE_LABEL: Record<string, string> = {
  inland: 'Inland',
  coastal: 'Coastal',
  international: 'International',
}

export default function SharedProfilePage() {
  const params = useParams()
  const token = params.token as string
  const [profile, setProfile] = useState<SharedProfile | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch(`${API_URL}/export/shared/${token}`)
      .then(async (res) => {
        if (!res.ok) throw new Error('Profile not found')
        return res.json()
      })
      .then(setProfile)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [token])

  if (loading) {
    return (
      <div className="min-h-screen bg-[#0a0e1a] flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-[#2dd4bf] border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  if (error || !profile) {
    return (
      <div className="min-h-screen bg-[#0a0e1a] flex items-center justify-center px-4">
        <div className="bg-[#111827] border border-white/8 rounded-xl p-8 max-w-sm w-full text-center">
          <p className="font-mono text-sm text-[#f0ece4] mb-2">Profile not found</p>
          <p className="font-mono text-xs text-[#6b7594]">
            This compliance profile link may have expired or been removed.
          </p>
        </div>
      </div>
    )
  }

  const fields: [string, string | number | null | undefined][] = [
    ['Vessel Type', profile.vessel_type],
    ['Gross Tonnage', profile.gross_tonnage],
    ['Routes', profile.route_types.map((r) => ROUTE_LABEL[r] ?? r).join(', ')],
    ['Flag State', profile.flag_state],
    ['Subchapter', profile.subchapter],
    ['Official Number', profile.official_number],
    ['Call Sign', profile.call_sign],
    ['Certificate Type', profile.inspection_certificate_type],
    ['Certificate Expiration', profile.expiration_date],
    ['Manning Requirement', profile.manning_requirement],
    ['Route Limitations', profile.route_limitations],
    ['Max Persons', profile.max_persons],
  ]

  return (
    <div className="min-h-screen bg-[#0a0e1a] px-4 py-8">
      <div className="max-w-md mx-auto flex flex-col gap-5">
        {/* Header */}
        <div className="flex items-center gap-2.5">
          <svg className="w-6 h-6 text-[#2dd4bf] flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <circle cx="12" cy="12" r="10" />
            <path d="M12 2v4M12 18v4M2 12h4M18 12h4" strokeLinecap="round" />
            <path d="M12 8l1.5 3.5L12 16l-1.5-4.5L12 8z" fill="currentColor" stroke="none" />
          </svg>
          <h1 className="font-display text-xl font-bold text-[#f0ece4] tracking-wide">
            RegKnot
          </h1>
        </div>

        {/* Vessel profile card */}
        <section className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-4">
          <div>
            <p className="font-mono text-xs text-[#6b7594] uppercase tracking-wider">Vessel Compliance Profile</p>
            <h2 className="font-display text-2xl font-bold text-[#f0ece4] mt-1">{profile.vessel_name}</h2>
          </div>

          <div className="flex flex-col gap-2">
            {fields.map(([label, value]) => {
              if (!value) return null
              return (
                <div key={label} className="flex items-baseline gap-2">
                  <span className="font-mono text-xs text-[#6b7594] shrink-0 w-36">{label}</span>
                  <span className="font-mono text-sm text-[#f0ece4] whitespace-pre-line">{String(value)}</span>
                </div>
              )
            })}
          </div>
        </section>

        {/* Footer */}
        <p className="font-mono text-[10px] text-[#6b7594]/50 text-center">
          Shared via RegKnot — Navigation aid only, not legal advice
        </p>
      </div>
    </div>
  )
}
