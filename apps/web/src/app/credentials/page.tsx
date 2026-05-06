'use client'

import { useEffect, useState, useRef } from 'react'
import AuthGuard from '@/components/AuthGuard'
import { AppHeader } from '@/components/AppHeader'
import { apiRequest, apiUpload } from '@/lib/api'

const CREDENTIAL_TYPES = [
  { value: 'mmc', label: 'MMC' },
  { value: 'stcw', label: 'STCW Endorsement' },
  { value: 'medical', label: 'Medical Certificate' },
  { value: 'twic', label: 'TWIC' },
  { value: 'other', label: 'Other' },
]

const TYPE_LABELS: Record<string, string> = Object.fromEntries(
  CREDENTIAL_TYPES.map((t) => [t.value, t.label]),
)

interface Credential {
  id: string
  credential_type: string
  title: string
  credential_number: string | null
  issuing_authority: string | null
  issue_date: string | null
  expiry_date: string | null
  notes: string | null
  created_at: string
  updated_at: string
}

function daysUntil(dateStr: string | null): number | null {
  if (!dateStr) return null
  const diff = new Date(dateStr).getTime() - Date.now()
  return Math.ceil(diff / (1000 * 60 * 60 * 24))
}

function urgencyColor(days: number | null): string {
  if (days === null) return 'text-[#6b7594]'
  if (days < 0) return 'text-red-400'
  if (days <= 7) return 'text-red-400'
  if (days <= 30) return 'text-amber-400'
  if (days <= 90) return 'text-yellow-400'
  return 'text-[#2dd4bf]'
}

function urgencyBorder(days: number | null): string {
  if (days === null) return 'border-white/8'
  if (days < 0) return 'border-red-400/30'
  if (days <= 7) return 'border-red-400/30'
  if (days <= 30) return 'border-amber-400/30'
  if (days <= 90) return 'border-yellow-400/20'
  return 'border-white/8'
}

function urgencyLabel(days: number | null): string {
  if (days === null) return 'No expiry set'
  if (days < 0) return `Expired ${Math.abs(days)}d ago`
  if (days === 0) return 'Expires today'
  return `${days}d remaining`
}

