'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import AuthGuard from '@/components/AuthGuard'
import { AppHeader } from '@/components/AppHeader'
import { apiRequest } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'

const LOADING_MESSAGES = [
  'Loading vessel profile...',
  'Matching applicable regulations...',
  'Reviewing safety equipment requirements...',
  'Reviewing fire safety items...',
  'Checking manning & certification rules...',
  'Adding ISM and ISPS items...',
  'Drafting checklist...',
  'Finalizing citations...',
]

interface ChecklistItem {
  category: string
  item: string
  regulation: string
  notes: string | null
}

interface PSCChecklist {
  vessel_name: string
  vessel_type: string
  checklist: ChecklistItem[]
  checked_indices: number[]
  generated_at: string
}

interface ProfileIncompleteError {
  detail: string
  missing_fields: string[]
  completeness_score: number
  required_score: number
}

function formatRelativeDate(iso: string): string {
  const then = new Date(iso).getTime()
  const diffSec = Math.floor((Date.now() - then) / 1000)
  if (diffSec < 60) return 'just now'
  const diffMin = Math.floor(diffSec / 60)
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr}h ago`
  const diffDay = Math.floor(diffHr / 24)
  if (diffDay < 30) return `${diffDay}d ago`
  return new Date(iso).toLocaleDateString()
}

function PSCContent() {
  const router = useRouter()
  const { vessels, activeVesselId } = useAuthStore()
  const [selectedVessel, setSelectedVessel] = useState(activeVesselId ?? '')
  const [checklist, setChecklist] = useState<PSCChecklist | null>(null)
  const [loading, setLoading] = useState(false)
  const [loadingSaved, setLoadingSaved] = useState(false)
  const [loadingStartedAt, setLoadingStartedAt] = useState<number | null>(null)
  const [loadingMsgIdx, setLoadingMsgIdx] = useState(0)
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [profileGap, setProfileGap] = useState<ProfileIncompleteError | null>(null)
  const [confirmRegen, setConfirmRegen] = useState(false)
  const [checked, setChecked] = useState<Set<number>>(new Set())

  // Debounced check-state save
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Cycle loading messages every 3.5s and track elapsed time
  useEffect(() => {
    if (!loading || !loadingStartedAt) return
    const tick = setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - loadingStartedAt) / 1000))
    }, 500)
    const rotate = setInterval(() => {
      setLoadingMsgIdx((i) => (i + 1) % LOADING_MESSAGES.length)
    }, 3500)
    return () => { clearInterval(tick); clearInterval(rotate) }
  }, [loading, loadingStartedAt])

  // Keep selectedVessel in sync when vessels hydrate after mount
  useEffect(() => {
    if (!selectedVessel && activeVesselId) {
      setSelectedVessel(activeVesselId)
    }
  }, [activeVesselId, selectedVessel])

  // Load saved checklist whenever selected vessel changes
  useEffect(() => {
    if (!selectedVessel) {
      setChecklist(null)
      setChecked(new Set())
      return
    }
    let cancelled = false
    setLoadingSaved(true)
    setError(null)
    setProfileGap(null)
    apiRequest<PSCChecklist | null>(`/checklists/psc/${selectedVessel}`)
      .then((saved) => {
        if (cancelled) return
        if (saved && saved.checklist && saved.checklist.length > 0) {
          setChecklist(saved)
          setChecked(new Set(saved.checked_indices || []))
        } else {
          setChecklist(null)
          setChecked(new Set())
        }
      })
      .catch(() => {
        if (cancelled) return
        setChecklist(null)
        setChecked(new Set())
      })
      .finally(() => {
        if (!cancelled) setLoadingSaved(false)
      })
    return () => { cancelled = true }
  }, [selectedVessel])

  const doGenerate = useCallback(async () => {
    if (!selectedVessel) {
      setError('Select a vessel first')
      return
    }
    setConfirmRegen(false)
    setLoading(true)
    setLoadingStartedAt(Date.now())
    setLoadingMsgIdx(0)
    setElapsedSeconds(0)
    setError(null)
    setProfileGap(null)
    setChecklist(null)
    setChecked(new Set())
    try {
      const result = await apiRequest<PSCChecklist>('/checklists/psc', {
        method: 'POST',
        body: JSON.stringify({ vessel_id: selectedVessel }),
      })
      setChecklist(result)
      setChecked(new Set(result.checked_indices || []))
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Failed to generate checklist'
      // Try to detect the 422 profile incomplete error
      try {
        // apiRequest throws an Error whose message is the JSON body for most error codes.
        const parsed = JSON.parse(msg)
        if (parsed?.detail && typeof parsed.detail === 'object' && parsed.detail.missing_fields) {
          setProfileGap(parsed.detail as ProfileIncompleteError)
        } else if (parsed?.detail?.missing_fields) {
          setProfileGap(parsed.detail as ProfileIncompleteError)
        } else {
          setError(typeof parsed?.detail === 'string' ? parsed.detail : msg)
        }
      } catch {
        setError(msg)
      }
    } finally {
      setLoading(false)
      setLoadingStartedAt(null)
    }
  }, [selectedVessel])

  function handleGenerateClick() {
    if (checklist) {
      setConfirmRegen(true)
      return
    }
    doGenerate()
  }

  function saveChecks(next: Set<number>) {
    if (!selectedVessel) return
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
    saveTimerRef.current = setTimeout(() => {
      apiRequest(`/checklists/psc/${selectedVessel}/checks`, {
        method: 'PATCH',
        body: JSON.stringify({ checked_indices: Array.from(next) }),
      }).catch(() => {
        // Silent — state stays local even if save fails
      })
    }, 600)
  }

  function toggleCheck(idx: number) {
    setChecked((prev) => {
      const next = new Set(prev)
      if (next.has(idx)) next.delete(idx)
      else next.add(idx)
      saveChecks(next)
      return next
    })
  }

  // Group items by category
  const grouped: Record<string, { item: ChecklistItem; idx: number }[]> = {}
  if (checklist) {
    checklist.checklist.forEach((item, idx) => {
      if (!grouped[item.category]) grouped[item.category] = []
      grouped[item.category].push({ item, idx })
    })
  }

  const totalItems = checklist?.checklist.length ?? 0
  const checkedCount = checked.size

  return (
    <div className="flex flex-col h-dvh bg-[#0a0e1a]">
      <AppHeader title="PSC Checklist" />

      <main className="flex-1 overflow-y-auto px-4 py-6">
        <div className="max-w-lg mx-auto flex flex-col gap-5">

          {/* Vessel selector + generate */}
          <section className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-4 print:hidden">
            <p className="font-mono text-xs text-[#6b7594] uppercase tracking-wider">
              PSC Inspection Readiness
            </p>
            <p className="font-mono text-xs text-[#f0ece4]/60 leading-relaxed">
              Generate a Port State Control inspection checklist tailored to your vessel profile and applicable regulations. Checklists are saved per vessel — your progress persists across sessions.
            </p>

            <div className="flex flex-col gap-1">
              <label className="font-mono text-xs text-[#6b7594]">Vessel</label>
              <select
                value={selectedVessel}
                onChange={(e) => setSelectedVessel(e.target.value)}
                className="font-mono w-full border border-white/10 rounded-lg px-3 py-2 text-sm
                  outline-none focus:border-[#2dd4bf] transition-colors"
                style={{ backgroundColor: '#0d1225', color: '#f0ece4' }}
              >
                <option value="" style={{ backgroundColor: '#111827', color: '#f0ece4' }}>
                  Select a vessel
                </option>
                {vessels.map((v) => (
                  <option key={v.id} value={v.id} style={{ backgroundColor: '#111827', color: '#f0ece4' }}>
                    {v.name}
                  </option>
                ))}
              </select>
            </div>

            {loadingSaved && selectedVessel && (
              <p className="font-mono text-xs text-[#6b7594]">Loading saved checklist…</p>
            )}

            <button
              onClick={handleGenerateClick}
              disabled={loading || !selectedVessel || loadingSaved}
              className="w-full font-mono text-sm font-bold text-[#0a0e1a] bg-[#2dd4bf]
                hover:brightness-110 disabled:opacity-50 rounded-lg py-2.5
                transition-[filter] duration-150"
            >
              {loading ? 'Generating…' : (checklist ? 'Regenerate Checklist' : 'Generate Checklist')}
            </button>

            {error && <p className="font-mono text-xs text-red-400">{error}</p>}
          </section>

          {/* Regenerate confirmation */}
          {confirmRegen && (
            <section className="bg-amber-950/40 border border-amber-500/30 rounded-xl p-5 flex flex-col gap-3 print:hidden">
              <p className="font-mono text-xs text-amber-400 uppercase tracking-wider">Replace existing checklist?</p>
              <p className="font-mono text-xs text-[#f0ece4]/80 leading-relaxed">
                This will generate a new checklist and reset your current progress ({checkedCount}/{totalItems} items checked).
              </p>
              <div className="flex items-center gap-2">
                <button
                  onClick={doGenerate}
                  className="font-mono text-sm font-bold text-[#0a0e1a] bg-amber-400
                    hover:brightness-110 rounded-lg px-4 py-2 transition-[filter] duration-150"
                >
                  Replace
                </button>
                <button
                  onClick={() => setConfirmRegen(false)}
                  className="font-mono text-sm text-[#6b7594] hover:text-[#f0ece4] px-3 py-2
                    transition-colors duration-150"
                >
                  Cancel
                </button>
              </div>
            </section>
          )}

          {/* Profile incomplete CTA */}
          {profileGap && (
            <section className="bg-[#111827] border border-amber-400/30 rounded-xl p-5 flex flex-col gap-3 print:hidden">
              <p className="font-mono text-xs text-amber-400 uppercase tracking-wider">Vessel profile too sparse</p>
              <p className="font-mono text-xs text-[#f0ece4]/80 leading-relaxed">
                {profileGap.detail}
              </p>
              {profileGap.missing_fields.length > 0 && (
                <div className="bg-[#0d1225] border border-white/10 rounded-lg p-3">
                  <p className="font-mono text-xs text-[#6b7594] mb-2">Missing fields:</p>
                  <ul className="font-mono text-xs text-[#f0ece4]/80 space-y-1 list-disc list-inside">
                    {profileGap.missing_fields.map((f) => <li key={f}>{f}</li>)}
                  </ul>
                </div>
              )}
              <button
                onClick={() => router.push(`/account/vessel/${selectedVessel}`)}
                className="font-mono text-sm font-bold text-[#2dd4bf]
                  border border-[#2dd4bf]/40 hover:bg-[#2dd4bf]/10
                  rounded-lg py-2.5 transition-colors duration-150"
              >
                Complete Vessel Profile
              </button>
            </section>
          )}

          {/* Loading state */}
          {loading && (
            <section className="bg-[#111827] border border-[#2dd4bf]/20 rounded-xl p-6 flex flex-col items-center gap-4 print:hidden">
              <div className="relative w-12 h-12 flex items-center justify-center">
                <div className="absolute inset-0 rounded-full bg-[#2dd4bf]/20 animate-ping" />
                <div className="relative w-6 h-6 rounded-full bg-[#2dd4bf]" />
              </div>
              <div className="flex flex-col items-center gap-1 min-h-[3rem]">
                <p className="font-mono text-sm text-[#2dd4bf] text-center transition-opacity duration-300">
                  {LOADING_MESSAGES[loadingMsgIdx]}
                </p>
                <p className="font-mono text-xs text-[#6b7594]">
                  {elapsedSeconds > 0 ? `${elapsedSeconds}s elapsed` : 'Starting...'}
                </p>
              </div>
              <p className="font-mono text-[10px] text-[#6b7594]/60 text-center leading-relaxed">
                Generating a PSC checklist takes about 30–45 seconds.
                <br />
                Please keep this page open.
              </p>
            </section>
          )}

          {/* Checklist results */}
          {checklist && !loading && (
            <>
              {/* Header with timestamp + progress + print */}
              <div className="bg-[#111827] border border-white/8 rounded-xl p-4 flex flex-col gap-3 print:hidden">
                <div className="flex items-center justify-between gap-3">
                  <p className="font-mono text-xs text-[#6b7594]">
                    Generated {formatRelativeDate(checklist.generated_at)}
                  </p>
                  <button
                    onClick={() => window.print()}
                    className="font-mono text-xs text-[#2dd4bf] hover:underline shrink-0"
                  >
                    Print
                  </button>
                </div>
                <div className="flex items-center gap-3">
                  <div className="flex-1">
                    <div className="w-full bg-white/5 rounded-full h-2">
                      <div
                        className="h-full bg-[#2dd4bf] rounded-full transition-all duration-300"
                        style={{ width: `${totalItems > 0 ? (checkedCount / totalItems) * 100 : 0}%` }}
                      />
                    </div>
                  </div>
                  <span className="font-mono text-xs text-[#6b7594] shrink-0">
                    {checkedCount}/{totalItems}
                  </span>
                </div>
              </div>

              {/* Print header */}
              <div className="hidden print:block mb-4">
                <h1 className="text-xl font-bold">PSC Inspection Readiness Checklist</h1>
                <p className="text-sm text-gray-600">
                  {checklist.vessel_name} ({checklist.vessel_type}) — Generated {new Date(checklist.generated_at).toLocaleDateString()}
                </p>
              </div>

              {/* Grouped checklist items */}
              {Object.entries(grouped).map(([category, items]) => (
                <section key={category} className="bg-[#111827] border border-white/8 rounded-xl p-4 flex flex-col gap-2
                  print:bg-white print:border-gray-300 print:text-black">
                  <p className="font-mono text-xs text-[#2dd4bf] uppercase tracking-wider font-bold
                    print:text-black">
                    {category}
                  </p>
                  {items.map(({ item, idx }) => (
                    <label
                      key={idx}
                      className={`flex items-start gap-3 py-2 px-2 rounded-lg cursor-pointer
                        hover:bg-white/3 transition-colors duration-100
                        ${checked.has(idx) ? 'opacity-60' : ''}`}
                    >
                      <input
                        type="checkbox"
                        checked={checked.has(idx)}
                        onChange={() => toggleCheck(idx)}
                        className="mt-0.5 w-4 h-4 rounded border-white/20 bg-[#0d1225]
                          accent-[#2dd4bf] shrink-0
                          print:accent-black"
                      />
                      <div className="min-w-0 flex-1">
                        <p className={`font-mono text-sm text-[#f0ece4] leading-relaxed
                          print:text-black ${checked.has(idx) ? 'line-through' : ''}`}>
                          {item.item}
                        </p>
                        <p className="font-mono text-xs text-[#2dd4bf]/70 mt-0.5
                          print:text-gray-600">
                          {item.regulation}
                        </p>
                        {item.notes && (
                          <p className="font-mono text-xs text-[#6b7594] mt-0.5
                            print:text-gray-500">
                            {item.notes}
                          </p>
                        )}
                      </div>
                    </label>
                  ))}
                </section>
              ))}

              <p className="font-mono text-[10px] text-[#6b7594]/50 text-center print:text-gray-400">
                Generated by RegKnot — Navigation aid only, not legal advice
              </p>
            </>
          )}

          {/* No vessels state */}
          {vessels.length === 0 && (
            <section className="bg-[#111827] border border-white/8 rounded-xl p-8 text-center">
              <p className="font-mono text-sm text-[#6b7594] mb-2">No vessels registered</p>
              <p className="font-mono text-xs text-[#6b7594]/70">
                Add a vessel profile first to generate a PSC inspection checklist.
              </p>
            </section>
          )}

        </div>
      </main>
    </div>
  )
}

export default function PSCChecklistPage() {
  return (
    <AuthGuard>
      <PSCContent />
    </AuthGuard>
  )
}
