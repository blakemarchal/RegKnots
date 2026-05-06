'use client'

import { useEffect, useState, useCallback } from 'react'
import Link from 'next/link'
import AuthGuard from '@/components/AuthGuard'
import { AppHeader } from '@/components/AppHeader'
import { EmailComposeButton } from '@/components/EmailComposeButton'
import { apiRequest } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'

// ── Types ─────────────────────────────────────────────────────────────────

interface PrefillVessel {
  id: string
  vessel_name: string
  official_number: string | null
  gross_tonnage: number | null
  vessel_type: string | null
  route_type: string | null
}

interface PrefillSeaTimeEntry {
  id: string
  vessel_id: string | null
  vessel_name: string
  official_number: string | null
  gross_tonnage: number | null
  vessel_type: string | null
  route_type: string | null
  horsepower: string | null
  propulsion: string | null
  capacity_served: string
  from_date: string
  to_date: string
  days_on_board: number
}

interface PrefillResponse {
  applicant_full_name: string
  applicant_mmc_number: string | null
  suggested_role: string | null
  vessels: PrefillVessel[]
  sea_time_entries?: PrefillSeaTimeEntry[]
}

interface VesselEntry {
  vessel_id: string | null  // null when typed in manually
  vessel_name: string
  official_number: string
  gross_tonnage: string  // string for form input; converted to number on submit
  vessel_type: string
  route_type: string
  horsepower: string
  propulsion: string
  capacity_served: string
  from_date: string
  to_date: string
  days_on_board: string
}

const SESSION_KEY = 'regknot:sea_service_letter:draft'

const ROUTE_OPTIONS = ['Oceans', 'Near-Coastal / Coastal', 'Inland', 'Great Lakes']
const PROPULSION_OPTIONS = ['Diesel', 'Steam', 'Gas Turbine', 'Electric', 'Hybrid', 'Other']
const CAPACITY_HINTS = [
  'Master', 'Chief Mate', 'Second Mate', 'Third Mate',
  'Chief Engineer', 'First Assistant Engineer', 'Second Assistant Engineer',
  'Third Assistant Engineer', 'Able Seaman', 'Ordinary Seaman',
  'OUPV', 'Mate', 'Pilot',
]

function emptyEntry(suggestedCapacity?: string | null): VesselEntry {
  return {
    vessel_id: null,
    vessel_name: '',
    official_number: '',
    gross_tonnage: '',
    vessel_type: '',
    route_type: '',
    horsepower: '',
    propulsion: '',
    capacity_served: suggestedCapacity || '',
    from_date: '',
    to_date: '',
    days_on_board: '',
  }
}

function calculateDays(from: string, to: string): number {
  if (!from || !to) return 0
  const f = new Date(from).getTime()
  const t = new Date(to).getTime()
  if (isNaN(f) || isNaN(t) || t < f) return 0
  return Math.floor((t - f) / (1000 * 60 * 60 * 24)) + 1
}

// ── Component ─────────────────────────────────────────────────────────────

