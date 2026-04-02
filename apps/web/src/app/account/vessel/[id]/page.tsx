'use client'

import { useEffect, useState } from 'react'
import { useRouter, useParams } from 'next/navigation'
import AuthGuard from '@/components/AuthGuard'
import { apiRequest } from '@/lib/api'

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

interface VesselData {
  id: string
  name: string
  vessel_type: string
  route_types: string[]
  cargo_types: string[]
  gross_tonnage: number | null
}

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
          onClick={() => router.back()}
          className="w-9 h-9 flex items-center justify-center rounded-lg
            text-[#6b7594] hover:text-[#f0ece4] transition-colors duration-150"
          aria-label="Back"
        >
          <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M19 12H5M12 5l-7 7 7 7" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
        <h1 className="font-display text-xl font-bold text-[#f0ece4] tracking-wide leading-none">
          Edit Vessel
        </h1>
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
