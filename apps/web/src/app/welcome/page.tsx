'use client'

import { useState, useRef, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import AuthGuard from '@/components/AuthGuard'
import { apiRequest, apiUpload } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import { ComingUpWidget } from '@/components/ComingUpWidget'
import { ExtractionProgress, useExtractionPhase } from '@/components/ExtractionProgress'

// ── Constants ─────────────────────────────────────────────────────────────

const VESSEL_TYPES = [
  'Containership', 'Tanker', 'Bulk Carrier',
  'OSV / Offshore Support', 'Towing / Tugboat',
  'Passenger Vessel', 'Ferry', 'Fish Processing',
  'Research Vessel', 'Other',
]

const ROUTE_OPTIONS = [
  { value: 'inland', label: 'Inland', desc: 'Rivers, lakes, protected waters' },
  { value: 'coastal', label: 'Coastal', desc: 'Near-shore and coastal' },
  { value: 'international', label: 'International', desc: 'Offshore, international voyages' },
]

const CARGO_OPTIONS = [
  'Containers', 'Petroleum / Oil', 'Chemicals', 'Liquefied Gas', 'Dry Bulk',
  'Passengers', 'Hazardous Materials', 'Vehicles', 'General Cargo',
  'None / Not Applicable',
]

const SUBCHAPTERS = ['T', 'K', 'H', 'I', 'R', 'C', 'D', 'L', 'O', 'S', 'U']

const CREDENTIAL_TYPES = [
  { value: 'mmc', label: 'MMC' },
  { value: 'stcw', label: 'STCW Endorsement' },
  { value: 'medical', label: 'Medical Certificate' },
  { value: 'twic', label: 'TWIC' },
  { value: 'other', label: 'Other' },
]

// Sprint D6.31 — added Step 0 for persona + jurisdiction_focus. Step 0
// runs first; users who pick a non-mariner persona see the vessel step
// (Step 1) marked as optional. The 4 = success step stays at the end.
type Step = 0 | 1 | 2 | 3 | 4
type Path = 'unchosen' | 'coi' | 'manual'

// Persona options — match VALID_PERSONAS in the API.
const PERSONA_OPTIONS = [
  { value: 'mariner_shipboard',     label: 'Mariner / shipboard' },
  { value: 'teacher_instructor',    label: 'Teacher / instructor' },
  { value: 'shore_side_compliance', label: 'Shore-side compliance' },
  { value: 'legal_consultant',      label: 'Maritime attorney / consultant' },
  { value: 'cadet_student',         label: 'Cadet / student' },
  { value: 'other',                 label: 'Other' },
]

// Jurisdiction focus options — US floated to top per design call.
// All 9 flag-state corpora exposed plus an "international mixed" catch-all.
const JURISDICTION_OPTIONS = [
  { value: 'us',                   label: 'United States' },
  { value: 'uk',                   label: 'United Kingdom' },
  { value: 'au',                   label: 'Australia' },
  { value: 'no',                   label: 'Norway' },
  { value: 'sg',                   label: 'Singapore' },
  { value: 'hk',                   label: 'Hong Kong' },
  { value: 'bs',                   label: 'Bahamas' },
  { value: 'lr',                   label: 'Liberia' },
  { value: 'mh',                   label: 'Marshall Islands' },
  { value: 'international_mixed',  label: 'International / mixed' },
]

interface CompletedSteps {
  vessel: boolean
  coi: boolean
  credential: boolean
}

interface PreviewExtraction {
  preview_id: string
  filename: string
  mime_type: string
  extracted_data: Record<string, unknown>
}

// Tracks which fields were auto-populated from a COI (for the ✓ badge).
type PrefilledSet = Record<string, boolean>

// ── Helpers ──────────────────────────────────────────────────────────────

function asString(v: unknown): string {
  if (v === null || v === undefined) return ''
  if (typeof v === 'string') return v.toLowerCase() === 'null' ? '' : v
  if (Array.isArray(v)) return v.map(asString).filter(Boolean).join('\n')
  if (typeof v === 'object') {
    return Object.entries(v as Record<string, unknown>)
      .filter(([, val]) => val !== null && val !== undefined && String(val).toLowerCase() !== 'null')
      .map(([k, val]) => `${k.replace(/_/g, ' ')}: ${asString(val)}`)
      .join('; ')
  }
  return String(v)
}

function deriveRouteTypes(route: unknown): string[] {
  const s = asString(route).toLowerCase()
  if (!s) return []
  const types: string[] = []
  if (/inland|river|lake|great lakes/.test(s)) types.push('inland')
  if (/coast|near-coastal|coastwise/.test(s)) types.push('coastal')
  if (/ocean|international|unlimited/.test(s)) types.push('international')
  return types
}

function matchVesselType(raw: unknown): string | null {
  const s = asString(raw)
  if (!s) return null
  const lc = s.toLowerCase()
  const hit = VESSEL_TYPES.find((t) => t.toLowerCase() === lc)
  if (hit) return hit
  // Soft match common variants just in case Claude drifts.
  if (/passenger/.test(lc)) return 'Passenger Vessel'
  if (/tank/.test(lc)) return 'Tanker'
  if (/container/.test(lc)) return 'Containership'
  if (/bulk/.test(lc)) return 'Bulk Carrier'
  if (/tow|tug/.test(lc)) return 'Towing / Tugboat'
  if (/osv|offshore/.test(lc)) return 'OSV / Offshore Support'
  if (/ferry/.test(lc)) return 'Ferry'
  if (/fish/.test(lc)) return 'Fish Processing'
  if (/research/.test(lc)) return 'Research Vessel'
  return null
}

function filterCargoTypes(raw: unknown): string[] {
  if (!Array.isArray(raw)) return []
  return raw.filter((c): c is string => typeof c === 'string' && CARGO_OPTIONS.includes(c))
}

function parseGrossTonnage(raw: unknown): string {
  const s = asString(raw).replace(/,/g, '').trim()
  if (!s) return ''
  const n = parseFloat(s)
  // Reject regulatory formats like "R-4"
  return Number.isFinite(n) && !/[a-z]/i.test(s) ? String(n) : ''
}

// ── Component ─────────────────────────────────────────────────────────────

function WelcomeContent() {
  const router = useRouter()
  const { addVessel, setActiveVessel } = useAuthStore()

  // Sprint D6.31 — Step 0 (persona + jurisdiction) is now the entry
  // point. Existing users who skipped Step 0 historically will see Step
  // 1 first as before; they can fill persona later via Account.
  const [step, setStep] = useState<Step>(0)
  const [path, setPath] = useState<Path>('unchosen')
  const [completed, setCompleted] = useState<CompletedSteps>({
    vessel: false, coi: false, credential: false,
  })
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  // Step 0 — persona + jurisdiction focus
  const [persona, setPersona] = useState<string>('')
  const [jurisdictionFocus, setJurisdictionFocus] = useState<string>('')
  const [personaSubmitting, setPersonaSubmitting] = useState(false)

  // Sprint B — pre-fill persona on mount so users coming from a
  // persona-targeted landing page (e.g. /education sets persona to
  // cadet_student during signup) see it already selected at step 0
  // and can just hit Continue.
  useEffect(() => {
    let cancelled = false
    apiRequest<{
      persona: string | null
      jurisdiction_focus: string | null
    }>('/onboarding/persona')
      .then((r) => {
        if (cancelled) return
        if (r.persona) setPersona(r.persona)
        if (r.jurisdiction_focus) setJurisdictionFocus(r.jurisdiction_focus)
      })
      .catch(() => {
        // Silent — fields stay empty, user picks at step 0.
      })
    return () => { cancelled = true }
  }, [])

  // ── Step 1 (COI upload) ─────────────────────────────────────────────
  const [coiPreview, setCoiPreview] = useState<PreviewExtraction | null>(null)
  const [coiRetryUsed, setCoiRetryUsed] = useState(false)
  const { phase: extractionPhase, start: startPhase, finish: finishPhase, reset: resetPhase } = useExtractionPhase()
  const fileInputRef = useRef<HTMLInputElement>(null)

  // ── Step 2 (unified vessel form) ────────────────────────────────────
  const [name, setName] = useState('')
  const [vesselType, setVesselType] = useState('Containership')
  const [grossTonnage, setGrossTonnage] = useState('')
  const [routeTypes, setRouteTypes] = useState<string[]>([])
  const [cargoTypes, setCargoTypes] = useState<string[]>([])
  const [subchapter, setSubchapter] = useState('')
  const [certType, setCertType] = useState('')
  const [manning, setManning] = useState('')
  const [routeLimitations, setRouteLimitations] = useState('')
  const [prefilled, setPrefilled] = useState<PrefilledSet>({})

  const [createdVesselId, setCreatedVesselId] = useState<string | null>(null)
  const [createdVesselName, setCreatedVesselName] = useState<string | null>(null)

  // ── Step 3 (credential) ─────────────────────────────────────────────
  const [credType, setCredType] = useState('mmc')
  const [credTitle, setCredTitle] = useState('')
  const [credExpiry, setCredExpiry] = useState('')
  const [credAddedTitle, setCredAddedTitle] = useState<string | null>(null)
  const [credScanning, setCredScanning] = useState(false)
  const credFileInputRef = useRef<HTMLInputElement>(null)

  function toggleRoute(r: string) {
    setRouteTypes((prev) => prev.includes(r) ? prev.filter((x) => x !== r) : [...prev, r])
  }
  function toggleCargo(c: string) {
    setCargoTypes((prev) => prev.includes(c) ? prev.filter((x) => x !== c) : [...prev, c])
  }

  // ── Step 1 actions ──────────────────────────────────────────────────

  async function uploadCoi(file: File) {
    setError(null)
    startPhase()
    try {
      const formData = new FormData()
      formData.append('file', file)
      const result = await apiUpload<PreviewExtraction>('/documents/extract-preview', formData)
      finishPhase(true)
      setCoiPreview(result)
      // Pre-fill Step 2 form from extraction
      applyExtractionToForm(result.extracted_data)
      // Advance to Step 2 review
      setPath('coi')
      setStep(2)
    } catch (e) {
      finishPhase(false)
      setError(e instanceof Error ? e.message : 'Could not read the document.')
    }
  }

  function applyExtractionToForm(data: Record<string, unknown>) {
    const next: PrefilledSet = {}

    const n = asString(data.vessel_name).trim()
    if (n) { setName(n); next.name = true }

    const vt = matchVesselType(data.vessel_type)
    if (vt) { setVesselType(vt); next.vesselType = true }

    const gt = parseGrossTonnage(data.gross_tonnage)
    if (gt) { setGrossTonnage(gt); next.grossTonnage = true }

    const rts = deriveRouteTypes(data.route)
    if (rts.length) { setRouteTypes(rts); next.routeTypes = true }

    const cargo = filterCargoTypes(data.cargo_types)
    if (cargo.length) { setCargoTypes(cargo); next.cargoTypes = true }

    const sub = asString(data.subchapter).trim().toUpperCase()
    if (sub && SUBCHAPTERS.includes(sub)) { setSubchapter(sub); next.subchapter = true }

    const manReq = asString(data.manning_requirement).trim()
    if (manReq) { setManning(manReq); next.manning = true }

    const rlim = asString(data.route_limitations).trim()
    if (rlim) { setRouteLimitations(rlim); next.routeLimitations = true }

    // Default cert type to "COI" when the user came through the COI path.
    setCertType('COI')
    next.certType = true

    setPrefilled(next)
  }

  function retryCoi() {
    setCoiRetryUsed(true)
    setError(null)
    resetPhase()
    fileInputRef.current?.click()
  }

  function fallbackToManual() {
    setPath('manual')
    setStep(2)
    setError(null)
    resetPhase()
  }

  function chooseManualFromStep1() {
    setPath('manual')
    setStep(2)
  }

  // ── Step 2 actions ──────────────────────────────────────────────────

  async function saveVesselAndContinue() {
    if (!name.trim()) { setError('Vessel name is required'); return }
    if (routeTypes.length === 0) { setError('Pick at least one route type'); return }
    setSubmitting(true)
    setError(null)
    try {
      const created = await apiRequest<{ id: string; name: string }>('/vessels', {
        method: 'POST',
        body: JSON.stringify({
          name: name.trim(),
          vessel_type: vesselType,
          gross_tonnage: grossTonnage ? parseFloat(grossTonnage) : null,
          route_types: routeTypes,
          cargo_types: cargoTypes,
          subchapter: subchapter || null,
          inspection_certificate_type: certType.trim() || null,
          manning_requirement: manning.trim() || null,
          route_limitations: routeLimitations.trim() || null,
        }),
      })
      addVessel({ id: created.id, name: created.name })
      setActiveVessel(created.id)
      setCreatedVesselId(created.id)
      setCreatedVesselName(created.name)

      // If the user came via COI path, attach the document as a snapshot.
      // apply_to_vessel=false because we just wrote the user-confirmed values.
      if (path === 'coi' && coiPreview) {
        try {
          await apiRequest(`/vessels/${created.id}/documents/from-preview`, {
            method: 'POST',
            body: JSON.stringify({
              preview_id: coiPreview.preview_id,
              document_type: 'coi',
              extracted_data: coiPreview.extracted_data,
              apply_to_vessel: false,
            }),
          })
          setCompleted((c) => ({ ...c, vessel: true, coi: true }))
        } catch {
          // Don't block wizard on attach failure; vessel is saved.
          setCompleted((c) => ({ ...c, vessel: true }))
        }
      } else {
        setCompleted((c) => ({ ...c, vessel: true }))
      }
      setStep(3)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save vessel')
    } finally {
      setSubmitting(false)
    }
  }

  function skipStep2() {
    // User doesn't want a vessel at all — skip straight to credential step.
    setStep(3)
  }

  // ── Step 3 actions ──────────────────────────────────────────────────

  async function scanCredentialPhoto(file: File) {
    setCredScanning(true)
    setError(null)
    try {
      const formData = new FormData()
      formData.append('file', file)
      const result = await apiUpload<{
        credential_type: string | null
        title: string | null
        issue_date: string | null
        expiry_date: string | null
      }>('/credentials/extract-from-photo', formData)
      if (result.credential_type) setCredType(result.credential_type)
      if (result.title) setCredTitle(result.title)
      if (result.expiry_date) setCredExpiry(result.expiry_date)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not extract — fill in manually')
    } finally {
      setCredScanning(false)
    }
  }

  async function saveCredential() {
    if (!credTitle.trim()) { setError('Credential title is required'); return }
    setSubmitting(true)
    setError(null)
    try {
      await apiRequest('/credentials', {
        method: 'POST',
        body: JSON.stringify({
          credential_type: credType,
          title: credTitle.trim(),
          expiry_date: credExpiry || null,
        }),
      })
      setCredAddedTitle(credTitle.trim())
      setCompleted((c) => ({ ...c, credential: true }))
      await finishOnboarding()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save credential')
      setSubmitting(false)
    }
  }

  async function skipCredential() { await finishOnboarding() }

  async function finishOnboarding() {
    setSubmitting(true)
    setError(null)
    try {
      const stepsCompleted: string[] = []
      if (completed.vessel) stepsCompleted.push('vessel')
      if (completed.coi) stepsCompleted.push('coi')
      if (completed.credential || credAddedTitle) stepsCompleted.push('credential')
      const skipped = stepsCompleted.length === 0

      await apiRequest('/onboarding/complete', {
        method: 'POST',
        body: JSON.stringify({ skipped, steps_completed: stepsCompleted }),
      })
      setStep(4)
    } catch (e) {
      console.error('Failed to record onboarding completion', e)
      setStep(4)
    } finally {
      setSubmitting(false)
    }
  }

  // Sprint D6.83 Phase A5 — students and teachers land on /study after
  // onboarding instead of /chat. Both personas registered for the exam-prep
  // angle, so dropping them at the chat input wastes the first impression.
  // Mariner / shore-side / legal personas keep the /chat default.
  const isStudyPersona = persona === 'cadet_student' || persona === 'teacher_instructor'
  const postOnboardingHref = isStudyPersona ? '/study' : '/'
  const postOnboardingLabel = isStudyPersona ? 'Open Study Tools' : 'Open Chat'

  function goToChat() { router.replace(postOnboardingHref) }

  // ── Step 0 actions (Sprint D6.31) ──────────────────────────────────

  /** Persist whatever the user picked for persona + jurisdiction_focus
   *  (either may be empty — backend treats null as "leave unchanged")
   *  and advance to Step 1. Failures are logged but don't block the
   *  flow — onboarding shouldn't dead-end on a soft profile field. */
  async function savePersonaAndContinue() {
    setPersonaSubmitting(true)
    setError(null)
    try {
      if (persona || jurisdictionFocus) {
        await apiRequest('/onboarding/persona', {
          method: 'POST',
          body: JSON.stringify({
            persona: persona || null,
            jurisdiction_focus: jurisdictionFocus || null,
          }),
        })
      }
      setStep(1)
    } catch (e) {
      console.error('Failed to save persona', e)
      // Don't block — let them proceed
      setStep(1)
    } finally {
      setPersonaSubmitting(false)
    }
  }

  function skipStep0() {
    setStep(1)
  }

  /** Helper so Step 1 can detect a non-mariner persona and mark vessel
   *  setup as optional. */
  const isNonMariner = persona !== '' && persona !== 'mariner_shipboard'

  // ── Render ──────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col min-h-dvh bg-[#0a0e1a]">
      {/* Header / progress */}
      <header className="flex-shrink-0 px-4 py-4 border-b border-white/8 bg-[#111827]/95">
        <div className="max-w-md mx-auto flex items-center justify-between">
          <div className="flex items-center gap-2">
            <svg className="w-5 h-5 text-[#2dd4bf]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <circle cx="12" cy="12" r="10" />
              <path d="M12 2v4M12 18v4M2 12h4M18 12h4" strokeLinecap="round" />
              <path d="M12 8l1.5 3.5L12 16l-1.5-4.5L12 8z" fill="currentColor" stroke="none" />
            </svg>
            <span className="font-display text-lg font-bold text-[#f0ece4]">RegKnot</span>
          </div>
          {step < 4 && (
            <div className="flex items-center gap-1.5">
              {/* Sprint D6.31 — Step 0 added; progression now 0..3.
                  Step 0 is intentionally subtle (no separate dot) so it
                  feels like a primer rather than a full wizard step. */}
              {[1, 2, 3].map((s) => (
                <span
                  key={s}
                  className={`w-2 h-2 rounded-full transition-colors ${
                    step === s ? 'bg-[#2dd4bf]' : step > s ? 'bg-[#2dd4bf]/40' : 'bg-white/15'
                  }`}
                />
              ))}
              <span className="font-mono text-[10px] text-[#6b7594] ml-2">
                {step === 0 ? 'Quick start' : `Step ${step} of 3`}
              </span>
            </div>
          )}
        </div>
      </header>

      <main className="flex-1 overflow-y-auto px-4 py-6">
        <div className="max-w-md mx-auto flex flex-col gap-5">

          {/* ── Step 0: Persona + jurisdiction (Sprint D6.31) ──────── */}
          {step === 0 && (
            <>
              <div className="flex flex-col gap-1">
                <h1 className="font-display text-2xl font-bold text-[#f0ece4]">A quick primer</h1>
                <p className="font-mono text-xs text-[#6b7594] leading-relaxed">
                  Two optional questions so RegKnot can scope answers to your role and primary
                  jurisdiction. Both can be skipped or changed later from your account.
                </p>
              </div>

              <section className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-4">
                <Field label="What's your role?">
                  <SelectInput
                    value={persona}
                    onChange={setPersona}
                    options={['Skip / pick later', ...PERSONA_OPTIONS.map((o) => o.label)]}
                    optionValues={['', ...PERSONA_OPTIONS.map((o) => o.value)]}
                  />
                </Field>

                <Field label="Primary jurisdiction (optional)">
                  <SelectInput
                    value={jurisdictionFocus}
                    onChange={setJurisdictionFocus}
                    options={['Skip', ...JURISDICTION_OPTIONS.map((o) => o.label)]}
                    optionValues={['', ...JURISDICTION_OPTIONS.map((o) => o.value)]}
                  />
                </Field>

                {error && <ErrorBox msg={error} />}

                <div className="flex items-center gap-3 mt-1">
                  <button
                    onClick={savePersonaAndContinue}
                    disabled={personaSubmitting}
                    className={primaryBtn}
                  >
                    {personaSubmitting ? 'Saving…' : 'Continue'}
                  </button>
                  <button onClick={skipStep0} className={ghostBtn}>
                    Skip
                  </button>
                </div>
              </section>
            </>
          )}

          {/* ── Step 1: Path chooser ───────────────────────────────── */}
          {step === 1 && (
            <>
              <div className="flex flex-col gap-1">
                <h1 className="font-display text-2xl font-bold text-[#f0ece4]">
                  {isNonMariner ? 'Set up a vessel? (optional)' : 'Welcome aboard'}
                </h1>
                <p className="font-mono text-xs text-[#6b7594] leading-relaxed">
                  {isNonMariner ? (
                    <>
                      Since you picked a non-shipboard role, you don&apos;t need a vessel profile —
                      RegKnot will scope answers to your jurisdiction. You can still add a vessel
                      now if you teach about a specific ship or want to test against one.
                    </>
                  ) : (
                    <>
                      Let&apos;s set up your vessel so RegKnot can give you compliance answers tailored to it.
                      This takes about 90 seconds.
                    </>
                  )}
                </p>
              </div>

              {extractionPhase !== 'idle' && !error ? (
                <section className="bg-[#111827] border border-[#2dd4bf]/30 rounded-xl p-5 flex flex-col gap-4">
                  <div className="w-8 h-8 border-2 border-[#2dd4bf] border-t-transparent rounded-full animate-spin mx-auto" />
                  <ExtractionProgress phase={extractionPhase} />
                </section>
              ) : (
                <section className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-4">
                  <div>
                    <p className="font-mono text-xs text-[#2dd4bf] uppercase tracking-wider mb-1">Do you have a COI?</p>
                    <p className="font-mono text-[11px] text-[#6b7594] leading-relaxed">
                      A Certificate of Inspection is the fastest way to set up — we&apos;ll auto-fill
                      vessel type, subchapter, manning, routes, and more.
                    </p>
                  </div>

                  <button
                    onClick={() => fileInputRef.current?.click()}
                    className="border-2 border-dashed border-[#2dd4bf]/40 hover:border-[#2dd4bf] bg-[#2dd4bf]/5 hover:bg-[#2dd4bf]/10
                      rounded-xl py-6 px-4 flex flex-col items-center gap-2 transition-colors"
                  >
                    <svg className="w-8 h-8 text-[#2dd4bf]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                      <polyline points="17 8 12 3 7 8" />
                      <line x1="12" y1="3" x2="12" y2="15" />
                    </svg>
                    <p className="font-mono text-sm font-bold text-[#2dd4bf]">Upload COI</p>
                    <p className="font-mono text-[10px] text-[#6b7594]">PDF, JPG, or PNG · max 10MB</p>
                  </button>

                  <input
                    ref={fileInputRef} type="file"
                    accept="image/jpeg,image/png,image/webp,application/pdf"
                    className="hidden"
                    onChange={(e) => {
                      const file = e.target.files?.[0]
                      if (file) uploadCoi(file)
                      e.target.value = ''
                    }}
                  />

                  <div className="flex items-center gap-3">
                    <div className="flex-1 h-px bg-white/8" />
                    <p className="font-mono text-[10px] text-[#6b7594] uppercase tracking-wider">or</p>
                    <div className="flex-1 h-px bg-white/8" />
                  </div>

                  <button
                    onClick={chooseManualFromStep1}
                    className="border border-white/10 hover:border-white/25 bg-[#0d1225] hover:bg-white/5
                      rounded-xl py-3 px-4 transition-colors"
                  >
                    <p className="font-mono text-sm text-[#f0ece4]">Enter vessel details manually</p>
                    <p className="font-mono text-[10px] text-[#6b7594] mt-0.5">Takes ~60 seconds</p>
                  </button>

                  {/* Sprint D6.31 — non-mariners (teachers, students,
                      shore-side, attorneys) can skip vessel setup
                      entirely. The persona + jurisdiction_focus they
                      picked at Step 0 already gives the prompt enough
                      to scope answers. */}
                  {isNonMariner && (
                    <>
                      <div className="flex items-center gap-3 mt-1">
                        <div className="flex-1 h-px bg-white/8" />
                        <p className="font-mono text-[10px] text-[#6b7594] uppercase tracking-wider">or</p>
                        <div className="flex-1 h-px bg-white/8" />
                      </div>
                      <button
                        onClick={() => { void finishOnboarding() }}
                        className="font-mono text-xs text-[#6b7594] hover:text-[#f0ece4] transition-colors py-2"
                      >
                        Skip vessel setup &mdash; I&apos;ll go straight to {isStudyPersona ? 'Study Tools' : 'chat'}
                      </button>
                    </>
                  )}
                </section>
              )}

              {error && (
                <>
                  <ErrorBox msg={error} />
                  <div className="flex items-center gap-3">
                    {!coiRetryUsed && (
                      <button onClick={retryCoi} className={primaryBtn}>Try Again</button>
                    )}
                    <button onClick={fallbackToManual} className={coiRetryUsed ? primaryBtn : ghostBtn}>
                      Enter manually instead
                    </button>
                  </div>
                </>
              )}
            </>
          )}

          {/* ── Step 2: Unified vessel form ────────────────────────── */}
          {step === 2 && (
            <>
              <div className="flex flex-col gap-1">
                <h1 className="font-display text-2xl font-bold text-[#f0ece4]">
                  {path === 'coi' ? 'Review your vessel' : 'Add your vessel'}
                </h1>
                <p className="font-mono text-xs text-[#6b7594] leading-relaxed">
                  {path === 'coi'
                    ? "We pulled these from your COI — edit anything that's off, then save."
                    : 'Fill in the basics. You can add a COI later from the vessel edit page.'}
                </p>
              </div>

              <section className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-4">
                <Field label="Vessel Name" required prefilled={prefilled.name}>
                  <input
                    type="text" value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="e.g. Maersk Tennessee"
                    className={inputClass}
                    autoFocus={!name}
                  />
                </Field>

                <Field label="Vessel Type" prefilled={prefilled.vesselType}>
                  <SelectInput value={vesselType} onChange={setVesselType} options={VESSEL_TYPES} />
                </Field>

                <Field label="Gross Tonnage (GT)" prefilled={prefilled.grossTonnage}>
                  <input
                    type="number" value={grossTonnage}
                    onChange={(e) => setGrossTonnage(e.target.value)}
                    placeholder="e.g. 50442"
                    className={inputClass}
                  />
                </Field>

                <Field label="Routes" required prefilled={prefilled.routeTypes}>
                  <div className="flex flex-col gap-2">
                    {ROUTE_OPTIONS.map((r) => (
                      <button
                        key={r.value}
                        onClick={() => toggleRoute(r.value)}
                        className={`text-left p-3 rounded-lg border transition-colors ${
                          routeTypes.includes(r.value)
                            ? 'border-[#2dd4bf]/50 bg-[#2dd4bf]/5'
                            : 'border-white/10 hover:border-white/20'
                        }`}
                      >
                        <p className={`font-mono text-sm ${routeTypes.includes(r.value) ? 'text-[#2dd4bf]' : 'text-[#f0ece4]'}`}>
                          {r.label}
                        </p>
                        <p className="font-mono text-[10px] text-[#6b7594] mt-0.5">{r.desc}</p>
                      </button>
                    ))}
                  </div>
                </Field>

                <Field label="Cargo Types" prefilled={prefilled.cargoTypes}>
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
                </Field>
              </section>

              {/* Compliance details — collapsible but always visible on COI path */}
              <section className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-4">
                <p className="font-mono text-xs text-[#2dd4bf] uppercase tracking-wider">
                  Compliance Details
                  <span className="normal-case tracking-normal ml-2 text-[#6b7594]/80">
                    (optional — improves PSC checklist)
                  </span>
                </p>

                <Field label="USCG Subchapter" prefilled={prefilled.subchapter}>
                  <SelectInput
                    value={subchapter}
                    onChange={setSubchapter}
                    options={['Not set', ...SUBCHAPTERS.map((s) => `Subchapter ${s}`)]}
                    optionValues={['', ...SUBCHAPTERS]}
                  />
                </Field>

                <Field label="Certificate Type" prefilled={prefilled.certType}>
                  <input
                    type="text" value={certType}
                    onChange={(e) => setCertType(e.target.value)}
                    placeholder="e.g. COI, SOLAS Safety, IOPP"
                    className={inputClass}
                  />
                </Field>

                <Field label="Manning Requirement" prefilled={prefilled.manning}>
                  <input
                    type="text" value={manning}
                    onChange={(e) => setManning(e.target.value)}
                    placeholder="e.g. 1 Master minimum"
                    className={inputClass}
                  />
                </Field>

                <Field label="Route Limitations" prefilled={prefilled.routeLimitations}>
                  <textarea
                    value={routeLimitations}
                    onChange={(e) => setRouteLimitations(e.target.value)}
                    rows={3}
                    placeholder="e.g. Limited to Table Rock Lake; no operation in winds > 35mph"
                    className={`${inputClass} resize-none`}
                  />
                </Field>
              </section>

              {error && <ErrorBox msg={error} />}

              <div className="flex items-center gap-3">
                <button
                  onClick={saveVesselAndContinue}
                  disabled={submitting}
                  className={primaryBtn}
                >
                  {submitting ? 'Saving…' : 'Save Vessel & Continue'}
                </button>
                <button onClick={skipStep2} disabled={submitting} className={ghostBtn}>
                  Skip
                </button>
              </div>
            </>
          )}

          {/* ── Step 3: Credential ─────────────────────────────────── */}
          {step === 3 && (
            <>
              <div className="flex flex-col gap-1">
                <h1 className="font-display text-2xl font-bold text-[#f0ece4]">Your credentials</h1>
                <p className="font-mono text-xs text-[#6b7594] leading-relaxed">
                  Track your MMC, STCW endorsements, medical certificate, or TWIC.
                  We&apos;ll remind you about expirations and use this context in chat.
                </p>
              </div>

              <section className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-4">
                <Field label="Type">
                  <SelectInput
                    value={credType}
                    onChange={setCredType}
                    options={CREDENTIAL_TYPES.map((c) => c.label)}
                    optionValues={CREDENTIAL_TYPES.map((c) => c.value)}
                  />
                </Field>

                <Field label="Title" required>
                  <input
                    type="text" value={credTitle}
                    onChange={(e) => setCredTitle(e.target.value)}
                    placeholder="e.g. Master 1600 GRT, STCW Basic Safety"
                    className={inputClass}
                  />
                </Field>

                <Field label="Expiry Date">
                  <input
                    type="date" value={credExpiry}
                    onChange={(e) => setCredExpiry(e.target.value)}
                    className={`${inputClass} [color-scheme:dark]`}
                  />
                </Field>

                <button
                  onClick={() => credFileInputRef.current?.click()}
                  disabled={credScanning}
                  className="font-mono text-xs text-[#2dd4bf] hover:bg-[#2dd4bf]/10
                    border border-dashed border-[#2dd4bf]/30 rounded-lg py-2.5
                    transition-colors disabled:opacity-50"
                >
                  {credScanning ? 'Scanning…' : '📷 Scan a photo instead'}
                </button>
                <input
                  ref={credFileInputRef} type="file"
                  accept="image/jpeg,image/png,image/webp,application/pdf"
                  className="hidden"
                  onChange={(e) => {
                    const file = e.target.files?.[0]
                    if (file) scanCredentialPhoto(file)
                    e.target.value = ''
                  }}
                />
              </section>

              {error && <ErrorBox msg={error} />}

              <div className="flex items-center gap-3">
                <button
                  onClick={saveCredential}
                  disabled={submitting}
                  className={primaryBtn}
                >
                  {submitting ? 'Saving…' : 'Add Credential & Finish'}
                </button>
                <button onClick={skipCredential} disabled={submitting} className={ghostBtn}>
                  Skip
                </button>
              </div>
            </>
          )}

          {/* ── Step 4: Success ─────────────────────────────────────── */}
          {step === 4 && (
            <>
              <div className="flex flex-col gap-2 text-center">
                <div className="mx-auto w-16 h-16 rounded-full bg-[#2dd4bf]/20 flex items-center justify-center mb-2">
                  <svg className="w-8 h-8 text-[#2dd4bf]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                </div>
                <h1 className="font-display text-2xl font-bold text-[#f0ece4]">You&apos;re all set</h1>
                <p className="font-mono text-xs text-[#6b7594]">
                  RegKnot is ready. Ask anything below.
                </p>
              </div>

              <section className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-2">
                <p className="font-mono text-xs text-[#6b7594] uppercase tracking-wider mb-1">Setup summary</p>
                <SummaryRow done={completed.vessel} label={completed.vessel ? `Vessel: ${createdVesselName}` : 'Vessel: skipped'} />
                <SummaryRow done={completed.coi} label={completed.coi ? 'COI uploaded & attached' : 'COI: skipped'} />
                <SummaryRow done={!!credAddedTitle} label={credAddedTitle ? `Credential: ${credAddedTitle}` : 'Credential: skipped'} />
              </section>

              {(completed.vessel || credAddedTitle) && (
                <ComingUpWidget visible={true} compact={false} />
              )}

              {/* Sprint D6.25 — feature-highlight cards (skippable). The "Open
                  Chat" button below remains the primary CTA; engaging with a
                  card is opt-in. We track which feature gets the first click
                  via the existing page-load referrer in Caddy logs. */}
              <FeatureHighlightCards />

              <button onClick={goToChat} className={primaryBtn}>
                {postOnboardingLabel}
              </button>

              <p className="font-mono text-[10px] text-[#6b7594]/60 text-center pb-6">
                Skipped a step? You can add anything from the menu later.
              </p>
            </>
          )}

        </div>
      </main>
    </div>
  )
}

// ── Form helpers ──────────────────────────────────────────────────────────

const inputClass = 'font-mono w-full bg-[#0d1225] border border-white/10 rounded-lg px-3 py-2 text-sm text-[#f0ece4] outline-none focus:border-[#2dd4bf] transition-colors'

const primaryBtn = 'flex-1 font-mono text-sm font-bold text-[#0a0e1a] bg-[#2dd4bf] hover:brightness-110 disabled:opacity-50 rounded-xl py-3 transition-[filter] duration-150'

const ghostBtn = 'font-mono text-sm text-[#6b7594] hover:text-[#f0ece4] px-4 py-3 transition-colors'

function Field({
  label, required, prefilled, children,
}: {
  label: string
  required?: boolean
  prefilled?: boolean
  children: React.ReactNode
}) {
  return (
    <div className="flex flex-col gap-1">
      <label className="font-mono text-xs text-[#6b7594] flex items-center gap-1.5">
        <span>{label}{required && <span className="text-amber-400 ml-1">*</span>}</span>
        {prefilled && (
          <span
            title="Pre-filled from your COI"
            className="inline-flex items-center justify-center w-3.5 h-3.5 rounded-full bg-[#2dd4bf]/20 text-[#2dd4bf]"
          >
            <svg className="w-2.5 h-2.5" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M2 6l3 3 5-5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </span>
        )}
      </label>
      {children}
    </div>
  )
}

function SelectInput({
  value, onChange, options, optionValues,
}: {
  value: string
  onChange: (v: string) => void
  options: string[]
  optionValues?: string[]
}) {
  return (
    <div className="relative">
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={`${inputClass} pr-10 appearance-none cursor-pointer`}
      >
        {options.map((o, i) => (
          <option key={o} value={optionValues ? optionValues[i] : o} style={{ backgroundColor: '#111827', color: '#f0ece4' }}>
            {o}
          </option>
        ))}
      </select>
      <svg className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#6b7594] pointer-events-none" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="6 9 12 15 18 9" />
      </svg>
    </div>
  )
}

function SummaryRow({ done, label }: { done: boolean; label: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className={`font-mono text-xs ${done ? 'text-[#2dd4bf]' : 'text-[#6b7594]/60'}`}>
        {done ? '✓' : '○'}
      </span>
      <span className={`font-mono text-xs ${done ? 'text-[#f0ece4]' : 'text-[#6b7594]/60'}`}>
        {label}
      </span>
    </div>
  )
}

function ErrorBox({ msg }: { msg: string }) {
  return (
    <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-3">
      <p className="font-mono text-xs text-red-400">{msg}</p>
    </div>
  )
}

// ── Feature highlight cards (Sprint D6.25) ────────────────────────────────
//
// Surfaces RegKnot features beyond chat that new users typically don't
// discover on their own. Per admin counts on 2026-04-30: Credentials Tracker
// (10), Compliance Log (1), PSC Checklist (1), Vessel Dossier (7) all
// chronically under-used. This is the lowest-friction nudge — sit right
// above the "Open Chat" CTA so engagement is opt-in.
//
// Tracking — we'll measure click-through via Caddy access logs filtered on
// `Referer: /welcome` for each card's destination route. No new instrumentation
// required.
function FeatureHighlightCards() {
  const cards = [
    {
      href: '/credentials',
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="5" width="18" height="14" rx="2" />
          <path d="M3 9h18" />
          <path d="M7 14h4" />
        </svg>
      ),
      title: 'Credentials Tracker',
      desc: 'Log MMC, STCW, medical, TWIC. Get expiry alerts before they bite.',
    },
    {
      href: '/log',
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
          <path d="M4 4h12a4 4 0 0 1 4 4v12H8a4 4 0 0 1-4-4V4z" />
          <path d="M8 9h8" />
          <path d="M8 13h6" />
        </svg>
      ),
      title: 'Compliance Log',
      desc: 'Document compliance checks for an audit trail you control.',
    },
    {
      href: '/psc-checklist',
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
          <rect x="5" y="3" width="14" height="18" rx="2" />
          <path d="M9 8l2 2 4-4" />
          <path d="M9 14h6" />
          <path d="M9 17h4" />
        </svg>
      ),
      title: 'PSC Checklist',
      desc: 'Walk through Port State Control prep before your next port call.',
    },
    {
      href: '/vessel-dossier',
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
          <path d="M3 17h18" />
          <path d="M5 17l1-7h12l1 7" />
          <path d="M9 10V6a3 3 0 1 1 6 0v4" />
        </svg>
      ),
      title: 'Vessel Dossier',
      desc: 'Build a one-page vessel profile in 60 seconds — share with auditors.',
    },
  ]
  return (
    <section className="flex flex-col gap-2">
      <p className="font-mono text-xs text-[#6b7594] uppercase tracking-wider">
        While you&apos;re here — try one of these
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {cards.map((c) => (
          <a
            key={c.href}
            href={c.href}
            className="group flex items-start gap-3 bg-[#111827] border border-white/8 rounded-xl p-3
              hover:border-[#2dd4bf]/40 hover:bg-[#152033] transition-colors"
          >
            <span className="flex-shrink-0 w-8 h-8 rounded-lg bg-[#2dd4bf]/10 text-[#2dd4bf]
              flex items-center justify-center group-hover:bg-[#2dd4bf]/20 transition-colors">
              <span className="block w-5 h-5">{c.icon}</span>
            </span>
            <div className="min-w-0 flex-1">
              <p className="font-display text-sm font-bold text-[#f0ece4] leading-tight">{c.title}</p>
              <p className="font-mono text-[11px] text-[#6b7594] leading-snug mt-0.5">{c.desc}</p>
            </div>
            <svg className="flex-shrink-0 w-4 h-4 text-[#6b7594] group-hover:text-[#2dd4bf] transition-colors mt-1"
              viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="9 18 15 12 9 6" />
            </svg>
          </a>
        ))}
      </div>
    </section>
  )
}

export default function WelcomePage() {
  return <AuthGuard><WelcomeContent /></AuthGuard>
}