function SeaServiceLetterContent() {
  const { vessels: storeVessels } = useAuthStore()

  const [prefillLoading, setPrefillLoading] = useState(true)
  const [prefill, setPrefill] = useState<PrefillResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [generating, setGenerating] = useState(false)
  const [success, setSuccess] = useState(false)

  // Applicant
  const [applicantName, setApplicantName] = useState('')
  const [applicantAddress, setApplicantAddress] = useState('')
  const [mmcNumber, setMmcNumber] = useState('')
  const [targetEndorsement, setTargetEndorsement] = useState('')

  // Company
  const [companyName, setCompanyName] = useState('')
  const [companyAddress, setCompanyAddress] = useState('')
  const [companyPhone, setCompanyPhone] = useState('')
  const [companyOfficialName, setCompanyOfficialName] = useState('')
  const [companyOfficialTitle, setCompanyOfficialTitle] = useState('')

  // Vessel entries
  const [entries, setEntries] = useState<VesselEntry[]>([emptyEntry()])

  // Remarks
  const [remarks, setRemarks] = useState('')

  // Load pre-fill on mount, then restore any saved draft
  useEffect(() => {
    apiRequest<PrefillResponse>('/credentials/sea-service-letter/prefill')
      .then((p) => {
        setPrefill(p)
        // Try to restore saved draft first
        let restored = false
        try {
          const raw = window.sessionStorage.getItem(SESSION_KEY)
          if (raw) {
            const draft = JSON.parse(raw)
            if (draft.applicantName) setApplicantName(draft.applicantName)
            if (draft.applicantAddress) setApplicantAddress(draft.applicantAddress)
            if (draft.mmcNumber) setMmcNumber(draft.mmcNumber)
            if (draft.targetEndorsement) setTargetEndorsement(draft.targetEndorsement)
            if (draft.companyName) setCompanyName(draft.companyName)
            if (draft.companyAddress) setCompanyAddress(draft.companyAddress)
            if (draft.companyPhone) setCompanyPhone(draft.companyPhone)
            if (draft.companyOfficialName) setCompanyOfficialName(draft.companyOfficialName)
            if (draft.companyOfficialTitle) setCompanyOfficialTitle(draft.companyOfficialTitle)
            if (draft.entries && Array.isArray(draft.entries) && draft.entries.length > 0) {
              setEntries(draft.entries)
            }
            if (draft.remarks) setRemarks(draft.remarks)
            restored = true
          }
        } catch { /* noop */ }

        if (!restored) {
          // Pre-fill from API response
          setApplicantName(p.applicant_full_name)
          if (p.applicant_mmc_number) setMmcNumber(p.applicant_mmc_number)
          setEntries([emptyEntry(p.suggested_role)])
        }
      })
      .catch(() => setError('Failed to load pre-fill data'))
      .finally(() => setPrefillLoading(false))
  }, [])

  // Save draft to sessionStorage on every change
  useEffect(() => {
    try {
      window.sessionStorage.setItem(SESSION_KEY, JSON.stringify({
        applicantName, applicantAddress, mmcNumber, targetEndorsement,
        companyName, companyAddress, companyPhone,
        companyOfficialName, companyOfficialTitle,
        entries, remarks,
      }))
    } catch { /* noop */ }
  }, [
    applicantName, applicantAddress, mmcNumber, targetEndorsement,
    companyName, companyAddress, companyPhone,
    companyOfficialName, companyOfficialTitle,
    entries, remarks,
  ])

  const updateEntry = useCallback((idx: number, patch: Partial<VesselEntry>) => {
    setEntries((prev) => prev.map((e, i) => (i === idx ? { ...e, ...patch } : e)))
  }, [])

  function addEntry() {
    setEntries((prev) => [...prev, emptyEntry(prefill?.suggested_role)])
  }

  function removeEntry(idx: number) {
    setEntries((prev) => prev.length > 1 ? prev.filter((_, i) => i !== idx) : prev)
  }

  function preFillFromVessel(idx: number, vesselId: string) {
    const v = prefill?.vessels.find((x) => x.id === vesselId)
    if (!v) return
    updateEntry(idx, {
      vessel_id: v.id,
      vessel_name: v.vessel_name,
      official_number: v.official_number ?? '',
      gross_tonnage: v.gross_tonnage ? String(v.gross_tonnage) : '',
      vessel_type: v.vessel_type ?? '',
      route_type: v.route_type ?? '',
    })
  }

  // D6.62 — drop a logged sea-time entry directly into the form. Adds
  // it as a new VesselEntry row (replacing the row if it's the empty
  // bootstrap; appending otherwise). Already-included entries are
  // tracked so the UI can hide them from the picker.
  const includedSeaTimeIds = new Set(
    entries.map((e) => (e as VesselEntry & { _sourceSeaTimeId?: string })._sourceSeaTimeId).filter(Boolean) as string[],
  )
  function includeSeaTimeEntry(s: PrefillSeaTimeEntry) {
    const newRow: VesselEntry = {
      vessel_id: s.vessel_id,
      vessel_name: s.vessel_name,
      official_number: s.official_number ?? '',
      gross_tonnage: s.gross_tonnage !== null ? String(s.gross_tonnage) : '',
      vessel_type: s.vessel_type ?? '',
      route_type: s.route_type ?? '',
      horsepower: s.horsepower ?? '',
      propulsion: s.propulsion ?? '',
      capacity_served: s.capacity_served,
      from_date: s.from_date,
      to_date: s.to_date,
      days_on_board: String(s.days_on_board),
    }
    // Tag with source id so we don't double-include and can hide from picker
    ;(newRow as VesselEntry & { _sourceSeaTimeId?: string })._sourceSeaTimeId = s.id

    setEntries((prev) => {
      // If only the empty bootstrap row exists, replace it. Otherwise append.
      if (prev.length === 1 && !prev[0].vessel_name && !prev[0].from_date) {
        return [newRow]
      }
      return [...prev, newRow]
    })
  }

  function clearForm() {
    if (!confirm('Clear the entire form? This cannot be undone.')) return
    try { window.sessionStorage.removeItem(SESSION_KEY) } catch { /* noop */ }
    setApplicantName(prefill?.applicant_full_name ?? '')
    setApplicantAddress('')
    setMmcNumber(prefill?.applicant_mmc_number ?? '')
    setTargetEndorsement('')
    setCompanyName('')
    setCompanyAddress('')
    setCompanyPhone('')
    setCompanyOfficialName('')
    setCompanyOfficialTitle('')
    setEntries([emptyEntry(prefill?.suggested_role)])
    setRemarks('')
  }

  async function handleGenerate() {
    setError(null)
    setSuccess(false)

    // Basic validation
    if (!applicantName.trim()) { setError('Applicant name is required'); return }
    if (!companyName.trim()) { setError('Company name is required'); return }
    if (!companyOfficialName.trim()) { setError("Company official's name is required"); return }
    if (!companyOfficialTitle.trim()) { setError("Company official's title is required"); return }

    for (let i = 0; i < entries.length; i++) {
      const e = entries[i]
      if (!e.vessel_name.trim()) { setError(`Vessel ${i + 1}: name is required`); return }
      if (!e.capacity_served.trim()) { setError(`Vessel ${i + 1}: capacity served is required`); return }
      if (!e.from_date) { setError(`Vessel ${i + 1}: from date is required`); return }
      if (!e.to_date) { setError(`Vessel ${i + 1}: to date is required`); return }
      if (new Date(e.from_date) > new Date(e.to_date)) {
        setError(`Vessel ${i + 1}: from date must be before to date`); return
      }
      const days = parseInt(e.days_on_board || '0', 10)
      if (isNaN(days) || days < 0) { setError(`Vessel ${i + 1}: days on board must be a positive number`); return }
    }

    setGenerating(true)

    const payload = {
      applicant_full_name: applicantName.trim(),
      applicant_address: applicantAddress.trim() || null,
      applicant_mariner_reference_number: mmcNumber.trim() || null,
      target_endorsement: targetEndorsement.trim() || null,
      company_name: companyName.trim(),
      company_address: companyAddress.trim() || null,
      company_phone: companyPhone.trim() || null,
      company_official_name: companyOfficialName.trim(),
      company_official_title: companyOfficialTitle.trim(),
      vessel_entries: entries.map((e) => ({
        vessel_id: e.vessel_id,
        vessel_name: e.vessel_name.trim(),
        official_number: e.official_number.trim() || null,
        gross_tonnage: e.gross_tonnage ? parseFloat(e.gross_tonnage) : null,
        vessel_type: e.vessel_type.trim() || null,
        route_type: e.route_type.trim() || null,
        horsepower: e.horsepower.trim() || null,
        propulsion: e.propulsion.trim() || null,
        capacity_served: e.capacity_served.trim(),
        from_date: e.from_date,
        to_date: e.to_date,
        days_on_board: parseInt(e.days_on_board || '0', 10),
      })),
      remarks: remarks.trim() || null,
    }

    try {
      const { useAuthStore } = await import('@/lib/auth')
      const token = useAuthStore.getState().accessToken
      const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

      // D6.62 hotfix — pass IANA tz so the letter's dateline matches
      // the user's local wall clock instead of UTC midnight.
      let tz = ''
      try {
        tz = Intl.DateTimeFormat().resolvedOptions().timeZone || ''
      } catch { /* fallthrough to UTC */ }
      const fetchUrl = tz
        ? `${API_URL}/credentials/sea-service-letter?tz=${encodeURIComponent(tz)}`
        : `${API_URL}/credentials/sea-service-letter`
      const resp = await fetch(fetchUrl, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(payload),
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
      const safeName = applicantName.trim().replace(/\s+/g, '_').replace(/[/\\]/g, '-')
      a.href = url
      a.download = `sea_service_letter_${safeName}.pdf`
      a.click()
      URL.revokeObjectURL(url)
      setSuccess(true)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to generate letter')
    } finally {
      setGenerating(false)
    }
  }

  const totalDays = entries.reduce((sum, e) => sum + (parseInt(e.days_on_board || '0', 10) || 0), 0)

  return (
    <div className="flex flex-col h-dvh bg-[#0a0e1a]">
      <AppHeader title="Sea Service Letter" />

      <main className="flex-1 overflow-y-auto px-4 py-6">
        <div className="max-w-lg mx-auto flex flex-col gap-5">

          {/* Intro */}
          <section className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-3">
            <p className="font-mono text-xs text-[#6b7594] uppercase tracking-wider">
              Sea Service Letter
            </p>
            <p className="font-mono text-xs text-[#f0ece4]/60 leading-relaxed">
              Generate a USCG-formatted Sea Service Letter for credential applications.
              Fill in the details, download as PDF, and email to your employer to sign.
              Form data is auto-saved to this session.
            </p>
            {storeVessels.length === 0 && (
              <p className="font-mono text-[10px] text-amber-400">
                Tip: add vessels in My Vessels to auto-fill vessel details below.
              </p>
            )}
          </section>

          {prefillLoading && (
            <div className="flex flex-col gap-3">
              {[1, 2, 3].map((i) => (
                <div key={i} className="h-32 bg-[#111827] border border-white/8 rounded-xl animate-pulse" />
              ))}
            </div>
          )}

          {!prefillLoading && (
            <>
              {/* Applicant */}
              <section className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-3">
                <p className="font-mono text-xs text-[#2dd4bf] uppercase tracking-wider">Applicant</p>

                <Field label="Full Name" required>
                  <input type="text" value={applicantName} onChange={(e) => setApplicantName(e.target.value)} className={inputClass} />
                </Field>

                <Field label="Mariner Reference Number (MMC #)">
                  <input type="text" value={mmcNumber} onChange={(e) => setMmcNumber(e.target.value)} placeholder="e.g. 1234567" className={inputClass} />
                </Field>

                <Field label="Target Endorsement / Application">
                  <input type="text" value={targetEndorsement} onChange={(e) => setTargetEndorsement(e.target.value)} placeholder="e.g. Master 1600 GRT, Oceans" className={inputClass} />
                </Field>

                <Field label="Address (optional)">
                  <textarea value={applicantAddress} onChange={(e) => setApplicantAddress(e.target.value)} rows={2} className={inputClass} />
                </Field>
              </section>

              {/* Company */}
              <section className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-3">
                <p className="font-mono text-xs text-[#2dd4bf] uppercase tracking-wider">Company / Employer</p>

                <Field label="Company Name" required>
                  <input type="text" value={companyName} onChange={(e) => setCompanyName(e.target.value)} className={inputClass} />
                </Field>

                <Field label="Address">
                  <textarea value={companyAddress} onChange={(e) => setCompanyAddress(e.target.value)} rows={2} className={inputClass} />
                </Field>

                <Field label="Phone">
                  <input type="text" value={companyPhone} onChange={(e) => setCompanyPhone(e.target.value)} className={inputClass} />
                </Field>

                <Field label="Authorized Signer's Name" required>
                  <input type="text" value={companyOfficialName} onChange={(e) => setCompanyOfficialName(e.target.value)} className={inputClass} />
                </Field>

                <Field label="Signer's Title" required>
                  <input type="text" value={companyOfficialTitle} onChange={(e) => setCompanyOfficialTitle(e.target.value)} placeholder="e.g. Operations Manager, HR Director" className={inputClass} />
                </Field>
              </section>

              {/* D6.62 — Sea-time log picker. Lets the user drop logged
                  blocks directly into the form instead of retyping. */}
              {prefill?.sea_time_entries && prefill.sea_time_entries.length > 0 && (
                <section className="bg-[#0d1225] border border-[#2dd4bf]/20 rounded-xl p-4 flex flex-col gap-3">
                  <div className="flex items-center justify-between gap-2 flex-wrap">
                    <p className="font-mono text-xs text-[#2dd4bf] uppercase tracking-wider">
                      Pull from your sea-time log
                    </p>
                    <Link
                      href="/sea-time"
                      className="font-mono text-[10px] text-[#2dd4bf]/80 hover:underline"
                    >
                      Open log →
                    </Link>
                  </div>
                  <p className="font-mono text-[11px] text-[#6b7594]">
                    Tap an entry to drop it into the form below.
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {prefill.sea_time_entries
                      .filter((s) => !includedSeaTimeIds.has(s.id))
                      .slice(0, 12)
                      .map((s) => (
                        <button
                          key={s.id}
                          type="button"
                          onClick={() => includeSeaTimeEntry(s)}
                          className="text-left bg-[#0a0e1a] hover:bg-[#0a0e1a]/70
                            border border-white/8 hover:border-[#2dd4bf]/40
                            rounded-lg px-3 py-2 transition-colors"
                        >
                          <div className="font-mono text-xs text-[#f0ece4]">
                            {s.vessel_name}{' '}
                            <span className="text-[#2dd4bf]">·</span>{' '}
                            <span className="text-[#f0ece4]/70">{s.capacity_served}</span>
                          </div>
                          <div className="font-mono text-[10px] text-[#6b7594] mt-0.5">
                            {new Date(s.from_date + 'T00:00:00Z').toLocaleDateString(undefined, {
                              year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC',
                            })}{' '}
                            → {new Date(s.to_date + 'T00:00:00Z').toLocaleDateString(undefined, {
                              year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC',
                            })}{' '}
                            · {s.days_on_board}d
                          </div>
                        </button>
                      ))}
                    {prefill.sea_time_entries.filter((s) => !includedSeaTimeIds.has(s.id)).length === 0 && (
                      <p className="font-mono text-[11px] text-[#6b7594] italic">
                        All logged entries already added.
                      </p>
                    )}
                  </div>
                </section>
              )}

              {/* Vessel entries */}
              {entries.map((entry, idx) => (
                <section key={idx} className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-3">
                  <div className="flex items-center justify-between">
                    <p className="font-mono text-xs text-[#2dd4bf] uppercase tracking-wider">
                      Vessel {idx + 1}
                    </p>
                    {entries.length > 1 && (
                      <button onClick={() => removeEntry(idx)} className="font-mono text-[10px] text-red-400/70 hover:text-red-400">
                        Remove
                      </button>
                    )}
                  </div>

                  {prefill && prefill.vessels.length > 0 && (
                    <div className="flex flex-col gap-1">
                      <label className="font-mono text-xs text-[#6b7594]">Pre-fill from saved vessel</label>
                      <div className="relative">
                        <select
                          value={entry.vessel_id ?? ''}
                          onChange={(e) => {
                            if (e.target.value) preFillFromVessel(idx, e.target.value)
                            else updateEntry(idx, { vessel_id: null })
                          }}
                          className={`${inputClass} pr-10 appearance-none cursor-pointer`}
                        >
                          <option value="" style={{ backgroundColor: '#111827', color: '#f0ece4' }}>— Manual entry —</option>
                          {prefill.vessels.map((v) => (
                            <option key={v.id} value={v.id} style={{ backgroundColor: '#111827', color: '#f0ece4' }}>
                              {v.vessel_name}
                            </option>
                          ))}
                        </select>
                        <svg className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#6b7594] pointer-events-none" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="6 9 12 15 18 9" /></svg>
                      </div>
                    </div>
                  )}

                  <Field label="Vessel Name" required>
                    <input type="text" value={entry.vessel_name} onChange={(e) => updateEntry(idx, { vessel_name: e.target.value })} className={inputClass} />
                  </Field>

                  <div className="grid grid-cols-2 gap-3">
                    <Field label="Official Number">
                      <input type="text" value={entry.official_number} onChange={(e) => updateEntry(idx, { official_number: e.target.value })} className={inputClass} />
                    </Field>
                    <Field label="Gross Tonnage (GT)">
                      <input type="number" value={entry.gross_tonnage} onChange={(e) => updateEntry(idx, { gross_tonnage: e.target.value })} className={inputClass} />
                    </Field>
                  </div>

                  <Field label="Vessel Type">
                    <input type="text" value={entry.vessel_type} onChange={(e) => updateEntry(idx, { vessel_type: e.target.value })} placeholder="e.g. Containership" className={inputClass} />
                  </Field>

                  <div className="grid grid-cols-2 gap-3">
                    <Field label="Route">
                      <SelectInput value={entry.route_type} onChange={(v) => updateEntry(idx, { route_type: v })} options={ROUTE_OPTIONS} />
                    </Field>
                    <Field label="Propulsion">
                      <SelectInput value={entry.propulsion} onChange={(v) => updateEntry(idx, { propulsion: v })} options={PROPULSION_OPTIONS} />
                    </Field>
                  </div>

                  <Field label="Horsepower (for engineering credentials)">
                    <input type="text" value={entry.horsepower} onChange={(e) => updateEntry(idx, { horsepower: e.target.value })} placeholder="e.g. 75,000 HP" className={inputClass} />
                  </Field>

                  <Field label="Capacity Served" required>
                    <input
                      type="text"
                      value={entry.capacity_served}
                      onChange={(e) => updateEntry(idx, { capacity_served: e.target.value })}
                      list={`capacity-${idx}`}
                      placeholder="e.g. Master, Chief Engineer"
                      className={inputClass}
                    />
                    <datalist id={`capacity-${idx}`}>
                      {CAPACITY_HINTS.map((c) => <option key={c} value={c} />)}
                    </datalist>
                  </Field>

                  <div className="grid grid-cols-2 gap-3">
                    <Field label="From Date" required>
                      <input
                        type="date"
                        value={entry.from_date}
                        onChange={(e) => {
                          const newFrom = e.target.value
                          const auto = calculateDays(newFrom, entry.to_date)
                          updateEntry(idx, {
                            from_date: newFrom,
                            days_on_board: auto > 0 ? String(auto) : entry.days_on_board,
                          })
                        }}
                        className={`${inputClass} [color-scheme:dark]`}
                      />
                    </Field>
                    <Field label="To Date" required>
                      <input
                        type="date"
                        value={entry.to_date}
                        onChange={(e) => {
                          const newTo = e.target.value
                          const auto = calculateDays(entry.from_date, newTo)
                          updateEntry(idx, {
                            to_date: newTo,
                            days_on_board: auto > 0 ? String(auto) : entry.days_on_board,
                          })
                        }}
                        className={`${inputClass} [color-scheme:dark]`}
                      />
                    </Field>
                  </div>

                  <Field label="Days On Board" required>
                    <input
                      type="number"
                      min="0"
                      value={entry.days_on_board}
                      onChange={(e) => updateEntry(idx, { days_on_board: e.target.value })}
                      className={inputClass}
                    />
                    {entry.from_date && entry.to_date && calculateDays(entry.from_date, entry.to_date) > 0 && (
                      <p className="font-mono text-[10px] text-[#6b7594] mt-1">
                        Calendar days between dates: {calculateDays(entry.from_date, entry.to_date)}.
                        Override if actual days on board differs (relief crew, time off, etc.).
                      </p>
                    )}
                  </Field>
                </section>
              ))}

              <button
                onClick={addEntry}
                className="font-mono text-xs text-[#2dd4bf] hover:bg-[#2dd4bf]/10
                  border border-dashed border-[#2dd4bf]/30 rounded-xl py-3
                  transition-colors duration-150"
              >
                + Add Another Vessel
              </button>

              {/* Remarks */}
              <section className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-3">
                <Field label="Remarks (optional)">
                  <textarea
                    value={remarks}
                    onChange={(e) => setRemarks(e.target.value)}
                    rows={3}
                    placeholder="Additional notes about service, e.g. relief crew rotation, special duties"
                    className={inputClass}
                  />
                </Field>
              </section>

              {/* Summary */}
              <section className="bg-[#0d1225] border border-[#2dd4bf]/20 rounded-xl p-4 flex items-center justify-between">
                <span className="font-mono text-xs text-[#6b7594]">
                  Total Days of Service
                </span>
                <span className="font-mono text-lg text-[#2dd4bf] font-bold">
                  {totalDays}
                </span>
              </section>

              {error && (
                <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-3">
                  <p className="font-mono text-xs text-red-400">{error}</p>
                </div>
              )}

              {success && (
                <div className="bg-[#2dd4bf]/10 border border-[#2dd4bf]/30 rounded-xl p-4 flex flex-col gap-3">
                  <p className="font-mono text-xs text-[#2dd4bf]">
                    PDF downloaded. Send it to your employer to sign and return.
                  </p>
                  {/* D6.62 hotfix — replaces brittle mailto: with a modal
                      that copies / opens-in-webmail. mailto: is still
                      offered as a fallback inside the modal. */}
                  <EmailComposeButton
                    mode="compose"
                    subject="Sea Service Letter for Signature"
                    body={
                      `Hi${companyOfficialName ? ' ' + companyOfficialName.split(' ')[0] : ''},\n\n` +
                      `Please find attached a Sea Service Letter that I need signed for my USCG credential application` +
                      (targetEndorsement ? ` (${targetEndorsement})` : '') + `.\n\n` +
                      `The dates and vessel details are based on company records — please review for accuracy, ` +
                      `sign at the bottom, and return to me at your earliest convenience.\n\n` +
                      `Thank you,\n${applicantName}`
                    }
                    buttonClassName="font-mono text-xs font-bold text-[#2dd4bf]
                      border border-[#2dd4bf]/40 hover:bg-[#2dd4bf]/10
                      rounded-lg py-2 transition-colors duration-150"
                    buttonChildren="Email this letter to your employer"
                  />
                  <p className="font-mono text-[10px] text-[#6b7594]">
                    Don&apos;t forget to attach the downloaded PDF before sending.
                  </p>
                </div>
              )}

              {/* Generate + Clear */}
              <div className="flex items-center gap-3">
                <button
                  onClick={handleGenerate}
                  disabled={generating}
                  className="flex-1 font-mono text-sm font-bold text-[#0a0e1a] bg-[#2dd4bf]
                    hover:brightness-110 disabled:opacity-50 rounded-xl py-3
                    transition-[filter] duration-150"
                >
                  {generating ? 'Generating PDF...' : 'Download PDF'}
                </button>
                <button
                  onClick={clearForm}
                  className="font-mono text-xs text-[#6b7594] hover:text-red-400 px-4 py-3
                    transition-colors duration-150"
                >
                  Clear
                </button>
              </div>

              <p className="font-mono text-[10px] text-[#6b7594]/50 text-center pb-6 leading-relaxed">
                Letter format follows USCG NMC guidance.
                Verify all details for accuracy before submission.
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

function SelectInput({ value, onChange, options }: { value: string; onChange: (v: string) => void; options: string[] }) {
  return (
    <div className="relative">
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={`${inputClass} pr-10 appearance-none cursor-pointer`}
      >
        <option value="" style={{ backgroundColor: '#111827', color: '#f0ece4' }}>—</option>
        {options.map((o) => (
          <option key={o} value={o} style={{ backgroundColor: '#111827', color: '#f0ece4' }}>{o}</option>
        ))}
      </select>
      <svg className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#6b7594] pointer-events-none" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="6 9 12 15 18 9" /></svg>
    </div>
  )
}

export default function SeaServiceLetterPage() {
  return <AuthGuard><SeaServiceLetterContent /></AuthGuard>
}
