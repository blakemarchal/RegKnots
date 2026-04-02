'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { apiRequest } from '@/lib/api'
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
    emoji: '🏠',
    label: 'Inland',
    desc: 'Rivers, lakes, and protected waters',
  },
  {
    value: 'coastal',
    emoji: '🌊',
    label: 'Coastal',
    desc: 'Near-shore and coastal routes',
  },
  {
    value: 'international',
    emoji: '🌐',
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
  route_type: string
  cargo_types: string[]
}

interface VesselResponse {
  id: string
  name: string
  vessel_type: string
  gross_tonnage: number | null
  route_type: string
  cargo_types: string[]
}

const EMPTY_FORM: VesselForm = {
  name: '',
  imo_mmsi: '',
  vessel_type: '',
  gross_tonnage: '',
  route_type: '',
  cargo_types: [],
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
  const { addVessel, setActiveVessel } = useAuthStore()

  const [step, setStep] = useState(1)
  const [direction, setDirection] = useState<'forward' | 'back'>('forward')
  const [form, setForm] = useState<VesselForm>(EMPTY_FORM)
  const [errors, setErrors] = useState<Partial<Record<keyof VesselForm, string>>>({})
  const [completedVessels, setCompletedVessels] = useState<VesselForm[]>([])
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  // ── Helpers ──────────────────────────────────────────────────────────────────

  function patch(key: keyof VesselForm, value: string | string[]) {
    setForm((f) => ({ ...f, [key]: value }))
    if (errors[key]) setErrors((e) => ({ ...e, [key]: undefined }))
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
    if (s === 3 && !form.route_type) e.route_type = 'Please select a route type'
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
    setStep((s) => s - 1)
  }

  function jumpToStep(n: number) {
    setErrors({})
    setDirection(n < step ? 'back' : 'forward')
    setStep(n)
  }

  function addAnotherVessel() {
    setCompletedVessels((prev) => [...prev, form])
    setForm(EMPTY_FORM)
    setErrors({})
    setDirection('forward')
    setStep(1)
  }

  async function handleSetSail() {
    setIsSubmitting(true)
    setSubmitError(null)

    const allForms = [...completedVessels, form]
    const created: { id: string; name: string }[] = []

    try {
      for (const v of allForms) {
        const result = await apiRequest<VesselResponse>('/vessels', {
          method: 'POST',
          body: JSON.stringify({
            name: v.name.trim(),
            imo_mmsi: v.imo_mmsi.trim() || null,
            vessel_type: v.vessel_type,
            gross_tonnage: v.gross_tonnage ? parseFloat(v.gross_tonnage) : null,
            route_type: v.route_type,
            cargo_types: v.cargo_types,
          }),
        })
        created.push({ id: result.id, name: result.name })
      }

      for (const v of created) {
        addVessel(v)
      }
      setActiveVessel(created[0].id)
      router.replace('/')
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
      if (step < 5) advance()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [step, form]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Route label helper ─────────────────────────────────────────────────────

  function routeLabel(v: string) {
    return ROUTE_OPTIONS.find((r) => r.value === v)?.label ?? v
  }

  // ── Step renderers ────────────────────────────────────────────────────────────

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
        {ROUTE_OPTIONS.map((r) => (
          <button
            key={r.value}
            type="button"
            onClick={() => patch('route_type', r.value)}
            className={`w-full p-4 rounded-xl border text-left transition-all duration-150 ${
              form.route_type === r.value
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
              {form.route_type === r.value && (
                <div className="ml-auto w-4 h-4 rounded-full bg-[--color-teal] flex items-center justify-center">
                  <svg viewBox="0 0 12 12" className="w-2.5 h-2.5" fill="none" stroke="#0a0e1a" strokeWidth="2">
                    <path d="M2 6l3 3 5-5" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </div>
              )}
            </div>
          </button>
        ))}
        {errors.route_type && (
          <HelperText variant="error">{errors.route_type}</HelperText>
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
          <ReviewRow label="Route" value={routeLabel(form.route_type)} onEdit={() => jumpToStep(3)} />
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
          {isSubmitting ? 'Saving vessels…' : 'Set Sail'}
        </button>
      </div>
    )
  }

  // ── Layout ────────────────────────────────────────────────────────────────────

  const stepContent = [renderStep1, renderStep2, renderStep3, renderStep4, renderStep5][step - 1]

  return (
    <main className="min-h-screen bg-[--color-navy] flex flex-col">
      {/* Header */}
      <header className="flex-shrink-0 px-5 pt-8 pb-5 bg-[--color-charcoal]/60 border-b border-white/8">
        <div className="max-w-sm mx-auto">
          <ProgressBar step={step} />
        </div>
      </header>

      {/* Scrollable step area */}
      <div className="flex-1 overflow-y-auto">
        <div
          key={step}
          className={`max-w-sm mx-auto px-5 py-7 animate-[${
            direction === 'forward' ? 'stepInRight' : 'stepInLeft'
          }_0.28s_ease-out]`}
        >
          {stepContent()}
        </div>
      </div>

      {/* Navigation footer */}
      <footer className="flex-shrink-0 bg-[--color-charcoal]/60 border-t border-white/8 px-5 py-4">
        <div className="max-w-sm mx-auto flex items-center justify-between gap-3">
          {step > 1 ? (
            <button
              type="button"
              onClick={goBack}
              disabled={isSubmitting}
              className="font-mono text-sm text-[--color-muted] hover:text-[#f0ece4] transition-[color] duration-150 disabled:opacity-50"
            >
              ← Back
            </button>
          ) : (
            <div />
          )}

          {step < 5 && (
            <button
              type="button"
              onClick={advance}
              className="font-mono bg-[--color-teal] hover:brightness-110 text-[--color-navy] font-bold text-sm uppercase tracking-wider rounded-lg px-6 py-2.5 transition-[filter] duration-150"
            >
              {step === 4 ? 'Review' : 'Continue →'}
            </button>
          )}
        </div>
      </footer>
    </main>
  )
}