function CredentialsContent() {
  const [credentials, setCredentials] = useState<Credential[]>([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Form fields
  const [formType, setFormType] = useState('mmc')
  const [formTitle, setFormTitle] = useState('')
  const [formNumber, setFormNumber] = useState('')
  const [formAuthority, setFormAuthority] = useState('')
  const [formIssueDate, setFormIssueDate] = useState('')
  const [formExpiryDate, setFormExpiryDate] = useState('')
  const [formNotes, setFormNotes] = useState('')
  const [scanning, setScanning] = useState(false)
  // D6.62 Sprint 2 — package PDF download
  const [packaging, setPackaging] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  async function downloadPackage() {
    setPackaging(true)
    setError(null)
    try {
      const { useAuthStore } = await import('@/lib/auth')
      const token = useAuthStore.getState().accessToken
      const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
      // D6.62 hotfix — pass IANA timezone so the cover-page date
      // matches the user's wall clock instead of UTC midnight.
      let tz = ''
      try {
        tz = Intl.DateTimeFormat().resolvedOptions().timeZone || ''
      } catch { /* old browsers — fallthrough to UTC server-side */ }
      const url = tz
        ? `${API_URL}/credentials/package?tz=${encodeURIComponent(tz)}`
        : `${API_URL}/credentials/package`
      const resp = await fetch(url, {
        method: 'GET',
        credentials: 'include',
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      })
      if (!resp.ok) {
        let detail = `Request failed (${resp.status})`
        try {
          const body = await resp.json()
          if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
        } catch { /* noop */ }
        throw new Error(detail)
      }
      const blob = await resp.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      // Filename comes back via Content-Disposition; browser will pick it up.
      // Fallback name in case the header isn't surfaced.
      a.download = `credential_package.pdf`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to build package')
    } finally {
      setPackaging(false)
    }
  }

  async function handlePhotoScan(file: File) {
    setScanning(true)
    setError(null)
    try {
      const formData = new FormData()
      formData.append('file', file)
      const result = await apiUpload<{
        credential_type: string | null
        title: string | null
        credential_number: string | null
        issuing_authority: string | null
        issue_date: string | null
        expiry_date: string | null
      }>('/credentials/extract-from-photo', formData)

      // Pre-fill form with extracted data
      if (result.credential_type) setFormType(result.credential_type)
      if (result.title) setFormTitle(result.title)
      if (result.credential_number) setFormNumber(result.credential_number)
      if (result.issuing_authority) setFormAuthority(result.issuing_authority)
      if (result.issue_date) setFormIssueDate(result.issue_date)
      if (result.expiry_date) setFormExpiryDate(result.expiry_date)
      setShowForm(true)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to extract credential data')
      setShowForm(true)
    } finally {
      setScanning(false)
    }
  }

  useEffect(() => {
    apiRequest<Credential[]>('/credentials')
      .then(setCredentials)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  function resetForm() {
    setFormType('mmc')
    setFormTitle('')
    setFormNumber('')
    setFormAuthority('')
    setFormIssueDate('')
    setFormExpiryDate('')
    setFormNotes('')
    setEditingId(null)
    setShowForm(false)
    setError(null)
  }

  function startEdit(c: Credential) {
    setFormType(c.credential_type)
    setFormTitle(c.title)
    setFormNumber(c.credential_number ?? '')
    setFormAuthority(c.issuing_authority ?? '')
    setFormIssueDate(c.issue_date ?? '')
    setFormExpiryDate(c.expiry_date ?? '')
    setFormNotes(c.notes ?? '')
    setEditingId(c.id)
    setShowForm(true)
    setError(null)
  }

  async function handleSave() {
    if (!formTitle.trim()) {
      setError('Title is required')
      return
    }
    setSaving(true)
    setError(null)
    const payload = {
      credential_type: formType,
      title: formTitle.trim(),
      credential_number: formNumber || null,
      issuing_authority: formAuthority || null,
      issue_date: formIssueDate || null,
      expiry_date: formExpiryDate || null,
      notes: formNotes || null,
    }
    try {
      if (editingId) {
        const updated = await apiRequest<Credential>(`/credentials/${editingId}`, {
          method: 'PUT',
          body: JSON.stringify(payload),
        })
        setCredentials((prev) => prev.map((c) => (c.id === editingId ? updated : c)))
      } else {
        const created = await apiRequest<Credential>('/credentials', {
          method: 'POST',
          body: JSON.stringify(payload),
        })
        setCredentials((prev) => [...prev, created])
      }
      resetForm()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete(id: string) {
    try {
      await apiRequest(`/credentials/${id}`, { method: 'DELETE' })
      setCredentials((prev) => prev.filter((c) => c.id !== id))
    } catch {
      // ignore
    } finally {
      setConfirmDeleteId(null)
    }
  }

  // Sort: expired first, then by days remaining ascending, then no-expiry last
  const sorted = [...credentials].sort((a, b) => {
    const dA = daysUntil(a.expiry_date)
    const dB = daysUntil(b.expiry_date)
    if (dA === null && dB === null) return 0
    if (dA === null) return 1
    if (dB === null) return -1
    return dA - dB
  })

  return (
    <div className="flex flex-col h-dvh bg-[#0a0e1a]">
      <AppHeader title="Credentials" />

      <main className="flex-1 overflow-y-auto px-4 py-6">
        <div className="max-w-sm mx-auto flex flex-col gap-5">

          {/* Add buttons */}
          {!showForm && (
            <div className="flex gap-2">
              <button
                onClick={() => { resetForm(); setShowForm(true) }}
                className="flex-1 font-mono text-sm font-bold text-[#0a0e1a] bg-[#2dd4bf]
                  hover:brightness-110 rounded-xl py-3 transition-[filter] duration-150"
              >
                + Add Credential
              </button>
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={scanning}
                className="font-mono text-sm font-bold text-[#2dd4bf]
                  border border-[#2dd4bf]/40 hover:bg-[#2dd4bf]/10
                  disabled:opacity-50 rounded-xl px-4 py-3 transition-colors duration-150
                  flex items-center gap-2"
              >
                <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="3" y="3" width="18" height="18" rx="2" />
                  <circle cx="8.5" cy="8.5" r="1.5" />
                  <path d="M21 15l-5-5L5 21" />
                </svg>
                {scanning ? 'Scanning...' : 'Scan'}
              </button>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/jpeg,image/png,image/webp,application/pdf"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0]
                  if (file) handlePhotoScan(file)
                  e.target.value = ''
                }}
              />
            </div>
          )}

          {/* D6.62 Sprint 2 — Build Package CTA. The "share with employer
              / manning agency / port agent" PDF other apps gate behind
              Pro tier. Auth'd fetch → blob → download. */}
          {!showForm && credentials.length > 0 && (
            <button
              onClick={() => void downloadPackage()}
              disabled={packaging}
              className="font-mono text-xs text-[#2dd4bf]
                border border-[#2dd4bf]/30 bg-[#2dd4bf]/5 hover:bg-[#2dd4bf]/10
                disabled:opacity-50
                rounded-lg py-2 px-3 transition-colors flex items-center
                justify-center gap-2"
              title="One PDF with all credentials + sea-time totals + log"
            >
              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none"
                   stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3" />
              </svg>
              {packaging ? 'Building package…' : 'Download credential package (PDF)'}
            </button>
          )}

          {/* Add/Edit form */}
          {showForm && (
            <section className="bg-[#111827] border border-[#2dd4bf]/20 rounded-xl p-5 flex flex-col gap-4">
              <p className="font-mono text-xs text-[#6b7594] uppercase tracking-wider">
                {editingId ? 'Edit Credential' : 'New Credential'}
              </p>

              <div className="flex flex-col gap-1">
                <label className="font-mono text-xs text-[#6b7594]">Type</label>
                <select
                  value={formType}
                  onChange={(e) => setFormType(e.target.value)}
                  className="font-mono w-full border border-white/10 rounded-lg px-3 py-2 text-sm
                    outline-none focus:border-[#2dd4bf] transition-colors"
                  style={{ backgroundColor: '#0d1225', color: '#f0ece4' }}
                >
                  {CREDENTIAL_TYPES.map((t) => (
                    <option key={t.value} value={t.value} style={{ backgroundColor: '#111827', color: '#f0ece4' }}>
                      {t.label}
                    </option>
                  ))}
                </select>
              </div>

              <div className="flex flex-col gap-1">
                <label className="font-mono text-xs text-[#6b7594]">Title</label>
                <input
                  type="text"
                  value={formTitle}
                  onChange={(e) => setFormTitle(e.target.value)}
                  placeholder="e.g. Master 1600 GRT"
                  className="font-mono w-full bg-[#0d1225] border border-white/10 rounded-lg px-3 py-2 text-sm
                    text-[#f0ece4] outline-none focus:border-[#2dd4bf] transition-colors"
                />
              </div>

              <div className="flex flex-col gap-1">
                <label className="font-mono text-xs text-[#6b7594]">Credential Number</label>
                <input
                  type="text"
                  value={formNumber}
                  onChange={(e) => setFormNumber(e.target.value)}
                  className="font-mono w-full bg-[#0d1225] border border-white/10 rounded-lg px-3 py-2 text-sm
                    text-[#f0ece4] outline-none focus:border-[#2dd4bf] transition-colors"
                />
              </div>

              <div className="flex flex-col gap-1">
                <label className="font-mono text-xs text-[#6b7594]">Issuing Authority</label>
                <input
                  type="text"
                  value={formAuthority}
                  onChange={(e) => setFormAuthority(e.target.value)}
                  placeholder="e.g. USCG NMC"
                  className="font-mono w-full bg-[#0d1225] border border-white/10 rounded-lg px-3 py-2 text-sm
                    text-[#f0ece4] outline-none focus:border-[#2dd4bf] transition-colors"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="flex flex-col gap-1">
                  <label className="font-mono text-xs text-[#6b7594]">Issue Date</label>
                  <input
                    type="date"
                    value={formIssueDate}
                    onChange={(e) => setFormIssueDate(e.target.value)}
                    className="font-mono w-full bg-[#0d1225] border border-white/10 rounded-lg px-3 py-2 text-sm
                      text-[#f0ece4] outline-none focus:border-[#2dd4bf] transition-colors
                      [color-scheme:dark]"
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <label className="font-mono text-xs text-[#6b7594]">Expiry Date</label>
                  <input
                    type="date"
                    value={formExpiryDate}
                    onChange={(e) => setFormExpiryDate(e.target.value)}
                    className="font-mono w-full bg-[#0d1225] border border-white/10 rounded-lg px-3 py-2 text-sm
                      text-[#f0ece4] outline-none focus:border-[#2dd4bf] transition-colors
                      [color-scheme:dark]"
                  />
                </div>
              </div>

              <div className="flex flex-col gap-1">
                <label className="font-mono text-xs text-[#6b7594]">Notes</label>
                <textarea
                  value={formNotes}
                  onChange={(e) => setFormNotes(e.target.value)}
                  rows={2}
                  className="font-mono w-full bg-[#0d1225] border border-white/10 rounded-lg px-3 py-2 text-sm
                    text-[#f0ece4] outline-none focus:border-[#2dd4bf] transition-colors resize-none"
                />
              </div>

              {error && (
                <p className="font-mono text-xs text-red-400">{error}</p>
              )}

              <div className="flex items-center gap-2">
                <button
                  onClick={handleSave}
                  disabled={saving}
                  className="font-mono text-sm font-bold text-[#0a0e1a] bg-[#2dd4bf] hover:brightness-110
                    disabled:opacity-50 rounded-lg px-4 py-2 transition-[filter] duration-150"
                >
                  {saving ? 'Saving...' : editingId ? 'Update' : 'Add'}
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

          {/* Loading */}
          {loading && (
            <div className="flex flex-col gap-3">
              {[1, 2, 3].map((i) => (
                <div key={i} className="h-20 bg-[#111827] border border-white/8 rounded-xl animate-pulse" />
              ))}
            </div>
          )}

          {/* Empty state */}
          {!loading && credentials.length === 0 && !showForm && (
            <section className="bg-[#111827] border border-white/8 rounded-xl p-8 text-center">
              <p className="font-mono text-sm text-[#6b7594] mb-2">No credentials tracked yet</p>
              <p className="font-mono text-xs text-[#6b7594]/70">
                Add your MMC, STCW endorsements, medical certificate, TWIC, and other credentials to get expiry reminders.
              </p>
            </section>
          )}

          {/* Credentials list */}
          {!loading && sorted.map((c) => {
            const days = daysUntil(c.expiry_date)
            return (
              <section
                key={c.id}
                className={`bg-[#111827] border ${urgencyBorder(days)} rounded-xl p-4 flex flex-col gap-2`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="font-mono text-sm text-[#f0ece4] font-bold truncate">{c.title}</p>
                    <p className="font-mono text-xs text-[#6b7594] mt-0.5">
                      {TYPE_LABELS[c.credential_type] ?? c.credential_type}
                      {c.credential_number && <> · #{c.credential_number}</>}
                    </p>
                  </div>
                  <span className={`font-mono text-xs font-bold shrink-0 ${urgencyColor(days)}`}>
                    {urgencyLabel(days)}
                  </span>
                </div>

                {(c.issuing_authority || c.issue_date) && (
                  <div className="flex items-center gap-3 text-xs font-mono text-[#6b7594]">
                    {c.issuing_authority && <span>{c.issuing_authority}</span>}
                    {c.issue_date && <span>Issued {c.issue_date}</span>}
                  </div>
                )}

                {c.expiry_date && (
                  <div className="w-full bg-white/5 rounded-full h-1.5 mt-1">
                    <div
                      className={`h-full rounded-full transition-all ${
                        days !== null && days < 0
                          ? 'bg-red-400 w-full'
                          : days !== null && days <= 7
                            ? 'bg-red-400'
                            : days !== null && days <= 30
                              ? 'bg-amber-400'
                              : days !== null && days <= 90
                                ? 'bg-yellow-400'
                                : 'bg-[#2dd4bf]'
                      }`}
                      style={{
                        width: days !== null && days >= 0
                          ? `${Math.max(5, Math.min(100, ((365 - Math.min(days, 365)) / 365) * 100))}%`
                          : '100%',
                      }}
                    />
                  </div>
                )}

                {c.notes && (
                  <p className="font-mono text-xs text-[#6b7594]/80 mt-1">{c.notes}</p>
                )}

                <div className="flex items-center gap-3 mt-1">
                  <button
                    onClick={() => startEdit(c)}
                    className="font-mono text-xs text-[#2dd4bf] hover:underline"
                  >
                    Edit
                  </button>
                  {confirmDeleteId === c.id ? (
                    <div className="flex items-center gap-1.5">
                      <button
                        onClick={() => handleDelete(c.id)}
                        className="font-mono text-xs text-red-400 hover:underline"
                      >
                        Confirm
                      </button>
                      <button
                        onClick={() => setConfirmDeleteId(null)}
                        className="font-mono text-xs text-[#6b7594] hover:underline"
                      >
                        Cancel
                      </button>
                    </div>
                  ) : (
                    <button
                      onClick={() => setConfirmDeleteId(c.id)}
                      className="font-mono text-xs text-red-400/70 hover:text-red-400"
                    >
                      Delete
                    </button>
                  )}
                </div>
              </section>
            )
          })}

        </div>
      </main>
    </div>
  )
}

export default function CredentialsPage() {
  return (
    <AuthGuard>
      <CredentialsContent />
    </AuthGuard>
  )
}
