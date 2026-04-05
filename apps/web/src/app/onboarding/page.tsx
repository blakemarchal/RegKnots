'use client'

import { useState, useEffect, useRef } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { apiRequest, apiUpload } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'

// ── Constants ──────────────────────────────────────────────────────────────────

const STEP_TITLES = ['Vessel Identity', 'Type & Size', 'Route', 'Cargo', 'Review']

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
  {
    value: 'inland',
    emoji: '\uD83C\uDFE0',
    label: 'Inland',
    desc: 'Rivers, lakes, and protected waters',
  },
  {
    value: 'coastal',
    emoji: '\uD83C\uDF0A',
    label: 'Coastal',
    desc: 'Near-shore and coastal routes',
  },
  {
    value: 'international',
    emoji: '\uD83C\uDF10',
    label: 'International',
    desc: 'Offshore and international voyages',
  },
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

// ── Types ──────────────────────────────────────────────────────────────────────

interface VesselForm {
  name: string
  imo_mmsi: string
  vessel_type: string
  gross_tonnage: string
  route_types: string[]
  cargo_types: string[]
}

interface VesselResponse {
  id: string
  name: string
  vessel_type: string
  gross_tonnage: number | null
  route_types: string[]
  cargo_types: string[]
}

interface PreviewResult {
  extracted_data: Record<string, unknown>
  preview_id: string
  filename: string
  mime_type: string
}

const EMPTY_FORM: VesselForm = {
  name: '',
  imo_mmsi: '',
  vessel_type: '',
  gross_tonnage: '',
  route_types: [],
  cargo_types: [],
}

type ExtractionPhase = 'idle' | 'uploading' | 'reading' | 'extracting' | 'done' | 'error'

const PHASE_LABELS: Record<ExtractionPhase, string> = {
  idle: '',
  uploading: 'Uploading document...',
  reading: 'Reading your COI...',
  extracting: 'Extracting vessel details...',
  done: 'Done!',
  error: 'Could not read document',
}

const PHASE_PROGRESS: Record<ExtractionPhase, number> = {
  idle: 0, uploading: 25, reading: 55, extracting: 85, done: 100, error: 0,
}

// ── Vessel type mapping (extracted text → dropdown value) ─────────────────────

function mapVesselType(extracted: string): string {
  const lower = extracted.toLowerCase()
  if (lower.includes('container')) return 'Containership'
  if (lower.includes('tanker') || lower.includes('tank vessel') || lower.includes('tank barge')) return 'Tanker'
  if (lower.includes('bulk')) return 'Bulk Carrier'
  if (lower.includes('osv') || lower.includes('offshore') || lower.includes('supply')) return 'OSV / Offshore Support'
  if (lower.includes('tow') || lower.includes('tug')) return 'Towing / Tugboat'
  if (lower.includes('passenger') || lower.includes('small passenger')) return 'Passenger Vessel'
  if (lower.includes('ferry')) return 'Ferry'
  if (lower.includes('fish')) return 'Fish Processing'
  if (lower.includes('research')) return 'Research Vessel'
  return 'Other'
}

function mapRouteTypes(extracted: string): string[] {
  const lower = extracted.toLowerCase()
  const routes: string[] = []
  if (['inland', 'river', 'lake', 'great lakes'].some((k) => lower.includes(k))) routes.push('inland')
  if (['coast', 'near-coastal', 'coastwise'].some((k) => lower.includes(k))) routes.push('coastal')
  if (['ocean', 'international', 'unlimited'].some((k) => lower.includes(k))) routes.push('international')
  return routes.length > 0 ? routes : ['coastal']
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function ProgressBar({ step }: { step: number }) {
  return (
    <div>
      <div className="flex gap-1">
        {[1, 2, 3, 4, 5].map((n) => (
          <div
            key={n}
            className={`h-1 flex-1 rounded-full transition-all duration-300 ${
              n <= step ? 'bg-[--color-teal]' : 'bg-white/10'
            }`}
          />
        ))}
      </div>
      <p className="font-mono text-xs text-[--color-muted] mt-2">
        Step {step} of 5 — {STEP_TITLES[step - 1]}
      </p>
    </div>
  )
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <label className="font-mono text-xs text-[--color-muted] uppercase tracking-wider">
      {children}
    </label>
  )
}

