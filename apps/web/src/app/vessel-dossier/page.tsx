'use client'

import { useEffect, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import AuthGuard from '@/components/AuthGuard'
import { AppHeader } from '@/components/AppHeader'
import { apiRequest } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'

// ── Types ─────────────────────────────────────────────────────────────────

interface VesselProfile {
  name: string; vessel_type: string; gross_tonnage: number | null
  route_types: string[]; flag_state: string | null; subchapter: string | null
  manning_requirement: string | null; route_limitations: string | null
  inspection_certificate_type: string | null; official_number: string | null
  imo_number: string | null; call_sign: string | null; hull_material: string | null
  expiration_date: string | null; max_persons: string | null
  lifesaving_equipment: string | null; fire_equipment: string | null
  conditions_of_operation: string | null; profile_enriched_at: string | null
}
interface CredentialSummary { id: string; credential_type: string; title: string; expiry_date: string | null; days_remaining: number | null }
interface DocumentSummary { id: string; document_type: string; filename: string; extraction_status: string; created_at: string }
interface LogSummary { total_entries: number; categories: Record<string, number>; latest_entry_date: string | null }
interface ChecklistSummary { exists: boolean; item_count: number; checked_count: number; generated_at: string | null; user_edits: number }
interface ChatSummary { total_conversations: number; total_messages: number; last_active: string | null; top_topics: string[] }
interface VesselDossier {
  vessel_id: string; profile: VesselProfile; credentials: CredentialSummary[]
  documents: DocumentSummary[]; compliance_log: LogSummary
  psc_checklist: ChecklistSummary; chat_activity: ChatSummary
}

const ROUTE_LABEL: Record<string, string> = { inland: 'Inland', coastal: 'Coastal', international: 'International' }
const CRED_TYPE_LABEL: Record<string, string> = { mmc: 'MMC', stcw: 'STCW', medical: 'Medical', twic: 'TWIC', other: 'Other' }
const DOC_TYPE_LABEL: Record<string, string> = {
  coi: 'COI', safety_equipment: 'Safety Equip', safety_construction: 'Safety Const',
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

const LAST_VESSEL_KEY = 'regknot:dossier:lastVesselId'

function readLastVessel(): string {
  if (typeof window === 'undefined') return ''
  try { return window.localStorage.getItem(LAST_VESSEL_KEY) ?? '' } catch { return '' }
}
function writeLastVessel(id: string): void {
  if (typeof window === 'undefined') return
  try { if (id) window.localStorage.setItem(LAST_VESSEL_KEY, id); else window.localStorage.removeItem(LAST_VESSEL_KEY) } catch {}
}

// ── Component ─────────────────────────────────────────────────────────────

function DossierContent() {
  const router = useRouter()
  const { vessels, activeVesselId } = useAuthStore()
  const [selectedVessel, setSelectedVessel] = useState<string>(() => readLastVessel() || activeVesselId || '')
  const [dossier, setDossier] = useState<VesselDossier | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Sync selectedVessel when store hydrates
  useEffect(() => {
    if (!selectedVessel && activeVesselId && !readLastVessel()) setSelectedVessel(activeVesselId)
  }, [activeVesselId, selectedVessel])

  useEffect(() => { writeLastVessel(selectedVessel) }, [selectedVessel])

  // Clean up stale vessel
  useEffect(() => {
    if (!selectedVessel || vessels.length === 0) return
    if (!vessels.some((v) => v.id === selectedVessel)) { setSelectedVessel(''); writeLastVessel('') }
  }, [selectedVessel, vessels])

  // Auto-select if only one vessel
  useEffect(() => {
    if (!selectedVessel && vessels.length === 1) setSelectedVessel(vessels[0].id)
  }, [vessels, selectedVessel])

  // Fetch dossier on vessel change
  useEffect(() => {
    if (!selectedVessel) { setDossier(null); return }
    let cancelled = false
    setLoading(true)
    setError(null)
    apiRequest<VesselDossier>(`/dossier/${selectedVessel}`)
      .then((d) => { if (!cancelled) setDossier(d) })
      .catch((e) => { if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [selectedVessel])

  const p = dossier?.profile
  const profileFields: [string, string | number | null | undefined][] = p ? [
    ['Vessel Type', p.vessel_type], ['Gross Tonnage', p.gross_tonnage],
    ['Routes', p.route_types.map((r) => ROUTE_LABEL[r] ?? r).join(', ')],
    ['Flag State', p.flag_state], ['Subchapter', p.subchapter],
    ['Official Number', p.official_number], ['IMO Number', p.imo_number],
    ['Call Sign', p.call_sign], ['Hull Material', p.hull_material],
    ['Certificate Type', p.inspection_certificate_type],
    ['Certificate Expiration', p.expiration_date],
    ['Manning Requirement', p.manning_requirement],
    ['Route Limitations', p.route_limitations], ['Max Persons', p.max_persons],
  ] : []
  const totalFields = profileFields.length
  const filledFields = profileFields.filter(([_, v]) => v != null && String(v).trim() !== '').length
  const pct = totalFields > 0 ? Math.round((filledFields / totalFields) * 100) : 0

  return (
    <div className="flex flex-col h-dvh bg-[#0a0e1a]">
      <AppHeader title="Vessel Dossier" />
      <main className="flex-1 overflow-y-auto px-4 py-6">
        <div className="max-w-lg mx-auto flex flex-col gap-5">

          {/* Vessel selector */}
          <section className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-3">
            <p className="font-mono text-xs text-[#6b7594] uppercase tracking-wider">What RegKnot Knows</p>
            <p className="font-mono text-xs text-[#f0ece4]/60 leading-relaxed">
              Select a vessel to see aggregated profile, credentials, documents, compliance logs, PSC checklist status, and chat activity.
            </p>
            <div className="relative">
              <select
                value={selectedVessel}
                onChange={(e) => setSelectedVessel(e.target.value)}
                className="font-mono w-full border border-white/10 rounded-lg pl-3 pr-10 py-2 text-sm
                  outline-none focus:border-[#2dd4bf] transition-colors appearance-none cursor-pointer"
                style={{ backgroundColor: '#0d1225', color: '#f0ece4' }}
              >
                <option value="" style={{ backgroundColor: '#111827', color: '#f0ece4' }}>Select a vessel</option>
                {vessels.map((v) => (
                  <option key={v.id} value={v.id} style={{ backgroundColor: '#111827', color: '#f0ece4' }}>{v.name}</option>
                ))}
              </select>
              <svg className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#6b7594] pointer-events-none" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="6 9 12 15 18 9" /></svg>
            </div>
          </section>

          {/* Loading */}
          {loading && (
            <div className="flex flex-col gap-4">
              {[1, 2, 3].map((i) => <div key={i} className="h-28 bg-[#111827] border border-white/8 rounded-xl animate-pulse" />)}
            </div>
          )}

          {error && (
            <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4">
              <p className="font-mono text-xs text-red-400">{error}</p>
            </div>
          )}

          {/* No vessel selected */}
          {!selectedVessel && !loading && vessels.length === 0 && (
            <section className="bg-[#111827] border border-white/8 rounded-xl p-8 text-center">
              <p className="font-mono text-sm text-[#6b7594] mb-2">No vessels registered</p>
              <p className="font-mono text-xs text-[#6b7594]/70">Add a vessel to see its dossier.</p>
            </section>
          )}

          {/* Dossier content */}
          {dossier && p && !loading && (
            <>
              {/* Header + completeness */}
              <section className="bg-[#111827] border border-white/8 rounded-xl p-5">
                <h2 className="font-display text-2xl font-bold text-[#f0ece4] mt-1">{p.name}</h2>
                <div className="flex items-center gap-3 mt-3">
                  <div className="flex-1"><div className="w-full bg-white/5 rounded-full h-2"><div className="h-full bg-[#2dd4bf] rounded-full transition-all" style={{ width: `${pct}%` }} /></div></div>
                  <span className="font-mono text-xs text-[#6b7594]">{pct}% complete</span>
                </div>
                {p.profile_enriched_at && <p className="font-mono text-[10px] text-[#6b7594] mt-2">Last enriched: {new Date(p.profile_enriched_at).toLocaleDateString()}</p>}
              </section>

              {/* Profile */}
              <section className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-2">
                <div className="flex items-center justify-between">
                  <p className="font-mono text-xs text-[#2dd4bf] uppercase tracking-wider">Profile</p>
                  <button onClick={() => router.push(`/account/vessel/${dossier.vessel_id}`)} className="font-mono text-[10px] text-[#2dd4bf] hover:underline">Edit</button>
                </div>
                {profileFields.map(([label, value]) => (
                  <div key={label} className="flex items-baseline gap-2">
                    <span className="font-mono text-[10px] text-[#6b7594] shrink-0 w-32">{label}</span>
                    <span className={`font-mono text-xs whitespace-pre-line ${value ? 'text-[#f0ece4]' : 'text-[#6b7594]/40 italic'}`}>{value ? String(value) : 'Not set'}</span>
                  </div>
                ))}
                {(p.lifesaving_equipment || p.fire_equipment) && (
                  <div className="mt-2 pt-2 border-t border-white/5">
                    {p.lifesaving_equipment && <div className="mb-2"><p className="font-mono text-[10px] text-[#6b7594]">Lifesaving Equipment</p><p className="font-mono text-xs text-[#f0ece4]/80 mt-0.5">{p.lifesaving_equipment}</p></div>}
                    {p.fire_equipment && <div><p className="font-mono text-[10px] text-[#6b7594]">Fire Equipment</p><p className="font-mono text-xs text-[#f0ece4]/80 mt-0.5">{p.fire_equipment}</p></div>}
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
                  <p className="font-mono text-xs text-[#2dd4bf] uppercase tracking-wider">Credentials ({dossier.credentials.length})</p>
                  <button onClick={() => router.push('/credentials')} className="font-mono text-[10px] text-[#2dd4bf] hover:underline">Manage</button>
                </div>
                {dossier.credentials.length === 0
                  ? <p className="font-mono text-xs text-[#6b7594]/50 italic">No credentials tracked</p>
                  : dossier.credentials.map((c) => (
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
                }
              </section>

              {/* Documents */}
              <section className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-2">
                <p className="font-mono text-xs text-[#2dd4bf] uppercase tracking-wider">Documents ({dossier.documents.length})</p>
                {dossier.documents.length === 0
                  ? <p className="font-mono text-xs text-[#6b7594]/50 italic">No documents uploaded</p>
                  : dossier.documents.map((d) => (
                    <div key={d.id} className="flex items-center justify-between py-1">
                      <div className="min-w-0 flex-1">
                        <p className="font-mono text-xs text-[#f0ece4] truncate">{d.filename}</p>
                        <p className="font-mono text-[10px] text-[#6b7594]">{DOC_TYPE_LABEL[d.document_type] ?? d.document_type}</p>
                      </div>
                      <span className={`font-mono text-[10px] shrink-0 ${d.extraction_status === 'confirmed' ? 'text-[#2dd4bf]' : d.extraction_status === 'failed' ? 'text-red-400' : 'text-[#6b7594]'}`}>{d.extraction_status}</span>
                    </div>
                  ))
                }
              </section>

              {/* PSC Checklist */}
              <section className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-2">
                <div className="flex items-center justify-between">
                  <p className="font-mono text-xs text-[#2dd4bf] uppercase tracking-wider">PSC Checklist</p>
                  <button onClick={() => router.push('/psc-checklist')} className="font-mono text-[10px] text-[#2dd4bf] hover:underline">{dossier.psc_checklist.exists ? 'View' : 'Generate'}</button>
                </div>
                {dossier.psc_checklist.exists ? (
                  <div className="flex flex-col gap-1">
                    <div className="flex items-center gap-3">
                      <div className="flex-1"><div className="w-full bg-white/5 rounded-full h-1.5"><div className="h-full bg-[#2dd4bf] rounded-full transition-all" style={{ width: `${dossier.psc_checklist.item_count > 0 ? (dossier.psc_checklist.checked_count / dossier.psc_checklist.item_count) * 100 : 0}%` }} /></div></div>
                      <span className="font-mono text-[10px] text-[#6b7594]">{dossier.psc_checklist.checked_count}/{dossier.psc_checklist.item_count} checked</span>
                    </div>
                    {dossier.psc_checklist.generated_at && <p className="font-mono text-[10px] text-[#6b7594]">Generated {new Date(dossier.psc_checklist.generated_at).toLocaleDateString()}{dossier.psc_checklist.user_edits > 0 && <> · {dossier.psc_checklist.user_edits} edit{dossier.psc_checklist.user_edits !== 1 ? 's' : ''}</>}</p>}
                  </div>
                ) : <p className="font-mono text-xs text-[#6b7594]/50 italic">No checklist generated yet</p>}
              </section>

              {/* Compliance Log */}
              <section className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-2">
                <div className="flex items-center justify-between">
                  <p className="font-mono text-xs text-[#2dd4bf] uppercase tracking-wider">Compliance Log ({dossier.compliance_log.total_entries})</p>
                  <button onClick={() => router.push('/log')} className="font-mono text-[10px] text-[#2dd4bf] hover:underline">View</button>
                </div>
                {dossier.compliance_log.total_entries === 0
                  ? <p className="font-mono text-xs text-[#6b7594]/50 italic">No log entries for this vessel</p>
                  : <div className="flex flex-wrap gap-1.5">{Object.entries(dossier.compliance_log.categories).map(([cat, count]) => (
                    <span key={cat} className="font-mono text-[10px] px-2 py-0.5 rounded-md bg-[#2dd4bf]/10 text-[#2dd4bf] border border-[#2dd4bf]/20">{cat}: {count}</span>
                  ))}</div>
                }
                {dossier.compliance_log.latest_entry_date && <p className="font-mono text-[10px] text-[#6b7594]">Latest: {dossier.compliance_log.latest_entry_date}</p>}
              </section>

              {/* Chat Activity */}
              <section className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-2">
                <p className="font-mono text-xs text-[#2dd4bf] uppercase tracking-wider">Chat Activity</p>
                {dossier.chat_activity.total_conversations === 0
                  ? <p className="font-mono text-xs text-[#6b7594]/50 italic">No conversations with this vessel selected</p>
                  : <>
                    <div className="flex items-center gap-4 font-mono text-xs text-[#f0ece4]/80">
                      <span>{dossier.chat_activity.total_conversations} conversation{dossier.chat_activity.total_conversations !== 1 ? 's' : ''}</span>
                      <span>{dossier.chat_activity.total_messages} message{dossier.chat_activity.total_messages !== 1 ? 's' : ''}</span>
                    </div>
                    {dossier.chat_activity.last_active && <p className="font-mono text-[10px] text-[#6b7594]">Last active: {new Date(dossier.chat_activity.last_active).toLocaleDateString()}</p>}
                    {dossier.chat_activity.top_topics.length > 0 && (
                      <div className="mt-1">
                        <p className="font-mono text-[10px] text-[#6b7594] mb-1">Recent topics:</p>
                        {dossier.chat_activity.top_topics.map((t, i) => <p key={i} className="font-mono text-[10px] text-[#f0ece4]/70 truncate">• {t}</p>)}
                      </div>
                    )}
                  </>
                }
              </section>

              <p className="font-mono text-[10px] text-[#6b7594]/50 text-center pb-4">
                Aggregated from vessel profile, documents, credentials, compliance logs, PSC checklists, and chat history.
              </p>
            </>
          )}
        </div>
      </main>
    </div>
  )
}

export default function VesselDossierPage() {
  return <AuthGuard><DossierContent /></AuthGuard>
}
