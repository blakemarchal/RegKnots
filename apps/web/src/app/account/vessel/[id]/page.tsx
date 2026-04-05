'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useRouter, useParams } from 'next/navigation'
import AuthGuard from '@/components/AuthGuard'
import { apiRequest, apiUpload } from '@/lib/api'

const VESSEL_TYPES = [
  'Containership',
  'Tanker',
  'Bulk Carrier',
  'OSV / Offshore Support',
  'Towing / Tugboat',
  'Passenger Vessel',
  'Ferry',
  'Fish Processing',
  'Research Vessel',
  'Other',
]

const ROUTE_OPTIONS = [
  { value: 'inland', label: 'Inland', desc: 'Rivers, lakes, and protected waters' },
  { value: 'coastal', label: 'Coastal', desc: 'Near-shore and coastal routes' },
  { value: 'international', label: 'International', desc: 'Offshore and international voyages' },
]

const CARGO_OPTIONS = [
  'Containers',
  'Petroleum / Oil',
  'Chemicals',
  'Liquefied Gas',
  'Dry Bulk',
  'Passengers',
  'Hazardous Materials',
  'Vehicles',
  'General Cargo',
  'None / Not Applicable',
]

const DOC_TYPE_OPTIONS = [
  { value: 'coi', label: 'Certificate of Inspection (COI)' },
  { value: 'safety_equipment', label: 'Safety Equipment Certificate' },
  { value: 'safety_construction', label: 'Safety Construction Certificate' },
  { value: 'safety_radio', label: 'Safety Radio Certificate' },
  { value: 'isps', label: 'ISPS Certificate' },
  { value: 'ism', label: 'ISM Certificate' },
  { value: 'other', label: 'Other Document' },
]

const DOC_TYPE_LABELS: Record<string, string> = Object.fromEntries(
  DOC_TYPE_OPTIONS.map((d) => [d.value, d.label]),
)

const STATUS_COLORS: Record<string, string> = {
  pending: 'bg-yellow-500/15 text-yellow-400 border-yellow-500/25',
  extracted: 'bg-blue-500/15 text-blue-400 border-blue-500/25',
  confirmed: 'bg-[#2dd4bf]/15 text-[#2dd4bf] border-[#2dd4bf]/25',
  failed: 'bg-red-500/15 text-red-400 border-red-500/25',
}

interface VesselData {
  id: string
  name: string
  vessel_type: string
  route_types: string[]
  cargo_types: string[]
  gross_tonnage: number | null
}

interface DocumentData {
  id: string
  vessel_id: string
  document_type: string
  filename: string
  file_size: number | null
  mime_type: string | null
  extracted_data: Record<string, unknown>
  extraction_status: string
  created_at: string
}

/* ── Extracted data review card ────────────────────────────────────── */

