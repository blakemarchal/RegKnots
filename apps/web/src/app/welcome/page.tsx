'use client'

import { useState, useRef } from 'react'
import { useRouter } from 'next/navigation'
import AuthGuard from '@/components/AuthGuard'
import { apiRequest, apiUpload } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import { ComingUpWidget } from '@/components/ComingUpWidget'

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

const CREDENTIAL_TYPES = [
  { value: 'mmc', label: 'MMC' },
  { value: 'stcw', label: 'STCW Endorsement' },
  { value: 'medical', label: 'Medical Certificate' },
  { value: 'twic', label: 'TWIC' },
  { value: 'other', label: 'Other' },
]

type Step = 1 | 2 | 3 | 4  // 4 = success

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

// ── Component ─────────────────────────────────────────────────────────────

function WelcomeContent() {
  const router = useRouter()
  const { addVessel, setActiveVessel } = useAuthStore()

  const [step, setStep] = useState<Step>(1)
  const [completed, setCompleted] = useState<CompletedSteps>({
    vessel: false, coi: false, credential: false,
  })
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  // ── Step 1: Vessel ──────────────────────────────────────────────────
  const [vesselName, setVesselName] = useState('')
  const [vesselType, setVesselType] = useState('Containership')
  const [grossTonnage, setGrossTonnage] = useState('')
  const [routeTypes, setRouteTypes] = useState<string[]>([])
  const [createdVesselId, setCreatedVesselId] = useState<string | null>(null)
  const [createdVesselName, setCreatedVesselName] = useState<string | null>(null)

  // ── Step 2: COI upload ──────────────────────────────────────────────
  const [coiUploading, setCoiUploading] = useState(false)
  const [coiPreview, setCoiPreview] = useState<PreviewExtraction | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // ── Step 3: Credential ──────────────────────────────────────────────
  const [credType, setCredType] = useState('mmc')
  const [credTitle, setCredTitle] = useState('')
  const [credExpiry, setCredExpiry] = useState('')
  const [credAddedTitle, setCredAddedTitle] = useState<string | null>(null)
  const [credScanning, setCredScanning] = useState(false)
  const credFileInputRef = useRef<HTMLInputElement>(null)

  function toggleRoute(r: string) {
    setRouteTypes((prev) => prev.includes(r) ? prev.filter((x) => x !== r) : [...prev, r])
  }

  // ── Step 1 actions ──────────────────────────────────────────────────
  async function saveVessel() {
    if (!vesselName.trim()) { setError('Vessel name is required'); return }
    if (routeTypes.length === 0) { setError('Pick at least one route type'); return }
    setSubmitting(true)
    setError(null)
    try {
      const created = await apiRequest<{ id: string; name: string }>('/vessels', {
        method: 'POST',
        body: JSON.stringify({
          name: vesselName.trim(),
          vessel_type: vesselType,
          gross_tonnage: grossTonnage ? parseFloat(grossTonnage) : null,
          route_types: routeTypes,
          cargo_types: [],
        }),
      })
      addVessel({ id: created.id, name: created.name })
      setActiveVessel(created.id)
      setCreatedVesselId(created.id)
      setCreatedVesselName(created.name)
      setCompleted((c) => ({ ...c, vessel: true }))
      setStep(2)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save vessel')
    } finally {
      setSubmitting(false)
    }
  }

  function skipVessel() {
    // No vessel = skip COI step too (nothing to attach to)
    setStep(3)
  }

  // ── Step 2 actions ──────────────────────────────────────────────────
  async function uploadCoi(file: File) {
    setCoiUploading(true)
    setError(null)
    try {
      const formData = new FormData()
      formData.append('file', file)
      const result = await apiUpload<PreviewExtraction>('/documents/extract-preview', formData)
      setCoiPreview(result)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'COI extraction failed — you can skip and add later')
    } finally {
      setCoiUploading(false)
    }
  }

  async function attachCoi() {
    if (!createdVesselId || !coiPreview) return
    setSubmitting(true)
    setError(null)
    try {
      await apiRequest(`/vessels/${createdVesselId}/documents/from-preview`, {
        method: 'POST',
        body: JSON.stringify({
          preview_id: coiPreview.preview_id,
          document_type: 'coi',
          extracted_data: coiPreview.extracted_data,
        }),
      })
      setCompleted((c) => ({ ...c, coi: true }))
      setStep(3)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to attach COI')
    } finally {
      setSubmitting(false)
    }
  }

  function skipCoi() { setStep(3) }

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

  async function skipCredential() {
    await finishOnboarding()
  }

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
      // Don't block the user on a flag-write failure
      console.error('Failed to record onboarding completion', e)
      setStep(4)
    } finally {
      setSubmitting(false)
    }
  }

  function goToChat() { router.replace('/') }

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
              {[1, 2, 3].map((s) => (
                <span
                  key={s}
                  className={`w-2 h-2 rounded-full transition-colors ${
                    step === s ? 'bg-[#2dd4bf]' : step > s ? 'bg-[#2dd4bf]/40' : 'bg-white/15'
                  }`}
                />
              ))}
              <span className="font-mono text-[10px] text-[#6b7594] ml-2">Step {step} of 3</span>
            </div>
          )}
        </div>
      </header>

      <main className="flex-1 overflow-y-auto px-4 py-6">
        <div className="max-w-md mx-auto flex flex-col gap-5">

          {/* ── Step 1: Vessel ──────────────────────────────────────── */}
          {step === 1 && (
            <>
              <div className="flex flex-col gap-1">
                <h1 className="font-display text-2xl font-bold text-[#f0ece4]">Welcome aboard</h1>
                <p className="font-mono text-xs text-[#6b7594] leading-relaxed">
                  Let&apos;s set you up so RegKnot can give you vessel-specific compliance answers.
                  This takes about 90 seconds.
                </p>
              </div>

              <section className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-4">
                <p className="font-mono text-xs text-[#2dd4bf] uppercase tracking-wider">Add a vessel</p>

                <Field label="Vessel Name" required>
                  <input
                    type="text" value={vesselName}
                    onChange={(e) => setVesselName(e.target.value)}
                    placeholder="e.g. Maersk Tennessee"
                    className={inputClass}
                    autoFocus
                  />
                </Field>

                <Field label="Vessel Type">
                  <SelectInput value={vesselType} onChange={setVesselType} options={VESSEL_TYPES} />
                </Field>

                <Field label="Gross Tonnage (GT)">
                  <input
                    type="number" value={grossTonnage}
                    onChange={(e) => setGrossTonnage(e.target.value)}
                    placeholder="e.g. 50442"
                    className={inputClass}
                  />
                </Field>

                <Field label="Routes" required>
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
              </section>

              {error && <ErrorBox msg={error} />}

              <div className="flex items-center gap-3">
                <button
                  onClick={saveVessel}
                  disabled={submitting}
                  className={primaryBtn}
                >
                  {submitting ? 'Saving…' : 'Save Vessel & Continue'}
                </button>
                <button onClick={skipVessel} className={ghostBtn}>
                  Skip
                </button>
              </div>
            </>
          )}

          {/* ── Step 2: COI Upload ─────────────────────────────────── */}
          {step === 2 && createdVesselId && (
            <>
              <div className="flex flex-col gap-1">
                <h1 className="font-display text-2xl font-bold text-[#f0ece4]">Got a COI?</h1>
                <p className="font-mono text-xs text-[#6b7594] leading-relaxed">
                  Upload your Certificate of Inspection and we&apos;ll auto-populate
                  subchapter, manning requirements, equipment, and route limitations
                  for {createdVesselName}.
                </p>
              </div>

              <section className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-4">
                {!coiPreview ? (
                  <>
                    <button
                      onClick={() => fileInputRef.current?.click()}
                      disabled={coiUploading}
                      className="border-2 border-dashed border-white/15 hover:border-[#2dd4bf]/40
                        rounded-xl py-8 px-4 flex flex-col items-center gap-2
                        transition-colors disabled:opacity-50"
                    >
                      {coiUploading ? (
                        <>
                          <div className="w-8 h-8 border-2 border-[#2dd4bf] border-t-transparent rounded-full animate-spin" />
                          <p className="font-mono text-xs text-[#2dd4bf]">Extracting COI…</p>
                          <p className="font-mono text-[10px] text-[#6b7594]">This takes 10-20 seconds</p>
                        </>
                      ) : (
                        <>
                          <svg className="w-10 h-10 text-[#6b7594]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                            <polyline points="17 8 12 3 7 8" />
                            <line x1="12" y1="3" x2="12" y2="15" />
                          </svg>
                          <p className="font-mono text-sm text-[#f0ece4]">Tap to upload COI</p>
                          <p className="font-mono text-[10px] text-[#6b7594]">PDF, JPG, or PNG · max 10MB</p>
                        </>
                      )}
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
                  </>
                ) : (
                  <div className="flex flex-col gap-3">
                    <p className="font-mono text-xs text-[#2dd4bf]">✓ Extracted from {coiPreview.filename}</p>
                    <div className="bg-[#0d1225] border border-white/10 rounded-lg p-3 max-h-48 overflow-y-auto">
                      <div className="flex flex-col gap-1.5 font-mono text-[11px]">
                        {Object.entries(coiPreview.extracted_data)
                          .filter(([_, v]) => v && String(v).toLowerCase() !== 'null')
                          .slice(0, 10)
                          .map(([k, v]) => (
                            <div key={k} className="flex items-baseline gap-2">
                              <span className="text-[#6b7594] shrink-0">{k.replace(/_/g, ' ')}:</span>
                              <span className="text-[#f0ece4] truncate">{String(v)}</span>
                            </div>
                          ))}
                      </div>
                    </div>
                    <button onClick={() => setCoiPreview(null)} className="font-mono text-[10px] text-[#6b7594] hover:text-[#f0ece4] self-start">
                      Try a different file
                    </button>
                  </div>
                )}
              </section>

              {error && <ErrorBox msg={error} />}

              <div className="flex items-center gap-3">
                <button
                  onClick={coiPreview ? attachCoi : skipCoi}
                  disabled={submitting || coiUploading}
                  className={primaryBtn}
                >
                  {submitting ? 'Saving…' : coiPreview ? 'Apply to Vessel & Continue' : 'Continue'}
                </button>
                {!coiPreview && (
                  <button onClick={skipCoi} className={ghostBtn}>
                    Skip
                  </button>
                )}
              </div>
            </>
          )}

          {/* ── Step 3: Credential ──────────────────────────────────── */}
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
                <SummaryRow done={completed.coi} label={completed.coi ? 'COI uploaded & extracted' : 'COI: skipped'} />
                <SummaryRow done={!!credAddedTitle} label={credAddedTitle ? `Credential: ${credAddedTitle}` : 'Credential: skipped'} />
              </section>

              {/* Show Coming Up if anything was set up */}
              {(completed.vessel || credAddedTitle) && (
                <ComingUpWidget visible={true} compact={false} />
              )}

              <button onClick={goToChat} className={primaryBtn}>
                Open Chat
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

function Field({ label, required, children }: { label: string; required?: boolean; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <label className="font-mono text-xs text-[#6b7594]">
        {label}{required && <span className="text-amber-400 ml-1">*</span>}
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

export default function WelcomePage() {
  return <AuthGuard><WelcomeContent /></AuthGuard>
}
