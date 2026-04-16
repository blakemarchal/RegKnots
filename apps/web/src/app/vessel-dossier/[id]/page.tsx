'use client'

import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import AuthGuard from '@/components/AuthGuard'
import { AppHeader } from '@/components/AppHeader'
import { apiRequest } from '@/lib/api'

interface VesselProfile {
  name: string
  vessel_type: string
  gross_tonnage: number | null
  route_types: string[]
  flag_state: string | null
  subchapter: string | null
  manning_requirement: string | null
  route_limitations: string | null
  inspection_certificate_type: string | null
  official_number: string | null
  imo_number: string | null
  call_sign: string | null
  hull_material: string | null
  expiration_date: string | null
  max_persons: string | null
  lifesaving_equipment: string | null
  fire_equipment: string | null
  conditions_of_operation: string | null
  profile_enriched_at: string | null
}

interface CredentialSummary {
  id: string
  credential_type: string
  title: string
  expiry_date: string | null
  days_remaining: number | null
}

interface DocumentSummary {
  id: string
  document_type: string
  filename: string
  extraction_status: string
  created_at: string
}

interface LogSummary {
  total_entries: number
  categories: Record<string, number>
  latest_entry_date: string | null
}

interface ChecklistSummary {
  exists: boolean
  item_count: number
  checked_count: number
  generated_at: string | null
  user_edits: number
}

interface ChatSummary {
  total_conversations: number
  total_messages: number
  last_active: string | null
  top_topics: string[]
}

interface VesselDossier {
  vessel_id: string
  profile: VesselProfile
  credentials: CredentialSummary[]
  documents: DocumentSummary[]
  compliance_log: LogSummary
  psc_checklist: ChecklistSummary
  chat_activity: ChatSummary
}

const ROUTE_LABEL: Record<string, string> = {
  inland: 'Inland', coastal: 'Coastal', international: 'International',
}

const CRED_TYPE_LABEL: Record<string, string> = {
  mmc: 'MMC', stcw: 'STCW', medical: 'Medical', twic: 'TWIC', other: 'Other',
}

const DOC_TYPE_LABEL: Record<string, string> = {
  coi: 'COI', safety_equipment: 'Safety Equipment', safety_construction: 'Safety Construction',
  safety_radio: 'Safety Radio', isps: 'ISPS', ism: 'ISM', other: 'Other',
}

function urgencyColor(days: number | null): string {
  if (days === null) return 'text-[#6b7594]'
  if (days < 0) return 'text-red-400'
  if (days <= 7) return 'text-red-400'
  if (days <= 30) return 'text-amber-400'
  if (days <= 90) return 'text-yellow-400'
  return 'text-[#2dd4bf]'
}