function ExtractionReviewCard({
  doc,
  onConfirm,
  onCancel,
  confirming,
}: {
  doc: DocumentData
  onConfirm: (corrections: Record<string, string>) => void
  onCancel: () => void
  confirming: boolean
}) {
  const [edits, setEdits] = useState<Record<string, string>>({})
  const [editingField, setEditingField] = useState<string | null>(null)

  const data = doc.extracted_data
  const fields = Object.entries(data).filter(
    ([, v]) => v !== null && v !== 'null' && String(v).trim() !== '',
  )

  if (doc.extraction_status === 'failed') {
    return (
      <div className="rounded-xl border border-red-500/20 bg-red-500/5 p-4">
        <p className="font-mono text-sm text-red-400">
          We couldn&apos;t read this document. Try a clearer photo or upload a PDF.
        </p>
        <button
          onClick={onCancel}
          className="mt-3 font-mono text-xs text-[#6b7594] hover:text-[#f0ece4] transition-colors"
        >
          Dismiss
        </button>
      </div>
    )
  }

  return (
    <div className="rounded-xl border border-[#2dd4bf]/30 bg-[#2dd4bf]/5 p-4 space-y-3">
      <div className="flex items-center gap-2 mb-1">
        <div className="w-8 h-8 rounded-full bg-[#2dd4bf]/15 flex items-center justify-center">
          <svg className="w-4 h-4 text-[#2dd4bf]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M9 12l2 2 4-4" strokeLinecap="round" strokeLinejoin="round" />
            <circle cx="12" cy="12" r="10" />
          </svg>
        </div>
        <div>
          <p className="font-display text-sm font-bold text-[#f0ece4]">
            We found these details in your document
          </p>
          <p className="font-mono text-[10px] text-[#6b7594]">
            Tap any value to correct it before saving
          </p>
        </div>
      </div>

      <div className="grid gap-1.5">
        {fields.map(([key, value]) => (
          <div
            key={key}
            className="flex items-start justify-between gap-2 px-2 py-1.5 rounded-lg
              hover:bg-white/3 transition-colors group"
          >
            <span className="font-mono text-[11px] text-[#6b7594] min-w-[120px] mt-0.5">
              {key.replace(/_/g, ' ')}
            </span>
            {editingField === key ? (
              <input
                autoFocus
                className="flex-1 font-mono text-xs text-[#f0ece4] bg-[#0d1225] border border-[#2dd4bf]/40
                  rounded px-2 py-1 outline-none"
                defaultValue={edits[key] ?? String(value)}
                onBlur={(e) => {
                  setEdits((p) => ({ ...p, [key]: e.target.value }))
                  setEditingField(null)
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') (e.target as HTMLInputElement).blur()
                }}
              />
            ) : (
              <button
                onClick={() => setEditingField(key)}
                className="flex-1 text-right font-mono text-xs text-[#f0ece4] group-hover:text-[#2dd4bf]
                  transition-colors cursor-text"
              >
                {edits[key] ?? String(value)}
              </button>
            )}
          </div>
        ))}
      </div>

      <div className="flex gap-2 pt-2">
        <button
          onClick={() => onConfirm(edits)}
          disabled={confirming}
          className="flex-1 bg-[#2dd4bf] hover:brightness-110 disabled:opacity-50
            text-[#0a0e1a] font-bold font-mono text-xs uppercase tracking-wider
            rounded-lg py-2.5 transition-[filter] duration-150"
        >
          {confirming ? 'Saving...' : 'Confirm & Save to Profile'}
        </button>
        <button
          onClick={onCancel}
          className="px-4 font-mono text-xs text-[#6b7594] hover:text-[#f0ece4]
            border border-white/10 rounded-lg transition-colors"
        >
          Cancel
        </button>
      </div>
    </div>
  )
}

/* ── Document list item ────────────────────────────────────────────── */

function DocumentItem({
  doc,
  onDelete,
}: {
  doc: DocumentData
  onDelete: (id: string) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const [deleting, setDeleting] = useState(false)

  const data = doc.extracted_data
  const fields = Object.entries(data).filter(
    ([, v]) => v !== null && v !== 'null' && String(v).trim() !== '',
  )

  return (
    <div className="rounded-xl border border-white/8 bg-[#111827]/60 overflow-hidden">
      <button
        onClick={() => setExpanded((p) => !p)}
        className="w-full flex items-center justify-between px-3 py-2.5 hover:bg-white/3 transition-colors"
      >
        <div className="flex items-center gap-2 text-left min-w-0">
          <span className="text-base flex-shrink-0">
            {doc.document_type === 'coi' ? '\uD83D\uDCC4' : '\uD83D\uDCC3'}
          </span>
          <div className="min-w-0">
            <p className="font-mono text-xs text-[#f0ece4] truncate">
              {DOC_TYPE_LABELS[doc.document_type] ?? doc.document_type}
            </p>
            <p className="font-mono text-[10px] text-[#6b7594]">
              {doc.filename} &middot; {new Date(doc.created_at).toLocaleDateString()}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0 ml-2">
          <span
            className={`font-mono text-[10px] px-2 py-0.5 rounded-full border ${STATUS_COLORS[doc.extraction_status] ?? ''}`}
          >
            {doc.extraction_status}
          </span>
          <svg
            className={`w-4 h-4 text-[#6b7594] transition-transform ${expanded ? 'rotate-180' : ''}`}
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>
      </button>

      {expanded && (
        <div className="px-3 pb-3 border-t border-white/5 pt-2 space-y-2">
          {fields.length > 0 ? (
            <div className="grid gap-1">
              {fields.map(([key, value]) => (
                <div key={key} className="flex gap-2">
                  <span className="font-mono text-[10px] text-[#6b7594] min-w-[110px]">
                    {key.replace(/_/g, ' ')}
                  </span>
                  <span className="font-mono text-[10px] text-[#f0ece4]">
                    {String(value)}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="font-mono text-[10px] text-[#6b7594]">No extracted data</p>
          )}
          <button
            onClick={(e) => {
              e.stopPropagation()
              if (!confirm('Delete this document?')) return
              setDeleting(true)
              onDelete(doc.id)
            }}
            disabled={deleting}
            className="font-mono text-[10px] text-red-400 hover:text-red-300 transition-colors disabled:opacity-50"
          >
            {deleting ? 'Deleting...' : 'Delete document'}
          </button>
        </div>
      )}
    </div>
  )
}

/* ── Main page ────────────────────────────────────────────────────── */

function VesselEditContent() {
  const router = useRouter()
  const params = useParams()
  const vesselId = params.id as string

  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)

  const [name, setName] = useState('')
  const [vesselType, setVesselType] = useState('')
  const [grossTonnage, setGrossTonnage] = useState('')
  const [routeTypes, setRouteTypes] = useState<string[]>([])
  const [cargoTypes, setCargoTypes] = useState<string[]>([])

  // Document state
  const [documents, setDocuments] = useState<DocumentData[]>([])
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState<string | null>(null)
  const [reviewDoc, setReviewDoc] = useState<DocumentData | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [docType, setDocType] = useState('coi')
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    apiRequest<VesselData[]>('/vessels')
      .then((vessels) => {
        const v = vessels.find((x) => x.id === vesselId)
        if (v) {
          setName(v.name)
          setVesselType(v.vessel_type)
          setGrossTonnage(v.gross_tonnage ? String(v.gross_tonnage) : '')
          setRouteTypes(v.route_types)
          setCargoTypes(v.cargo_types)
        } else {
          setError('Vessel not found')
        }
      })
      .catch(() => setError('Failed to load vessel'))
      .finally(() => setLoading(false))
  }, [vesselId])

  const fetchDocuments = useCallback(() => {
    apiRequest<DocumentData[]>(`/vessels/${vesselId}/documents`)
      .then(setDocuments)
      .catch(() => {}) // silent fail
  }, [vesselId])

  useEffect(() => {
    fetchDocuments()
  }, [fetchDocuments])

  function toggleRoute(r: string) {
    setRouteTypes((prev) => (prev.includes(r) ? prev.filter((x) => x !== r) : [...prev, r]))
  }

  function toggleCargo(c: string) {
    setCargoTypes((prev) => (prev.includes(c) ? prev.filter((x) => x !== c) : [...prev, c]))
  }

  async function handleSave() {
    if (!name.trim()) { setError('Vessel name is required'); return }
    if (routeTypes.length === 0) { setError('Select at least one route type'); return }
    setSaving(true)
    setError(null)
    try {
      await apiRequest(`/vessels/${vesselId}`, {
        method: 'PUT',
        body: JSON.stringify({
          name: name.trim(),
          vessel_type: vesselType,
          gross_tonnage: grossTonnage ? parseFloat(grossTonnage) : null,
          route_types: routeTypes,
          cargo_types: cargoTypes,
        }),
      })
      setSuccess(true)
      setTimeout(() => router.push('/account'), 600)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  async function handleFileSelect(file: File) {
    // Client-side validation
    const allowed = ['image/jpeg', 'image/png', 'image/webp', 'application/pdf']
    if (!allowed.includes(file.type)) {
      setError('Unsupported file type. Use JPEG, PNG, WebP, or PDF.')
      return
    }
    if (file.size > 10 * 1024 * 1024) {
      setError('File too large. Maximum size is 10 MB.')
      return
    }

    setError(null)
    setUploading(true)
    setUploadProgress('Uploading...')

    try {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('document_type', docType)

      setUploadProgress('Analyzing document with AI...')
      const result = await apiUpload<DocumentData>(
        `/vessels/${vesselId}/documents`,
        formData,
      )

      setUploadProgress(null)
      setUploading(false)

      if (result.extraction_status === 'extracted' || result.extraction_status === 'failed') {
        setReviewDoc(result)
      }
      fetchDocuments()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upload failed')
      setUploading(false)
      setUploadProgress(null)
    }
  }

  async function handleConfirm(corrections: Record<string, string>) {
    if (!reviewDoc) return
    setConfirming(true)
    try {
      await apiRequest(`/vessels/${vesselId}/documents/${reviewDoc.id}/confirm`, {
        method: 'POST',
        body: JSON.stringify({ corrections }),
      })
      setReviewDoc(null)
      fetchDocuments()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to confirm')
    } finally {
      setConfirming(false)
    }
  }

  async function handleDeleteDoc(docId: string) {
    try {
      await apiRequest(`/vessels/${vesselId}/documents/${docId}`, { method: 'DELETE' })
      setDocuments((prev) => prev.filter((d) => d.id !== docId))
    } catch {
      setError('Failed to delete document')
    }
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    const file = e.dataTransfer.files[0]
    if (file) handleFileSelect(file)
  }

  if (loading) {
    return (
      <div className="flex flex-col h-dvh bg-[#0a0e1a] items-center justify-center">
        <div className="w-6 h-6 border-2 border-[#2dd4bf] border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  return (
    <div className="flex flex-col h-dvh bg-[#0a0e1a]">
      {/* Header */}
      <header className="flex-shrink-0 flex items-center gap-3 px-4 py-3
        bg-[#111827]/95 backdrop-blur-md border-b border-white/8">
        <button
          onClick={() => router.push('/account')}
          className="w-9 h-9 flex items-center justify-center rounded-lg
            text-[#6b7594] hover:text-[#f0ece4] transition-colors duration-150"
          aria-label="Back to Account"
        >
          <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M19 12H5M12 5l-7 7 7 7" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
        <div className="flex flex-col">
          <h1 className="font-display text-xl font-bold text-[#f0ece4] tracking-wide leading-none">
            Edit Vessel
          </h1>
          <button
            onClick={() => router.push('/account')}
            className="font-mono text-xs text-[#6b7594] hover:text-[#2dd4bf] transition-colors duration-150 text-left mt-0.5"
          >
            &larr; Back to Account
          </button>
        </div>
      </header>

      <main className="flex-1 overflow-y-auto px-4 py-6">
        <div className="max-w-sm mx-auto flex flex-col gap-5">

          {/* Name */}
          <div className="flex flex-col gap-1">
            <label className="font-mono text-xs text-[#6b7594] uppercase tracking-wider">Vessel Name *</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="font-mono w-full bg-[#0d1225] border border-white/10 rounded-lg px-3 py-2.5 text-sm
                text-[#f0ece4] outline-none focus:border-[#2dd4bf] transition-colors"
            />
          </div>

          {/* Type */}
          <div className="flex flex-col gap-1">
            <label className="font-mono text-xs text-[#6b7594] uppercase tracking-wider">Vessel Type</label>
            <select
              value={vesselType}
              onChange={(e) => setVesselType(e.target.value)}
              className="font-mono w-full border border-white/10 rounded-lg px-3 py-2.5 text-sm
                outline-none focus:border-[#2dd4bf] transition-colors"
              style={{ backgroundColor: '#0d1225', color: '#f0ece4' }}
            >
              {VESSEL_TYPES.map((t) => (
                <option key={t} value={t} style={{ backgroundColor: '#111827', color: '#f0ece4' }}>
                  {t}
                </option>
              ))}
            </select>
          </div>

          {/* Tonnage */}
          <div className="flex flex-col gap-1">
            <label className="font-mono text-xs text-[#6b7594] uppercase tracking-wider">Gross Tonnage</label>
            <input
              type="number"
              value={grossTonnage}
              onChange={(e) => setGrossTonnage(e.target.value)}
              placeholder="e.g. 5000"
              className="font-mono w-full bg-[#0d1225] border border-white/10 rounded-lg px-3 py-2.5 text-sm
                text-[#f0ece4] outline-none focus:border-[#2dd4bf] transition-colors placeholder:text-[#6b7594]/50"
            />
          </div>

          {/* Route types */}
          <div className="flex flex-col gap-2">
            <label className="font-mono text-xs text-[#6b7594] uppercase tracking-wider">Route Types *</label>
            {ROUTE_OPTIONS.map((r) => {
              const selected = routeTypes.includes(r.value)
              return (
                <button
                  key={r.value}
                  type="button"
                  onClick={() => toggleRoute(r.value)}
                  className={`w-full p-3 rounded-xl border text-left transition-all duration-150 ${
                    selected
                      ? 'border-[#2dd4bf] bg-[#2dd4bf]/8'
                      : 'border-white/10 bg-[#0d1225] hover:border-white/20'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="font-mono text-sm font-medium text-[#f0ece4]">{r.label}</p>
                      <p className="font-mono text-xs text-[#6b7594] mt-0.5">{r.desc}</p>
                    </div>
                    {selected && (
                      <div className="w-4 h-4 rounded-full bg-[#2dd4bf] flex items-center justify-center ml-2">
                        <svg viewBox="0 0 12 12" className="w-2.5 h-2.5" fill="none" stroke="#0a0e1a" strokeWidth="2">
                          <path d="M2 6l3 3 5-5" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                      </div>
                    )}
                  </div>
                </button>
              )
            })}
          </div>

          {/* Cargo types */}
          <div className="flex flex-col gap-2">
            <label className="font-mono text-xs text-[#6b7594] uppercase tracking-wider">Cargo Types</label>
            <div className="flex flex-wrap gap-2">
              {CARGO_OPTIONS.map((c) => {
                const selected = cargoTypes.includes(c)
                return (
                  <button
                    key={c}
                    type="button"
                    onClick={() => toggleCargo(c)}
                    className={`font-mono px-3 py-1.5 rounded-full text-xs border transition-colors duration-150 ${
                      selected
                        ? 'bg-[#2dd4bf]/15 border-[#2dd4bf] text-[#2dd4bf]'
                        : 'bg-white/5 border-white/10 text-[#6b7594] hover:border-white/25 hover:text-[#f0ece4]'
                    }`}
                  >
                    {c}
                  </button>
                )
              })}
            </div>
          </div>

          {/* Error / success */}
          {error && (
            <p className="font-mono text-xs text-red-400 bg-red-400/10 border border-red-400/20 rounded-lg px-3 py-2">
              {error}
            </p>
          )}
          {success && (
            <p className="font-mono text-xs text-[#2dd4bf] bg-[#2dd4bf]/10 border border-[#2dd4bf]/20 rounded-lg px-3 py-2">
              Vessel updated. Redirecting...
            </p>
          )}

          {/* Save */}
          <button
            onClick={handleSave}
            disabled={saving}
            className="w-full bg-[#2dd4bf] hover:brightness-110 disabled:opacity-50
              text-[#0a0e1a] font-bold font-mono text-sm uppercase tracking-wider
              rounded-xl py-3 transition-[filter] duration-150"
          >
            {saving ? 'Saving...' : 'Save Vessel'}
          </button>

          {/* ── Documents Section ──────────────────────────────────── */}
          <div className="mt-4 pt-6 border-t border-white/8">
            <h2 className="font-display text-lg font-bold text-[#f0ece4] tracking-wide mb-1">
              Documents
            </h2>
            <p className="font-mono text-xs text-[#6b7594] mb-4">
              Upload your COI or vessel certificates to supercharge your compliance answers.
            </p>

            {/* Extraction review card */}
            {reviewDoc && (
              <div className="mb-4">
                <ExtractionReviewCard
                  doc={reviewDoc}
                  onConfirm={handleConfirm}
                  onCancel={() => setReviewDoc(null)}
                  confirming={confirming}
                />
              </div>
            )}

            {/* Doc type selector */}
            <div className="flex flex-col gap-1 mb-3">
              <label className="font-mono text-[10px] text-[#6b7594] uppercase tracking-wider">
                Document Type
              </label>
              <select
                value={docType}
                onChange={(e) => setDocType(e.target.value)}
                className="font-mono w-full border border-white/10 rounded-lg px-3 py-2 text-xs
                  outline-none focus:border-[#2dd4bf] transition-colors"
                style={{ backgroundColor: '#0d1225', color: '#f0ece4' }}
              >
                {DOC_TYPE_OPTIONS.map((d) => (
                  <option key={d.value} value={d.value} style={{ backgroundColor: '#111827', color: '#f0ece4' }}>
                    {d.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Upload drop zone */}
            <div
              onDrop={handleDrop}
              onDragOver={(e) => e.preventDefault()}
              onClick={() => !uploading && fileInputRef.current?.click()}
              className={`relative w-full rounded-xl border-2 border-dashed
                flex flex-col items-center justify-center py-8 px-4 cursor-pointer
                transition-all duration-200 group
                ${uploading
                  ? 'border-[#2dd4bf]/40 bg-[#2dd4bf]/5'
                  : 'border-white/15 hover:border-[#2dd4bf]/50 hover:bg-[#2dd4bf]/3 bg-[#0d1225]/50'
                }`}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept="image/jpeg,image/png,image/webp,application/pdf"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0]
                  if (f) handleFileSelect(f)
                  e.target.value = ''
                }}
              />
              {uploading ? (
                <>
                  <div className="w-8 h-8 border-2 border-[#2dd4bf] border-t-transparent rounded-full animate-spin mb-3" />
                  <p className="font-mono text-xs text-[#2dd4bf] animate-pulse">
                    {uploadProgress}
                  </p>
                </>
              ) : (
                <>
                  <div className="w-10 h-10 rounded-full bg-[#2dd4bf]/10 flex items-center justify-center mb-3
                    group-hover:bg-[#2dd4bf]/20 transition-colors">
                    <svg className="w-5 h-5 text-[#2dd4bf]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" strokeLinecap="round" strokeLinejoin="round" />
                      <polyline points="17 8 12 3 7 8" strokeLinecap="round" strokeLinejoin="round" />
                      <line x1="12" y1="3" x2="12" y2="15" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </div>
                  <p className="font-mono text-sm text-[#f0ece4] font-medium mb-1">
                    Upload COI or vessel document
                  </p>
                  <p className="font-mono text-[10px] text-[#6b7594] text-center">
                    Photo, scan, or PDF &mdash; we&apos;ll extract the details automatically
                  </p>
                  <p className="font-mono text-[9px] text-[#6b7594]/60 mt-2">
                    JPEG, PNG, WebP, or PDF &middot; Max 10 MB
                  </p>
                </>
              )}
            </div>

            {/* Uploaded documents list */}
            {documents.length > 0 && (
              <div className="mt-4 flex flex-col gap-2">
                <p className="font-mono text-[10px] text-[#6b7594] uppercase tracking-wider">
                  Uploaded Documents
                </p>
                {documents.map((doc) => (
                  <DocumentItem key={doc.id} doc={doc} onDelete={handleDeleteDoc} />
                ))}
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  )
}

export default function VesselEditPage() {
  return (
    <AuthGuard>
      <VesselEditContent />
    </AuthGuard>
  )
}
