'use client'

import { useEffect, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import AuthGuard from '@/components/AuthGuard'
import { AppHeader } from '@/components/AppHeader'
import { apiRequest } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import { useVoiceInput } from '@/lib/useVoiceInput'

const CATEGORIES = [
  { value: 'general', label: 'General' },
  { value: 'safety_drill', label: 'Safety Drill' },
  { value: 'inspection', label: 'Inspection' },
  { value: 'maintenance', label: 'Maintenance' },
  { value: 'incident', label: 'Incident' },
  { value: 'navigation', label: 'Navigation' },
  { value: 'cargo', label: 'Cargo' },
  { value: 'crew', label: 'Crew' },
  { value: 'environmental', label: 'Environmental' },
  { value: 'psc', label: 'PSC' },
]

const CATEGORY_LABELS: Record<string, string> = Object.fromEntries(
  CATEGORIES.map((c) => [c.value, c.label]),
)

interface LogEntry {
  id: string
  vessel_id: string | null
  vessel_name: string | null
  entry_date: string
  category: string
  entry: string
  created_at: string
  updated_at: string
}

interface VesselItem {
  id: string
  name: string
}

function LogContent() {
  const searchParams = useSearchParams()
  const isQuick = searchParams.get('quick') === 'true'
  const { vessels, activeVesselId } = useAuthStore()
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(isQuick)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [filterVessel, setFilterVessel] = useState<string>('all')
  const [filterCategory, setFilterCategory] = useState<string>('all')

  // Form fields
  const [formVessel, setFormVessel] = useState(activeVesselId ?? '')
  const [formDate, setFormDate] = useState(new Date().toISOString().slice(0, 10))
  const [formCategory, setFormCategory] = useState('general')
  const [formEntry, setFormEntry] = useState('')

  const { listening, supported, toggle, start: startVoice } = useVoiceInput({
    onTranscript: (text) => {
      setFormEntry((prev) => (prev ? `${prev} ${text}` : text))
    },
  })

  // Auto-start voice when entering via Quick Log
  useEffect(() => {
    if (isQuick && supported && !listening) {
      // Small delay to let the page render and get mic permission prompt
      const t = setTimeout(() => startVoice(), 500)
      return () => clearTimeout(t)
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const params = new URLSearchParams()
    if (filterVessel !== 'all') params.set('vessel_id', filterVessel)
    if (filterCategory !== 'all') params.set('category', filterCategory)
    params.set('limit', '100')
    apiRequest<LogEntry[]>(`/logs?${params}`)
      .then(setLogs)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [filterVessel, filterCategory])

  function resetForm() {
    setFormVessel(activeVesselId ?? '')
    setFormDate(new Date().toISOString().slice(0, 10))
    setFormCategory('general')
    setFormEntry('')
    setShowForm(false)
    setError(null)
  }

  async function handleSave() {
    if (!formEntry.trim()) {
      setError('Entry text is required')
      return
    }
    setSaving(true)
    setError(null)
    try {
      const created = await apiRequest<LogEntry>('/logs', {
        method: 'POST',
        body: JSON.stringify({
          vessel_id: formVessel || null,
          entry_date: formDate,
          category: formCategory,
          entry: formEntry.trim(),
        }),
      })
      setLogs((prev) => [created, ...prev])
      resetForm()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete(id: string) {
    try {
      await apiRequest(`/logs/${id}`, { method: 'DELETE' })
      setLogs((prev) => prev.filter((l) => l.id !== id))
    } catch {
      // ignore
    }
  }

  return (
    <div className="flex flex-col h-dvh bg-[#0a0e1a]">
      <AppHeader title="Compliance Log" />

      <main className="flex-1 overflow-y-auto px-4 py-6">
        <div className="max-w-sm md:max-w-3xl mx-auto flex flex-col gap-5">

          {/* New entry button */}
          {!showForm && (
            <button
              onClick={() => { resetForm(); setShowForm(true) }}
              className="w-full font-mono text-sm font-bold text-[#0a0e1a] bg-[#2dd4bf]
                hover:brightness-110 rounded-xl py-3 transition-[filter] duration-150"
            >
              + New Log Entry
            </button>
          )}

          {/* Entry form */}
          {showForm && (
            <section className="bg-[#111827] border border-[#2dd4bf]/20 rounded-xl p-5 flex flex-col gap-4">
              <p className="font-mono text-xs text-[#6b7594] uppercase tracking-wider">New Entry</p>

              {/* Vessel selector */}
              <div className="flex flex-col gap-1">
                <label className="font-mono text-xs text-[#6b7594]">Vessel</label>
                <select
                  value={formVessel}
                  onChange={(e) => setFormVessel(e.target.value)}
                  className="font-mono w-full border border-white/10 rounded-lg px-3 py-2 text-sm
                    outline-none focus:border-[#2dd4bf] transition-colors"
                  style={{ backgroundColor: '#0d1225', color: '#f0ece4' }}
                >
                  <option value="" style={{ backgroundColor: '#111827', color: '#f0ece4' }}>
                    No vessel
                  </option>
                  {vessels.map((v) => (
                    <option key={v.id} value={v.id} style={{ backgroundColor: '#111827', color: '#f0ece4' }}>
                      {v.name}
                    </option>
                  ))}
                </select>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="flex flex-col gap-1">
                  <label className="font-mono text-xs text-[#6b7594]">Date</label>
                  <input
                    type="date"
                    value={formDate}
                    onChange={(e) => setFormDate(e.target.value)}
                    className="font-mono w-full bg-[#0d1225] border border-white/10 rounded-lg px-3 py-2 text-sm
                      text-[#f0ece4] outline-none focus:border-[#2dd4bf] transition-colors
                      [color-scheme:dark]"
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <label className="font-mono text-xs text-[#6b7594]">Category</label>
                  <select
                    value={formCategory}
                    onChange={(e) => setFormCategory(e.target.value)}
                    className="font-mono w-full border border-white/10 rounded-lg px-3 py-2 text-sm
                      outline-none focus:border-[#2dd4bf] transition-colors"
                    style={{ backgroundColor: '#0d1225', color: '#f0ece4' }}
                  >
                    {CATEGORIES.map((c) => (
                      <option key={c.value} value={c.value} style={{ backgroundColor: '#111827', color: '#f0ece4' }}>
                        {c.label}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              {/* Entry text with voice */}
              <div className="flex flex-col gap-1">
                <div className="flex items-center justify-between">
                  <label className="font-mono text-xs text-[#6b7594]">Entry</label>
                  {supported && (
                    <button
                      onClick={toggle}
                      className={`font-mono text-xs flex items-center gap-1 px-2 py-0.5 rounded-md
                        transition-colors duration-150 ${
                          listening
                            ? 'text-red-400 bg-red-500/10 animate-pulse'
                            : 'text-[#6b7594] hover:text-[#2dd4bf] hover:bg-white/5'
                        }`}
                    >
                      <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <rect x="9" y="1" width="6" height="14" rx="3" />
                        <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                      </svg>
                      {listening ? 'Listening...' : 'Voice'}
                    </button>
                  )}
                </div>
                <textarea
                  value={formEntry}
                  onChange={(e) => setFormEntry(e.target.value)}
                  rows={4}
                  placeholder={listening ? 'Speak now...' : 'Describe the event, observation, or action taken...'}
                  className="font-mono w-full bg-[#0d1225] border border-white/10 rounded-lg px-3 py-2 text-sm
                    text-[#f0ece4] outline-none focus:border-[#2dd4bf] transition-colors resize-none"
                />
              </div>

              {error && <p className="font-mono text-xs text-red-400">{error}</p>}

              <div className="flex items-center gap-2">
                <button
                  onClick={handleSave}
                  disabled={saving}
                  className="font-mono text-sm font-bold text-[#0a0e1a] bg-[#2dd4bf] hover:brightness-110
                    disabled:opacity-50 rounded-lg px-4 py-2 transition-[filter] duration-150"
                >
                  {saving ? 'Saving...' : 'Log Entry'}
                </button>
                <button
                  onClick={resetForm}
                  className="font-mono text-sm text-[#6b7594] hover:text-[#f0ece4] px-3 py-2
                    transition-colors duration-150"
                >
                  Cancel
                </button>
              </div>
            </section>
          )}

          {/* Filters */}
          <div className="flex items-center gap-2">
            <select
              value={filterVessel}
              onChange={(e) => { setFilterVessel(e.target.value); setLoading(true) }}
              className="font-mono flex-1 border border-white/10 rounded-lg px-2 py-1.5 text-xs
                outline-none focus:border-[#2dd4bf] transition-colors"
              style={{ backgroundColor: '#0d1225', color: '#f0ece4' }}
            >
              <option value="all" style={{ backgroundColor: '#111827', color: '#f0ece4' }}>All vessels</option>
              {vessels.map((v) => (
                <option key={v.id} value={v.id} style={{ backgroundColor: '#111827', color: '#f0ece4' }}>
                  {v.name}
                </option>
              ))}
            </select>
            <select
              value={filterCategory}
              onChange={(e) => { setFilterCategory(e.target.value); setLoading(true) }}
              className="font-mono flex-1 border border-white/10 rounded-lg px-2 py-1.5 text-xs
                outline-none focus:border-[#2dd4bf] transition-colors"
              style={{ backgroundColor: '#0d1225', color: '#f0ece4' }}
            >
              <option value="all" style={{ backgroundColor: '#111827', color: '#f0ece4' }}>All categories</option>
              {CATEGORIES.map((c) => (
                <option key={c.value} value={c.value} style={{ backgroundColor: '#111827', color: '#f0ece4' }}>
                  {c.label}
                </option>
              ))}
            </select>
          </div>

          {/* Loading */}
          {loading && (
            <div className="flex flex-col gap-3">
              {[1, 2, 3].map((i) => (
                <div key={i} className="h-16 bg-[#111827] border border-white/8 rounded-xl animate-pulse" />
              ))}
            </div>
          )}

          {/* Empty state */}
          {!loading && logs.length === 0 && !showForm && (
            <section className="bg-[#111827] border border-white/8 rounded-xl p-8 text-center">
              <p className="font-mono text-sm text-[#6b7594] mb-2">No log entries yet</p>
              <p className="font-mono text-xs text-[#6b7594]/70">
                Record safety drills, inspections, maintenance, incidents, and other compliance events.
              </p>
            </section>
          )}

          {/* Log entries list */}
          {!loading && logs.map((log) => (
            <section
              key={log.id}
              className="bg-[#111827] border border-white/8 rounded-xl p-4 flex flex-col gap-2"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-mono text-xs px-2 py-0.5 rounded-md bg-[#2dd4bf]/10 text-[#2dd4bf] border border-[#2dd4bf]/20">
                      {CATEGORY_LABELS[log.category] ?? log.category}
                    </span>
                    {log.vessel_name && (
                      <span className="font-mono text-xs text-[#6b7594]">{log.vessel_name}</span>
                    )}
                  </div>
                </div>
                <span className="font-mono text-xs text-[#6b7594] shrink-0">{log.entry_date}</span>
              </div>

              <p className="font-mono text-sm text-[#f0ece4]/90 whitespace-pre-wrap leading-relaxed">
                {log.entry}
              </p>

              <div className="flex items-center gap-3 mt-1">
                <button
                  onClick={() => handleDelete(log.id)}
                  className="font-mono text-xs text-red-400/70 hover:text-red-400"
                >
                  Delete
                </button>
              </div>
            </section>
          ))}

        </div>
      </main>
    </div>
  )
}

export default function LogPage() {
  return (
    <AuthGuard>
      <LogContent />
    </AuthGuard>
  )
}
