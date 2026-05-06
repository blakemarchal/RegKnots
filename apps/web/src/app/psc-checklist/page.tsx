'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import AuthGuard from '@/components/AuthGuard'
import { AppHeader } from '@/components/AppHeader'
import { PSCPrepCard } from '@/components/PSCPrepCard'
import { apiRequest, ApiError } from '@/lib/api'
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

const PSC_CATEGORIES = [
  'Safety Equipment & LSA',
  'Structural & Hull',
  'Fire Safety',
  'Navigation & Communications',
  'Pollution Prevention',
  'Manning & Certification',
  'ISM / SMS Documentation',
  'ISPS Security',
  'Working & Living Conditions',
]

interface ChecklistItem {
  category: string
  item: string
  regulation: string
  notes: string | null
  user_added?: boolean
}

interface OmittedCategory {
  category: string
  reason: string
}

interface CoverageInfo {
  included_categories: string[]
  omitted_categories: OmittedCategory[]
}

interface PSCChecklist {
  vessel_name: string
  vessel_type: string
  checklist: ChecklistItem[]
  checked_indices: number[]
  coverage: CoverageInfo | null
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

const LAST_VESSEL_KEY = 'regknot:psc:lastVesselId'

function readLastVesselId(): string {
  if (typeof window === 'undefined') return ''
  try {
    return window.localStorage.getItem(LAST_VESSEL_KEY) ?? ''
  } catch {
    return ''
  }
}

function writeLastVesselId(id: string): void {
  if (typeof window === 'undefined') return
  try {
    if (id) window.localStorage.setItem(LAST_VESSEL_KEY, id)
    else window.localStorage.removeItem(LAST_VESSEL_KEY)
  } catch {
    /* noop — quota, private mode, etc */
  }
}

function PSCContent() {
  const router = useRouter()
  const { vessels, activeVesselId } = useAuthStore()
  // Last vessel persists across navigation via localStorage.
  // On mount: prefer the last-used vessel on this page; fall back to the
  // globally-active vessel only if nothing was previously picked here.
  const [selectedVessel, setSelectedVessel] = useState<string>(() => {
    const last = readLastVesselId()
    return last || activeVesselId || ''
  })
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
  const [editingIdx, setEditingIdx] = useState<number | null>(null)
  const [editItem, setEditItem] = useState({ item: '', regulation: '', notes: '' })
  const [addingForCategory, setAddingForCategory] = useState<string | null>(null)
  const [newItemState, setNewItemState] = useState({ item: '', regulation: '', notes: '' })
  const [savingItem, setSavingItem] = useState(false)
  const [coverageExpanded, setCoverageExpanded] = useState(false)

  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const abortRef = useRef<AbortController | null>(null)

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

  useEffect(() => {
    // Only backfill from the global active vessel if nothing is selected here
    // AND nothing was ever persisted for this page. We don't want the global
    // selection to override a vessel the user deliberately picked on PSC.
    if (!selectedVessel && activeVesselId && !readLastVesselId()) {
      setSelectedVessel(activeVesselId)
    }
  }, [activeVesselId, selectedVessel])

  // Persist every vessel change so it survives navigation and refresh.
  useEffect(() => {
    writeLastVesselId(selectedVessel)
  }, [selectedVessel])

  // If the persisted vessel no longer exists (e.g. deleted), clear it.
  useEffect(() => {
    if (!selectedVessel) return
    if (vessels.length === 0) return  // still hydrating
    const exists = vessels.some((v) => v.id === selectedVessel)
    if (!exists) {
      setSelectedVessel('')
      writeLastVesselId('')
    }
  }, [selectedVessel, vessels])

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
    if (!selectedVessel) { setError('Select a vessel first'); return }
    setConfirmRegen(false)
    setLoading(true)
    setLoadingStartedAt(Date.now())
    setLoadingMsgIdx(0)
    setElapsedSeconds(0)
    setError(null)
    setProfileGap(null)
    setChecklist(null)
    setChecked(new Set())

    const controller = new AbortController()
    abortRef.current = controller

    try {
      const result = await apiRequest<PSCChecklist>('/checklists/psc', {
        method: 'POST',
        body: JSON.stringify({ vessel_id: selectedVessel }),
        signal: controller.signal,
      })
      setChecklist(result)
      setChecked(new Set(result.checked_indices || []))
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return
      if (e instanceof ApiError && e.status === 422) {
        const body = e.body as { detail?: unknown }
        const detail = body?.detail
        if (detail && typeof detail === 'object' && 'missing_fields' in (detail as Record<string, unknown>)) {
          setProfileGap(detail as ProfileIncompleteError)
          return
        }
      }
      const msg = e instanceof Error ? e.message : 'Failed to generate checklist'
      setError(msg)
    } finally {
      abortRef.current = null
      setLoading(false)
      setLoadingStartedAt(null)
    }
  }, [selectedVessel])

  function handleGenerateClick() {
    if (checklist) { setConfirmRegen(true); return }
    doGenerate()
  }

  function cancelGeneration() {
    if (abortRef.current) {
      abortRef.current.abort()
      abortRef.current = null
    }
    setLoading(false)
    setLoadingStartedAt(null)
  }

  function saveChecks(next: Set<number>) {
    if (!selectedVessel) return
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
    saveTimerRef.current = setTimeout(() => {
      apiRequest(`/checklists/psc/${selectedVessel}/checks`, {
        method: 'PATCH',
        body: JSON.stringify({ checked_indices: Array.from(next) }),
      }).catch(() => {})
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

  function startEdit(idx: number, item: ChecklistItem) {
    setEditingIdx(idx)
    setEditItem({
      item: item.item,
      regulation: item.regulation,
      notes: item.notes ?? '',
    })
  }

  async function saveEdit(idx: number) {
    if (!selectedVessel || !editItem.item.trim() || !editItem.regulation.trim()) return
    setSavingItem(true)
    try {
      const updated = await apiRequest<PSCChecklist>(`/checklists/psc/${selectedVessel}/items/${idx}`, {
        method: 'PATCH',
        body: JSON.stringify({
          item: editItem.item.trim(),
          regulation: editItem.regulation.trim(),
          notes: editItem.notes.trim() || null,
        }),
      })
      setChecklist(updated)
      setChecked(new Set(updated.checked_indices || []))
      setEditingIdx(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save item')
    } finally {
      setSavingItem(false)
    }
  }

  async function deleteItem(idx: number) {
    if (!selectedVessel) return
    setSavingItem(true)
    try {
      const updated = await apiRequest<PSCChecklist>(`/checklists/psc/${selectedVessel}/items/${idx}`, {
        method: 'DELETE',
      })
      setChecklist(updated)
      setChecked(new Set(updated.checked_indices || []))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to delete item')
    } finally {
      setSavingItem(false)
    }
  }

  async function addItem(category: string) {
    if (!selectedVessel || !newItemState.item.trim() || !newItemState.regulation.trim()) return
    setSavingItem(true)
    try {
      const updated = await apiRequest<PSCChecklist>(`/checklists/psc/${selectedVessel}/items`, {
        method: 'POST',
        body: JSON.stringify({
          category,
          item: newItemState.item.trim(),
          regulation: newItemState.regulation.trim(),
          notes: newItemState.notes.trim() || null,
        }),
      })
      setChecklist(updated)
      setChecked(new Set(updated.checked_indices || []))
      setNewItemState({ item: '', regulation: '', notes: '' })
      setAddingForCategory(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to add item')
    } finally {
      setSavingItem(false)
    }
  }

  // Group items by category, preserving AI-chosen order from `included_categories`
  const grouped: Record<string, { item: ChecklistItem; idx: number }[]> = {}
  if (checklist) {
    checklist.checklist.forEach((item, idx) => {
      if (!grouped[item.category]) grouped[item.category] = []
      grouped[item.category].push({ item, idx })
    })
  }

  // Order: AI's included_categories first, then any user-added categories not in that list
  const orderedCategories: string[] = []
  if (checklist?.coverage?.included_categories) {
    checklist.coverage.included_categories.forEach((c) => {
      if (grouped[c]) orderedCategories.push(c)
    })
  }
  Object.keys(grouped).forEach((c) => {
    if (!orderedCategories.includes(c)) orderedCategories.push(c)
  })

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
              <div className="relative">
                <select
                  value={selectedVessel}
                  onChange={(e) => setSelectedVessel(e.target.value)}
                  className="font-mono w-full border border-white/10 rounded-lg pl-3 pr-10 py-2 text-sm
                    outline-none focus:border-[#2dd4bf] transition-colors
                    appearance-none cursor-pointer"
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
                <svg
                  className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#6b7594] pointer-events-none"
                  viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <polyline points="6 9 12 15 18 9" />
                </svg>
              </div>
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
                This will generate a new checklist and reset your current progress ({checkedCount}/{totalItems} items checked). Any custom items you added will be lost.
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
                This can take up to a minute.
                <br />
                Please keep this page open.
              </p>
              <button
                onClick={cancelGeneration}
                className="font-mono text-xs text-[#6b7594] hover:text-red-400
                  border border-white/10 hover:border-red-400/40
                  rounded-lg px-4 py-2 mt-1 transition-colors duration-150"
              >
                Cancel
              </button>
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

              {/* Coverage statement (transparency) */}
              {checklist.coverage && (
                <div className="bg-[#111827] border border-white/8 rounded-xl p-4 flex flex-col gap-2 print:bg-white print:border-gray-300">
                  <button
                    onClick={() => setCoverageExpanded((v) => !v)}
                    className="flex items-center justify-between w-full text-left
                      hover:opacity-90 transition-opacity print:cursor-default"
                  >
                    <p className="font-mono text-xs text-[#2dd4bf] uppercase tracking-wider print:text-black">
                      Coverage
                    </p>
                    <svg
                      className={`w-3.5 h-3.5 text-[#6b7594] transition-transform duration-150 print:hidden ${coverageExpanded ? 'rotate-180' : ''}`}
                      viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
                    >
                      <polyline points="6 9 12 15 18 9" />
                    </svg>
                  </button>
                  <p className="font-mono text-xs text-[#f0ece4]/80 leading-relaxed print:text-black">
                    This checklist covers <strong className="text-[#2dd4bf] print:text-black">
                    {checklist.coverage.included_categories.length} of {PSC_CATEGORIES.length}</strong> PSC categories applicable to your vessel.
                    {checklist.coverage.omitted_categories.length > 0 && !coverageExpanded && (
                      <> <span className="text-[#6b7594]">Tap to see what was omitted and why.</span></>
                    )}
                  </p>
                  {(coverageExpanded || typeof window !== 'undefined' && window.matchMedia?.('print').matches) &&
                    checklist.coverage.omitted_categories.length > 0 && (
                    <div className="bg-[#0d1225] border border-white/10 rounded-lg p-3 mt-1 print:bg-white print:border-gray-300">
                      <p className="font-mono text-xs text-[#6b7594] uppercase tracking-wider mb-2 print:text-gray-600">Omitted categories</p>
                      <ul className="flex flex-col gap-2">
                        {checklist.coverage.omitted_categories.map((o) => (
                          <li key={o.category} className="font-mono text-xs leading-relaxed">
                            <span className="text-[#f0ece4] print:text-black">{o.category}</span>
                            <span className="text-[#6b7594] print:text-gray-600"> — {o.reason}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}

              {/* Print header */}
              <div className="hidden print:block mb-4">
                <h1 className="text-xl font-bold">PSC Inspection Readiness Checklist</h1>
                <p className="text-sm text-gray-600">
                  {checklist.vessel_name} ({checklist.vessel_type}) — Generated {new Date(checklist.generated_at).toLocaleDateString()}
                </p>
              </div>

              {/* Grouped checklist items */}
              {orderedCategories.map((category) => {
                const items = grouped[category] || []
                return (
                  <section key={category} className="bg-[#111827] border border-white/8 rounded-xl p-4 flex flex-col gap-2
                    print:bg-white print:border-gray-300 print:text-black">
                    <p className="font-mono text-xs text-[#2dd4bf] uppercase tracking-wider font-bold
                      print:text-black">
                      {category}
                    </p>
                    {items.map(({ item, idx }) => (
                      <div key={idx}>
                        {editingIdx === idx ? (
                          <div className="flex flex-col gap-2 bg-[#0d1225] border border-[#2dd4bf]/30 rounded-lg p-3">
                            <input
                              type="text"
                              value={editItem.item}
                              onChange={(e) => setEditItem({ ...editItem, item: e.target.value })}
                              placeholder="Item text"
                              className="font-mono w-full bg-[#0a0e1a] border border-white/10 rounded-lg px-2 py-1.5 text-sm
                                text-[#f0ece4] outline-none focus:border-[#2dd4bf] transition-colors"
                            />
                            <input
                              type="text"
                              value={editItem.regulation}
                              onChange={(e) => setEditItem({ ...editItem, regulation: e.target.value })}
                              placeholder="Regulation (e.g. 46 CFR 181.400)"
                              className="font-mono w-full bg-[#0a0e1a] border border-white/10 rounded-lg px-2 py-1.5 text-xs
                                text-[#2dd4bf]/80 outline-none focus:border-[#2dd4bf] transition-colors"
                            />
                            <textarea
                              value={editItem.notes}
                              onChange={(e) => setEditItem({ ...editItem, notes: e.target.value })}
                              placeholder="Notes (optional)"
                              rows={2}
                              className="font-mono w-full bg-[#0a0e1a] border border-white/10 rounded-lg px-2 py-1.5 text-xs
                                text-[#f0ece4]/80 outline-none focus:border-[#2dd4bf] transition-colors resize-none"
                            />
                            <div className="flex items-center gap-2">
                              <button
                                onClick={() => saveEdit(idx)}
                                disabled={savingItem || !editItem.item.trim() || !editItem.regulation.trim()}
                                className="font-mono text-xs font-bold text-[#0a0e1a] bg-[#2dd4bf]
                                  hover:brightness-110 disabled:opacity-50 rounded-md px-3 py-1
                                  transition-[filter] duration-150"
                              >
                                {savingItem ? 'Saving…' : 'Save'}
                              </button>
                              <button
                                onClick={() => setEditingIdx(null)}
                                className="font-mono text-xs text-[#6b7594] hover:text-[#f0ece4] px-2 py-1"
                              >
                                Cancel
                              </button>
                            </div>
                          </div>
                        ) : (
                          <div className={`flex items-start gap-3 py-2 px-2 rounded-lg
                            hover:bg-white/3 transition-colors duration-100 group
                            ${checked.has(idx) ? 'opacity-60' : ''}`}>
                            <label className="flex items-start gap-3 flex-1 cursor-pointer min-w-0">
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
                                  {item.user_added && (
                                    <span className="ml-1.5 inline-block font-mono text-[9px] uppercase tracking-wider text-[#2dd4bf]/70 border border-[#2dd4bf]/30 rounded px-1 py-0 align-middle print:hidden">
                                      Custom
                                    </span>
                                  )}
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
                            <div className="flex flex-col gap-1 shrink-0 opacity-0 group-hover:opacity-100
                              transition-opacity duration-100 print:hidden">
                              <button
                                onClick={() => startEdit(idx, item)}
                                className="font-mono text-[10px] text-[#6b7594] hover:text-[#2dd4bf] px-1"
                                aria-label="Edit item"
                              >
                                Edit
                              </button>
                              <button
                                onClick={() => {
                                  const q = `Tell me more about this PSC checklist item: "${item.item}" (${item.regulation})`
                                  router.push(`/?conversation_id=&q=${encodeURIComponent(q)}`)
                                }}
                                className="font-mono text-[10px] text-[#6b7594] hover:text-[#2dd4bf] px-1"
                                aria-label="Ask about this item"
                              >
                                Ask
                              </button>
                              <button
                                onClick={() => deleteItem(idx)}
                                disabled={savingItem}
                                className="font-mono text-[10px] text-[#6b7594] hover:text-red-400 px-1"
                                aria-label="Delete item"
                              >
                                Delete
                              </button>
                            </div>
                          </div>
                        )}
                      </div>
                    ))}

                    {/* Add custom item UI */}
                    {addingForCategory === category ? (
                      <div className="flex flex-col gap-2 bg-[#0d1225] border border-[#2dd4bf]/30 rounded-lg p-3 mt-1">
                        <input
                          type="text"
                          value={newItemState.item}
                          onChange={(e) => setNewItemState({ ...newItemState, item: e.target.value })}
                          placeholder="What to check"
                          className="font-mono w-full bg-[#0a0e1a] border border-white/10 rounded-lg px-2 py-1.5 text-sm
                            text-[#f0ece4] outline-none focus:border-[#2dd4bf] transition-colors"
                        />
                        <input
                          type="text"
                          value={newItemState.regulation}
                          onChange={(e) => setNewItemState({ ...newItemState, regulation: e.target.value })}
                          placeholder="Regulation reference (e.g. 46 CFR 185.500)"
                          className="font-mono w-full bg-[#0a0e1a] border border-white/10 rounded-lg px-2 py-1.5 text-xs
                            text-[#2dd4bf]/80 outline-none focus:border-[#2dd4bf] transition-colors"
                        />
                        <textarea
                          value={newItemState.notes}
                          onChange={(e) => setNewItemState({ ...newItemState, notes: e.target.value })}
                          placeholder="Notes (optional)"
                          rows={2}
                          className="font-mono w-full bg-[#0a0e1a] border border-white/10 rounded-lg px-2 py-1.5 text-xs
                            text-[#f0ece4]/80 outline-none focus:border-[#2dd4bf] transition-colors resize-none"
                        />
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => addItem(category)}
                            disabled={savingItem || !newItemState.item.trim() || !newItemState.regulation.trim()}
                            className="font-mono text-xs font-bold text-[#0a0e1a] bg-[#2dd4bf]
                              hover:brightness-110 disabled:opacity-50 rounded-md px-3 py-1
                              transition-[filter] duration-150"
                          >
                            {savingItem ? 'Adding…' : 'Add'}
                          </button>
                          <button
                            onClick={() => { setAddingForCategory(null); setNewItemState({ item: '', regulation: '', notes: '' }) }}
                            className="font-mono text-xs text-[#6b7594] hover:text-[#f0ece4] px-2 py-1"
                          >
                            Cancel
                          </button>
                        </div>
                      </div>
                    ) : (
                      <button
                        onClick={() => { setAddingForCategory(category); setNewItemState({ item: '', regulation: '', notes: '' }) }}
                        className="font-mono text-xs text-[#6b7594] hover:text-[#2dd4bf]
                          border border-dashed border-white/10 hover:border-[#2dd4bf]/30
                          rounded-lg py-1.5 mt-1 transition-colors duration-150 print:hidden"
                      >
                        + Add item
                      </button>
                    )}
                  </section>
                )
              })}

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

          {/* D6.64 — PSC Co-Pilot. AI-driven inspection prep brief
              tailored to vessel + target port region. Renders below the
              static checklist so admins / mariners can use both. */}
          {selectedVessel && (
            <PSCPrepCard vesselId={selectedVessel} />
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