function TextInput({
  value,
  onChange,
  placeholder,
  type = 'text',
  error,
  autoFocus,
}: {
  value: string
  onChange: (v: string) => void
  placeholder?: string
  type?: string
  error?: string
  autoFocus?: boolean
}) {
  return (
    <input
      type={type}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      autoFocus={autoFocus}
      className={`font-mono w-full bg-[--color-surface-dim] border rounded-lg px-3 py-2.5 text-sm text-[--color-off-white] outline-none transition-colors placeholder:text-[--color-muted]/50 ${
        error
          ? 'border-red-400/60 focus:border-red-400'
          : 'border-white/10 focus:border-[--color-teal]'
      }`}
    />
  )
}

function HelperText({ children, variant = 'muted' }: { children: React.ReactNode; variant?: 'muted' | 'error' | 'nudge' }) {
  const cls =
    variant === 'error'
      ? 'text-red-400'
      : variant === 'nudge'
      ? 'text-[--color-amber]/80'
      : 'text-[--color-muted]'
  return <p className={`font-mono text-xs mt-1.5 ${cls}`}>{children}</p>
}

function ReviewRow({
  label,
  value,
  onEdit,
}: {
  label: string
  value: string
  onEdit: () => void
}) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="min-w-0">
        <p className="font-mono text-xs text-[--color-muted] uppercase tracking-wider">{label}</p>
        <p className="font-mono text-sm text-[--color-off-white] mt-0.5 break-words">{value}</p>
      </div>
      <button
        onClick={onEdit}
        className="font-mono text-xs text-[--color-teal] hover:underline shrink-0 mt-0.5"
      >
        Edit
      </button>
    </div>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function OnboardingPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const isAddMode = searchParams.get('add') === 'true'
  const { addVessel, setActiveVessel } = useAuthStore()

  // step=0 is the COI fast-track screen; steps 1-5 are the original flow
  const [step, setStep] = useState(0)
  const [direction, setDirection] = useState<'forward' | 'back'>('forward')
  const [form, setForm] = useState<VesselForm>(EMPTY_FORM)
  const [errors, setErrors] = useState<Partial<Record<keyof VesselForm, string>>>({})
  const [completedVessels, setCompletedVessels] = useState<VesselForm[]>([])
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  // COI fast-track state
  const [extractionPhase, setExtractionPhase] = useState<ExtractionPhase>('idle')
  const [coiPreviewId, setCoiPreviewId] = useState<string | null>(null)
  const [coiExtractedData, setCoiExtractedData] = useState<Record<string, unknown> | null>(null)
  const [coiError, setCoiError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const phaseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  function startPhaseTimer() {
    setExtractionPhase('uploading')
    phaseTimerRef.current = setTimeout(() => {
      setExtractionPhase('reading')
      phaseTimerRef.current = setTimeout(() => {
        setExtractionPhase('extracting')
      }, 3000)
    }, 2000)
  }

  function stopPhaseTimer(success: boolean) {
    if (phaseTimerRef.current) {
      clearTimeout(phaseTimerRef.current)
      phaseTimerRef.current = null
    }
    setExtractionPhase(success ? 'done' : 'error')
  }

  // ── Helpers ──────────────────────────────────────────────────────────────────

  function patch(key: keyof VesselForm, value: string | string[]) {
    setForm((f) => ({ ...f, [key]: value }))
    if (errors[key]) setErrors((e) => ({ ...e, [key]: undefined }))
  }

  function toggleRoute(r: string) {
    setForm((f) => ({
      ...f,
      route_types: f.route_types.includes(r)
        ? f.route_types.filter((x) => x !== r)
        : [...f.route_types, r],
    }))
    if (errors.route_types) setErrors((e) => ({ ...e, route_types: undefined }))
  }

  function toggleCargo(c: string) {
    setForm((f) => ({
      ...f,
      cargo_types: f.cargo_types.includes(c)
        ? f.cargo_types.filter((x) => x !== c)
        : [...f.cargo_types, c],
    }))
  }

  function validateStep(s: number): Partial<Record<keyof VesselForm, string>> {
    const e: Partial<Record<keyof VesselForm, string>> = {}
    if (s === 1 && !form.name.trim()) e.name = 'Vessel name is required'
    if (s === 2 && !form.vessel_type) e.vessel_type = 'Please select a vessel type'
    if (s === 3 && form.route_types.length === 0) e.route_types = 'Please select at least one route type'
    return e
  }

  function advance() {
    const e = validateStep(step)
    if (Object.keys(e).length > 0) {
      setErrors(e)
      return
    }
    setErrors({})
    setDirection('forward')
    setStep((s) => s + 1)
  }

  function goBack() {
    setErrors({})
    setDirection('back')
    // From step 1, go back to step 0 (COI screen)
    setStep((s) => (s <= 1 ? 0 : s - 1))
  }

  function jumpToStep(n: number) {
    setErrors({})
    setDirection(n < step ? 'back' : 'forward')
    setStep(n)
  }

  function addAnotherVessel() {
    setCompletedVessels((prev) => [...prev, form])
    setForm(EMPTY_FORM)
    setCoiPreviewId(null)
    setCoiExtractedData(null)
    setErrors({})
    setDirection('forward')
    setStep(0)
  }

  // ── COI upload handler ─────────────────────────────────────────────────────

  async function handleCoiUpload(file: File) {
    const allowed = ['image/jpeg', 'image/png', 'image/webp', 'application/pdf']
    if (!allowed.includes(file.type)) {
      setCoiError('Unsupported file type. Use JPEG, PNG, WebP, or PDF.')
      return
    }
    if (file.size > 10 * 1024 * 1024) {
      setCoiError('File too large. Maximum size is 10 MB.')
      return
    }

    setCoiError(null)
    startPhaseTimer()

    try {
      const formData = new FormData()
      formData.append('file', file)

      const result = await apiUpload<PreviewResult>(
        '/documents/extract-preview',
        formData,
      )

      stopPhaseTimer(true)
      setCoiPreviewId(result.preview_id)
      setCoiExtractedData(result.extracted_data)

      // Pre-fill the form
      const d = result.extracted_data
      const preFilled: VesselForm = {
        name: (d.vessel_name as string) || '',
        imo_mmsi: (d.imo_number as string) || (d.official_number as string) || '',
        vessel_type: d.vessel_type ? mapVesselType(d.vessel_type as string) : '',
        gross_tonnage: d.gross_tonnage ? String(d.gross_tonnage).replace(',', '') : '',
        route_types: d.route ? mapRouteTypes(d.route as string) : [],
        cargo_types: [],
      }
      setForm(preFilled)

      // Jump to review after a short delay to show "Done!"
      setTimeout(() => {
        setDirection('forward')
        setStep(5)
      }, 800)
    } catch (e) {
      stopPhaseTimer(false)
      setCoiError(e instanceof Error ? e.message : 'Could not extract data. Try a clearer photo.')
      setTimeout(() => setExtractionPhase('idle'), 2000)
    }
  }

  // ── Final submit ────────────────────────────────────────────────────────────

  async function handleSetSail() {
    setIsSubmitting(true)
    setSubmitError(null)

    const allForms = [...completedVessels, form]
    const created: { id: string; name: string }[] = []

    try {
      for (let i = 0; i < allForms.length; i++) {
        const v = allForms[i]
        const result = await apiRequest<VesselResponse>('/vessels', {
          method: 'POST',
          body: JSON.stringify({
            name: v.name.trim(),
            imo_mmsi: v.imo_mmsi.trim() || null,
            vessel_type: v.vessel_type,
            gross_tonnage: v.gross_tonnage ? parseFloat(v.gross_tonnage) : null,
            route_types: v.route_types,
            cargo_types: v.cargo_types,
          }),
        })
        created.push({ id: result.id, name: result.name })

        // Attach the COI preview document to the first vessel (current form)
        if (i === allForms.length - 1 && coiPreviewId && coiExtractedData) {
          try {
            await apiRequest(`/vessels/${result.id}/documents/from-preview`, {
              method: 'POST',
              body: JSON.stringify({
                preview_id: coiPreviewId,
                document_type: 'coi',
                extracted_data: coiExtractedData,
              }),
            })
          } catch {
            // Non-fatal: vessel is created, COI attachment just failed
            console.warn('Failed to attach COI preview document')
          }
        }
      }

      for (const v of created) {
        addVessel(v)
      }
      setActiveVessel(created[0].id)
      router.replace(isAddMode ? '/account' : '/')
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : 'Failed to save vessel. Please try again.')
      setIsSubmitting(false)
    }
  }

  // ── Keyboard navigation ───────────────────────────────────────────────────────

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key !== 'Enter') return
      const tag = (e.target as HTMLElement).tagName
      if (tag === 'BUTTON' || tag === 'SELECT' || tag === 'TEXTAREA') return
      if (step >= 1 && step < 5) advance()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [step, form]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Route label helper ─────────────────────────────────────────────────────

  function routeLabels(values: string[]) {
    return values.map((v) => ROUTE_OPTIONS.find((r) => r.value === v)?.label ?? v).join(', ') || 'Not specified'
  }

  // ── Step renderers ────────────────────────────────────────────────────────────

  function renderStep0() {
    const isExtracting = extractionPhase !== 'idle' && extractionPhase !== 'error'
    const pct = PHASE_PROGRESS[extractionPhase]

    return (
      <div className="flex flex-col gap-6 items-center text-center">
        <div>
          <h2 className="font-display text-2xl font-bold text-[--color-off-white] tracking-wide">
            {isAddMode ? 'Add a vessel' : 'Got your COI handy?'}
          </h2>
          <p className="font-mono text-sm text-[--color-muted] mt-2 max-w-xs mx-auto">
            Upload a photo or PDF of your Certificate of Inspection and we&apos;ll fill in your vessel details automatically.
          </p>
        </div>

        {/* Upload zone */}
        <div
          onClick={() => !isExtracting && fileInputRef.current?.click()}
          onDrop={(e) => {
            e.preventDefault()
            const f = e.dataTransfer.files[0]
            if (f) handleCoiUpload(f)
          }}
          onDragOver={(e) => e.preventDefault()}
          className={`relative w-full rounded-xl border-2 border-dashed
            flex flex-col items-center justify-center py-10 px-4 cursor-pointer
            transition-all duration-200 group
            ${isExtracting
              ? 'border-[--color-teal]/40 bg-[--color-teal]/5'
              : 'border-white/15 hover:border-[--color-teal]/50 hover:bg-[--color-teal]/3 bg-[--color-surface-dim]'
            }`}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp,application/pdf"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) handleCoiUpload(f)
              e.target.value = ''
            }}
          />
          {isExtracting ? (
            <div className="w-full px-4 space-y-3">
              <div className="w-8 h-8 border-2 border-[--color-teal] border-t-transparent rounded-full animate-spin mx-auto" />
              <div className="h-1.5 w-full rounded-full bg-white/8 overflow-hidden">
                <div
                  className="h-full rounded-full bg-[--color-teal] transition-all duration-700 ease-out"
                  style={{ width: `${pct}%` }}
                />
              </div>
              <p className="font-mono text-xs text-[--color-teal] animate-pulse">
                {PHASE_LABELS[extractionPhase]}
              </p>
            </div>
          ) : (
            <>
              <div className="w-12 h-12 rounded-full bg-[--color-teal]/10 flex items-center justify-center mb-3
                group-hover:bg-[--color-teal]/20 transition-colors">
                <svg className="w-6 h-6 text-[--color-teal]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" strokeLinecap="round" strokeLinejoin="round" />
                  <polyline points="17 8 12 3 7 8" strokeLinecap="round" strokeLinejoin="round" />
                  <line x1="12" y1="3" x2="12" y2="15" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </div>
              <p className="font-mono text-sm text-[--color-off-white] font-medium mb-1">
                Upload your COI
              </p>
              <p className="font-mono text-[10px] text-[--color-muted]">
                Photo, scan, or PDF &middot; Max 10 MB
              </p>
            </>
          )}
        </div>

        {coiError && (
          <p className="font-mono text-xs text-red-400 bg-red-400/10 border border-red-400/20 rounded-lg px-3 py-2 w-full">
            {coiError}
          </p>
        )}

        {/* Skip link */}
        <button
          onClick={() => {
            setDirection('forward')
            setStep(1)
          }}
          className="font-mono text-sm text-[--color-muted] hover:text-[--color-off-white] transition-colors"
        >
          Skip &mdash; I&apos;ll enter details manually
        </button>
      </div>
    )
  }

  function renderStep1() {
    return (
      <div className="flex flex-col gap-5">
        <div className="flex flex-col gap-1.5">
          <FieldLabel>Vessel Name *</FieldLabel>
          <TextInput
            value={form.name}
            onChange={(v) => patch('name', v)}
            placeholder="e.g. MV Pacific Star"
            error={errors.name}
            autoFocus
          />
          {errors.name && <HelperText variant="error">{errors.name}</HelperText>}
        </div>

        <div className="flex flex-col gap-1.5">
          <FieldLabel>IMO Number or MMSI</FieldLabel>
          <TextInput
            value={form.imo_mmsi}
            onChange={(v) => patch('imo_mmsi', v)}
            placeholder="e.g. 9123456 or 338123456"
          />
          <HelperText>Optional — helps us auto-populate vessel details in a future update</HelperText>
        </div>

        <p className="font-mono text-xs text-[--color-muted] italic border-t border-white/8 pt-4">
          The more you share, the more precise your compliance answers will be.
        </p>
      </div>
    )
  }

  function renderStep2() {
    return (
      <div className="flex flex-col gap-5">
        <div className="flex flex-col gap-1.5">
          <FieldLabel>Vessel Type *</FieldLabel>
          <select
            value={form.vessel_type}
            onChange={(e) => patch('vessel_type', e.target.value)}
            className={`font-mono w-full border rounded-lg px-3 py-2.5 text-sm outline-none transition-colors ${
              errors.vessel_type
                ? 'border-red-400/60 focus:border-red-400'
                : 'border-white/10 focus:border-[--color-teal]'
            }`}
            style={{ backgroundColor: '#0d1225', color: '#f0ece4' }}
          >
            <option value="" disabled style={{ backgroundColor: '#0d1225' }}>
              Select vessel type
            </option>
            {VESSEL_TYPES.map((t) => (
              <option key={t} value={t} style={{ backgroundColor: '#111827', color: '#f0ece4' }}>
                {t}
              </option>
            ))}
          </select>
          {errors.vessel_type && <HelperText variant="error">{errors.vessel_type}</HelperText>}
        </div>

        <div className="flex flex-col gap-1.5">
          <FieldLabel>Gross Tonnage</FieldLabel>
          <TextInput
            type="number"
            value={form.gross_tonnage}
            onChange={(v) => patch('gross_tonnage', v)}
            placeholder="e.g. 5000"
          />
          <HelperText>
            Optional — but tonnage determines which CFR subchapters apply to your vessel
          </HelperText>
          {!form.gross_tonnage && (
            <HelperText variant="nudge">
              Tonnage thresholds affect which regulations apply. Adding it improves answer accuracy.
            </HelperText>
          )}
        </div>
      </div>
    )
  }

  function renderStep3() {
    return (
      <div className="flex flex-col gap-3">
        <HelperText>Select all that apply — many vessels operate on multiple route types.</HelperText>
        {ROUTE_OPTIONS.map((r) => {
          const selected = form.route_types.includes(r.value)
          return (
            <button
              key={r.value}
              type="button"
              onClick={() => toggleRoute(r.value)}
              className={`w-full p-4 rounded-xl border text-left transition-all duration-150 ${
                selected
                  ? 'border-[--color-teal] bg-[--color-teal]/8'
                  : 'border-white/10 bg-[--color-surface-dim] hover:border-white/20'
              }`}
            >
              <div className="flex items-center gap-3">
                <span className="text-2xl leading-none" aria-hidden="true">
                  {r.emoji}
                </span>
                <div>
                  <p className="font-mono text-sm font-medium text-[--color-off-white]">{r.label}</p>
                  <p className="font-mono text-xs text-[--color-muted] mt-0.5">{r.desc}</p>
                </div>
                {selected && (
                  <div className="ml-auto w-4 h-4 rounded-full bg-[--color-teal] flex items-center justify-center">
                    <svg viewBox="0 0 12 12" className="w-2.5 h-2.5" fill="none" stroke="#0a0e1a" strokeWidth="2">
                      <path d="M2 6l3 3 5-5" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </div>
                )}
              </div>
            </button>
          )
        })}
        {errors.route_types && (
          <HelperText variant="error">{errors.route_types}</HelperText>
        )}
      </div>
    )
  }

  function renderStep4() {
    return (
      <div className="flex flex-col gap-4">
        <HelperText>
          Optional — hazardous cargo triggers additional CFR Title 49 requirements. Selecting your
          cargo types sharpens your answers.
        </HelperText>
        <div className="flex flex-wrap gap-2">
          {CARGO_OPTIONS.map((c) => {
            const selected = form.cargo_types.includes(c)
            return (
              <button
                key={c}
                type="button"
                onClick={() => toggleCargo(c)}
                className={`font-mono px-3 py-1.5 rounded-full text-xs border transition-colors duration-150 ${
                  selected
                    ? 'bg-[--color-teal]/15 border-[--color-teal] text-[--color-teal]'
                    : 'bg-white/5 border-white/10 text-[--color-muted] hover:border-white/25 hover:text-[--color-off-white]'
                }`}
              >
                {c}
              </button>
            )
          })}
        </div>
      </div>
    )
  }

  function renderStep5() {
    return (
      <div className="flex flex-col gap-5">
        {/* COI pre-fill banner */}
        {coiPreviewId && (
          <div className="flex items-center gap-2 bg-[--color-teal]/8 border border-[--color-teal]/25 rounded-xl px-4 py-3">
            <svg className="w-4 h-4 text-[--color-teal] flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M9 12l2 2 4-4" strokeLinecap="round" strokeLinejoin="round" />
              <circle cx="12" cy="12" r="10" />
            </svg>
            <p className="font-mono text-xs text-[--color-teal]">
              Pre-filled from your COI — review and edit below
            </p>
          </div>
        )}

        {/* Previously added vessels */}
        {completedVessels.length > 0 && (
          <div className="bg-[--color-surface-dim] border border-white/8 rounded-xl p-4">
            <p className="font-mono text-xs text-[--color-muted] uppercase tracking-wider mb-3">
              Previously added
            </p>
            <div className="flex flex-col gap-2">
              {completedVessels.map((v, i) => (
                <div key={i} className="flex items-center gap-2">
                  <span className="w-1.5 h-1.5 rounded-full bg-[--color-teal]" />
                  <p className="font-mono text-sm text-[--color-off-white]">{v.name}</p>
                  <p className="font-mono text-xs text-[--color-muted]">— {v.vessel_type}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Current vessel review */}
        <div className="bg-[--color-surface-mid] border border-white/8 rounded-xl p-5 flex flex-col gap-4">
          <ReviewRow label="Vessel Name" value={form.name} onEdit={() => jumpToStep(1)} />
          {form.imo_mmsi && (
            <ReviewRow label="IMO / MMSI" value={form.imo_mmsi} onEdit={() => jumpToStep(1)} />
          )}
          <div className="border-t border-white/8" />
          <ReviewRow label="Type" value={form.vessel_type} onEdit={() => jumpToStep(2)} />
          {form.gross_tonnage && (
            <ReviewRow
              label="Gross Tonnage"
              value={`${form.gross_tonnage} GT`}
              onEdit={() => jumpToStep(2)}
            />
          )}
          <div className="border-t border-white/8" />
          <ReviewRow label="Route" value={routeLabels(form.route_types)} onEdit={() => jumpToStep(3)} />
          <div className="border-t border-white/8" />
          <ReviewRow
            label="Cargo"
            value={form.cargo_types.length > 0 ? form.cargo_types.join(', ') : 'Not specified'}
            onEdit={() => jumpToStep(4)}
          />
        </div>

        {/* Add another vessel */}
        <button
          type="button"
          onClick={addAnotherVessel}
          className="font-mono text-sm text-[--color-teal] hover:underline text-center"
        >
          + Add another vessel
        </button>

        {/* Submit error */}
        {submitError && (
          <p className="font-mono text-xs text-red-400 bg-red-400/10 border border-red-400/20 rounded-lg px-3 py-2">
            {submitError}
          </p>
        )}

        {/* Set Sail CTA */}
        <button
          type="button"
          onClick={handleSetSail}
          disabled={isSubmitting}
          className="w-full bg-[--color-teal] hover:brightness-110 disabled:opacity-50 disabled:cursor-not-allowed text-[--color-navy] font-bold font-mono text-sm uppercase tracking-wider rounded-xl py-3.5 transition-[filter] duration-150"
        >
          {isSubmitting ? 'Saving\u2026' : isAddMode ? 'Save Vessel' : 'Set Sail'}
        </button>
      </div>
    )
  }

  // ── Layout ────────────────────────────────────────────────────────────────────

  const isStep0 = step === 0
  const stepRenderers = [renderStep0, renderStep1, renderStep2, renderStep3, renderStep4, renderStep5]
  const stepContent = stepRenderers[step]

  return (
    <main className="min-h-screen bg-[--color-navy] flex flex-col">
      {/* Header — hide progress bar on step 0 */}
      {!isStep0 && (
        <header className="flex-shrink-0 px-5 pt-8 pb-5 bg-[--color-charcoal]/60 border-b border-white/8">
          <div className="max-w-sm mx-auto">
            <ProgressBar step={step} />
          </div>
        </header>
      )}

      {/* Scrollable step area */}
      <div className="flex-1 overflow-y-auto">
        <div
          key={step}
          className={`max-w-sm mx-auto px-5 ${isStep0 ? 'py-16' : 'py-7'} animate-[${
            direction === 'forward' ? 'stepInRight' : 'stepInLeft'
          }_0.28s_ease-out]`}
        >
          {stepContent()}
        </div>
      </div>

      {/* Navigation footer — hide on step 0 */}
      {!isStep0 && (
        <footer className="flex-shrink-0 bg-[--color-charcoal]/60 border-t border-white/8 px-5 py-4">
          <div className="max-w-sm mx-auto flex items-center justify-between gap-3">
            <button
              type="button"
              onClick={goBack}
              disabled={isSubmitting}
              className="font-mono text-sm text-[--color-muted] hover:text-[#f0ece4] transition-[color] duration-150 disabled:opacity-50"
            >
              &larr; Back
            </button>

            {step < 5 && (
              <button
                type="button"
                onClick={advance}
                className="font-mono bg-[--color-teal] hover:brightness-110 text-[--color-navy] font-bold text-sm uppercase tracking-wider rounded-lg px-6 py-2.5 transition-[filter] duration-150"
              >
                {step === 4 ? 'Review' : 'Continue \u2192'}
              </button>
            )}
          </div>
        </footer>
      )}
    </main>
  )
}