function DossierContent() {
  const params = useParams()
  const router = useRouter()
  const vesselId = params.id as string
  const [dossier, setDossier] = useState<VesselDossier | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    apiRequest<VesselDossier>(`/dossier/${vesselId}`)
      .then(setDossier)
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load'))
      .finally(() => setLoading(false))
  }, [vesselId])

  if (loading) {
    return (
      <div className="flex flex-col h-dvh bg-[#0a0e1a]">
        <AppHeader title="Vessel Dossier" />
        <main className="flex-1 overflow-y-auto px-4 py-6">
          <div className="max-w-lg mx-auto flex flex-col gap-4">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="h-32 bg-[#111827] border border-white/8 rounded-xl animate-pulse" />
            ))}
          </div>
        </main>
      </div>
    )
  }

  if (error || !dossier) {
    return (
      <div className="flex flex-col h-dvh bg-[#0a0e1a]">
        <AppHeader title="Vessel Dossier" />
        <main className="flex-1 flex items-center justify-center px-4">
          <div className="bg-[#111827] border border-white/8 rounded-xl p-8 max-w-sm text-center">
            <p className="font-mono text-sm text-red-400 mb-2">Failed to load dossier</p>
            <p className="font-mono text-xs text-[#6b7594]">{error}</p>
          </div>
        </main>
      </div>
    )
  }

  const { profile: p, credentials, documents, compliance_log: log, psc_checklist: psc, chat_activity: chat } = dossier

  const profileFields: [string, string | number | null | undefined][] = [
    ['Vessel Type', p.vessel_type],
    ['Gross Tonnage', p.gross_tonnage],
    ['Routes', p.route_types.map((r) => ROUTE_LABEL[r] ?? r).join(', ')],
    ['Flag State', p.flag_state],
    ['Subchapter', p.subchapter],
    ['Official Number', p.official_number],
    ['IMO Number', p.imo_number],
    ['Call Sign', p.call_sign],
    ['Hull Material', p.hull_material],
    ['Certificate Type', p.inspection_certificate_type],
    ['Certificate Expiration', p.expiration_date],
    ['Manning Requirement', p.manning_requirement],
    ['Route Limitations', p.route_limitations],
    ['Max Persons', p.max_persons],
  ]

  // Count non-null profile fields for completeness
  const totalProfileFields = profileFields.length
  const filledProfileFields = profileFields.filter(([_, v]) => v != null && String(v).trim() !== '').length
  const completenessPercent = Math.round((filledProfileFields / totalProfileFields) * 100)

  return (
    <div className="flex flex-col h-dvh bg-[#0a0e1a]">
      <AppHeader title="Vessel Dossier" />

      <main className="flex-1 overflow-y-auto px-4 py-6">
        <div className="max-w-lg mx-auto flex flex-col gap-5">

          {/* Header */}
          <section className="bg-[#111827] border border-white/8 rounded-xl p-5">
            <p className="font-mono text-xs text-[#6b7594] uppercase tracking-wider">
              What RegKnot Knows About
            </p>
            <h2 className="font-display text-2xl font-bold text-[#f0ece4] mt-1">{p.name}</h2>
            <div className="flex items-center gap-3 mt-3">
              <div className="flex-1">
                <div className="w-full bg-white/5 rounded-full h-2">
                  <div
                    className="h-full bg-[#2dd4bf] rounded-full transition-all"
                    style={{ width: `${completenessPercent}%` }}
                  />
                </div>
              </div>
              <span className="font-mono text-xs text-[#6b7594]">
                {completenessPercent}% complete
              </span>
            </div>
            {p.profile_enriched_at && (
              <p className="font-mono text-[10px] text-[#6b7594] mt-2">
                Last enriched: {new Date(p.profile_enriched_at).toLocaleDateString()}
              </p>
            )}
          </section>

          {/* Vessel Profile Details */}
          <section className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <p className="font-mono text-xs text-[#2dd4bf] uppercase tracking-wider">Profile</p>
              <button
                onClick={() => router.push(`/account/vessel/${vesselId}`)}
                className="font-mono text-[10px] text-[#2dd4bf] hover:underline"
              >
                Edit
              </button>
            </div>
            {profileFields.map(([label, value]) => (
              <div key={label} className="flex items-baseline gap-2">
                <span className="font-mono text-[10px] text-[#6b7594] shrink-0 w-32">{label}</span>
                <span className={`font-mono text-xs ${value ? 'text-[#f0ece4]' : 'text-[#6b7594]/40 italic'}`}>
                  {value ? String(value) : 'Not set'}
                </span>
              </div>
            ))}
            {(p.lifesaving_equipment || p.fire_equipment) && (
              <div className="mt-2 pt-2 border-t border-white/5">
                {p.lifesaving_equipment && (
                  <div className="mb-2">
                    <p className="font-mono text-[10px] text-[#6b7594]">Lifesaving Equipment</p>
                    <p className="font-mono text-xs text-[#f0ece4]/80 mt-0.5">{p.lifesaving_equipment}</p>
                  </div>
                )}
                {p.fire_equipment && (
                  <div>
                    <p className="font-mono text-[10px] text-[#6b7594]">Fire Equipment</p>
                    <p className="font-mono text-xs text-[#f0ece4]/80 mt-0.5">{p.fire_equipment}</p>
                  </div>
                )}
              </div>
            )}
            {p.conditions_of_operation && (
              <div className="mt-2 pt-2 border-t border-white/5">
                <p className="font-mono text-[10px] text-[#6b7594]">Conditions of Operation</p>
                <p className="font-mono text-xs text-[#f0ece4]/80 mt-0.5">{p.conditions_of_operation}</p>
              </div>
            )}
          </section>

          {/* Credentials */}
          <section className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <p className="font-mono text-xs text-[#2dd4bf] uppercase tracking-wider">
                Credentials ({credentials.length})
              </p>
              <button
                onClick={() => router.push('/credentials')}
                className="font-mono text-[10px] text-[#2dd4bf] hover:underline"
              >
                Manage
              </button>
            </div>
            {credentials.length === 0 ? (
              <p className="font-mono text-xs text-[#6b7594]/50 italic">No credentials tracked</p>
            ) : (
              credentials.map((c) => (
                <div key={c.id} className="flex items-center justify-between py-1">
                  <div className="min-w-0 flex-1">
                    <p className="font-mono text-xs text-[#f0ece4]">{c.title}</p>
                    <p className="font-mono text-[10px] text-[#6b7594]">{CRED_TYPE_LABEL[c.credential_type] ?? c.credential_type}</p>
                  </div>
                  <span className={`font-mono text-[10px] font-bold shrink-0 ${urgencyColor(c.days_remaining)}`}>
                    {c.days_remaining === null ? 'No expiry' : c.days_remaining < 0 ? `Expired ${Math.abs(c.days_remaining)}d ago` : `${c.days_remaining}d`}
                  </span>
                </div>
              ))
            )}
          </section>

          {/* Documents */}
          <section className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-2">
            <p className="font-mono text-xs text-[#2dd4bf] uppercase tracking-wider">
              Documents ({documents.length})
            </p>
            {documents.length === 0 ? (
              <p className="font-mono text-xs text-[#6b7594]/50 italic">No documents uploaded</p>
            ) : (
              documents.map((d) => (
                <div key={d.id} className="flex items-center justify-between py-1">
                  <div className="min-w-0 flex-1">
                    <p className="font-mono text-xs text-[#f0ece4] truncate">{d.filename}</p>
                    <p className="font-mono text-[10px] text-[#6b7594]">{DOC_TYPE_LABEL[d.document_type] ?? d.document_type}</p>
                  </div>
                  <span className={`font-mono text-[10px] shrink-0 ${
                    d.extraction_status === 'confirmed' ? 'text-[#2dd4bf]' :
                    d.extraction_status === 'failed' ? 'text-red-400' :
                    'text-[#6b7594]'
                  }`}>
                    {d.extraction_status}
                  </span>
                </div>
              ))
            )}
          </section>

          {/* PSC Checklist */}
          <section className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <p className="font-mono text-xs text-[#2dd4bf] uppercase tracking-wider">PSC Checklist</p>
              <button
                onClick={() => router.push('/psc-checklist')}
                className="font-mono text-[10px] text-[#2dd4bf] hover:underline"
              >
                {psc.exists ? 'View' : 'Generate'}
              </button>
            </div>
            {psc.exists ? (
              <div className="flex flex-col gap-1">
                <div className="flex items-center gap-3">
                  <div className="flex-1">
                    <div className="w-full bg-white/5 rounded-full h-1.5">
                      <div
                        className="h-full bg-[#2dd4bf] rounded-full transition-all"
                        style={{ width: `${psc.item_count > 0 ? (psc.checked_count / psc.item_count) * 100 : 0}%` }}
                      />
                    </div>
                  </div>
                  <span className="font-mono text-[10px] text-[#6b7594]">
                    {psc.checked_count}/{psc.item_count} checked
                  </span>
                </div>
                {psc.generated_at && (
                  <p className="font-mono text-[10px] text-[#6b7594]">
                    Generated {new Date(psc.generated_at).toLocaleDateString()}
                    {psc.user_edits > 0 && <> · {psc.user_edits} edit{psc.user_edits !== 1 ? 's' : ''}</>}
                  </p>
                )}
              </div>
            ) : (
              <p className="font-mono text-xs text-[#6b7594]/50 italic">No checklist generated yet</p>
            )}
          </section>

          {/* Compliance Log */}
          <section className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <p className="font-mono text-xs text-[#2dd4bf] uppercase tracking-wider">
                Compliance Log ({log.total_entries} entries)
              </p>
              <button
                onClick={() => router.push('/log')}
                className="font-mono text-[10px] text-[#2dd4bf] hover:underline"
              >
                View
              </button>
            </div>
            {log.total_entries === 0 ? (
              <p className="font-mono text-xs text-[#6b7594]/50 italic">No log entries for this vessel</p>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(log.categories).map(([cat, count]) => (
                  <span key={cat} className="font-mono text-[10px] px-2 py-0.5 rounded-md bg-[#2dd4bf]/10 text-[#2dd4bf] border border-[#2dd4bf]/20">
                    {cat}: {count}
                  </span>
                ))}
              </div>
            )}
            {log.latest_entry_date && (
              <p className="font-mono text-[10px] text-[#6b7594]">
                Latest: {log.latest_entry_date}
              </p>
            )}
          </section>

          {/* Chat Activity */}
          <section className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-2">
            <p className="font-mono text-xs text-[#2dd4bf] uppercase tracking-wider">Chat Activity</p>
            {chat.total_conversations === 0 ? (
              <p className="font-mono text-xs text-[#6b7594]/50 italic">No conversations with this vessel selected</p>
            ) : (
              <>
                <div className="flex items-center gap-4 font-mono text-xs text-[#f0ece4]/80">
                  <span>{chat.total_conversations} conversation{chat.total_conversations !== 1 ? 's' : ''}</span>
                  <span>{chat.total_messages} message{chat.total_messages !== 1 ? 's' : ''}</span>
                </div>
                {chat.last_active && (
                  <p className="font-mono text-[10px] text-[#6b7594]">
                    Last active: {new Date(chat.last_active).toLocaleDateString()}
                  </p>
                )}
                {chat.top_topics.length > 0 && (
                  <div className="mt-1">
                    <p className="font-mono text-[10px] text-[#6b7594] mb-1">Recent topics:</p>
                    <div className="flex flex-col gap-0.5">
                      {chat.top_topics.map((t, i) => (
                        <p key={i} className="font-mono text-[10px] text-[#f0ece4]/70 truncate">• {t}</p>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
          </section>

          {/* Footer */}
          <p className="font-mono text-[10px] text-[#6b7594]/50 text-center pb-4">
            This dossier aggregates data from vessel profile, documents, credentials,
            compliance logs, PSC checklists, and chat history.
          </p>

        </div>
      </main>
    </div>
  )
}

export default function VesselDossierPage() {
  return (
    <AuthGuard>
      <DossierContent />
    </AuthGuard>
  )
}
