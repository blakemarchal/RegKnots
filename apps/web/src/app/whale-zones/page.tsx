/**
 * Whale Zones map page — Sprint D6.97 #49.
 *
 * Standalone Leaflet map visualizing NOAA Fisheries North Atlantic
 * Right Whale Seasonal Management Areas (SMAs). Public route, no
 * auth required (zones are public regulatory data under 50 CFR 224.105).
 *
 * The map dynamically imports `react-leaflet` because Leaflet itself
 * references `window` at module load and breaks Next.js SSR.
 *
 * Data source: GET /whale-zones/sma — returns a GeoJSON FeatureCollection
 * computed server-side from `apps/api/app/data/whale_sma_zones.py`.
 */
'use client'

import { useEffect, useMemo, useState } from 'react'
import dynamic from 'next/dynamic'
import 'leaflet/dist/leaflet.css'

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

// Dynamic imports — react-leaflet primitives only render client-side.
// Each is a small wrapper that maps a prop config onto the Leaflet API.
const MapContainer = dynamic(
  () => import('react-leaflet').then((m) => m.MapContainer),
  { ssr: false },
)
const TileLayer = dynamic(
  () => import('react-leaflet').then((m) => m.TileLayer),
  { ssr: false },
)
const GeoJSON = dynamic(
  () => import('react-leaflet').then((m) => m.GeoJSON),
  { ssr: false },
)

interface ZoneProps {
  name: string
  season_start: string
  season_end: string
  speed_limit_knots: number
  vessel_threshold_ft: number
  description: string
  authority: string
  zone_type: string
  mandatory: boolean
  active_now: boolean
}

interface ZoneFeature {
  type: 'Feature'
  id: string
  geometry: {
    type: 'Polygon'
    coordinates: number[][][]
  }
  properties: ZoneProps
}

interface ZoneCollection {
  type: 'FeatureCollection'
  features: ZoneFeature[]
  metadata: {
    source: string
    authority: string
    generated_at: string
    note: string
  }
}

export default function WhaleZonesPage() {
  const [data, setData] = useState<ZoneCollection | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showActiveOnly, setShowActiveOnly] = useState(false)
  const [selected, setSelected] = useState<ZoneFeature | null>(null)

  useEffect(() => {
    fetch(`${API_URL}/whale-zones/sma`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then(setData)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false))
  }, [])

  const displayedFeatures = useMemo(() => {
    if (!data) return []
    return showActiveOnly
      ? data.features.filter((f) => f.properties.active_now)
      : data.features
  }, [data, showActiveOnly])

  // Style each feature by active/inactive status.
  const zoneStyle = (feature?: ZoneFeature) => {
    if (!feature) return {}
    const active = feature.properties.active_now
    return {
      color: active ? '#dc2626' : '#64748b', // red-600 vs slate-500
      weight: 2,
      fillColor: active ? '#dc2626' : '#94a3b8',
      fillOpacity: active ? 0.35 : 0.15,
    }
  }

  const onEachZone = (feature: ZoneFeature, layer: { on: (event: string, handler: () => void) => void }) => {
    layer.on('click', () => setSelected(feature))
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="border-b border-slate-800 bg-slate-900/70 px-6 py-4">
        <div className="mx-auto flex max-w-7xl items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">
              Whale Zones — NOAA Right Whale SMAs
            </h1>
            <p className="mt-1 text-sm text-slate-400">
              North Atlantic Right Whale Seasonal Management Areas (50 CFR 224.105).
              Vessels ≥35 ft restricted to 10 knots during active seasons.
            </p>
          </div>
          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={showActiveOnly}
              onChange={(e) => setShowActiveOnly(e.target.checked)}
              className="h-4 w-4 rounded border-slate-600 bg-slate-800 text-emerald-500 focus:ring-emerald-500"
            />
            Show active zones only
          </label>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-6 py-6">
        {loading && (
          <p className="text-slate-400">Loading zones…</p>
        )}
        {error && (
          <p className="text-red-400">
            Could not load zones: {error}
          </p>
        )}

        <div className="grid gap-6 lg:grid-cols-[2fr_1fr]">
          {/* Map */}
          <div className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900">
            <div style={{ height: '600px', width: '100%' }}>
              {data && (
                <MapContainer
                  center={[36.5, -75.5]}
                  zoom={5}
                  style={{ height: '100%', width: '100%' }}
                >
                  <TileLayer
                    attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                    url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                  />
                  {displayedFeatures.map((feature) => (
                    <GeoJSON
                      key={feature.id}
                      data={feature}
                      style={() => zoneStyle(feature)}
                      onEachFeature={onEachZone}
                    />
                  ))}
                </MapContainer>
              )}
            </div>
          </div>

          {/* Side panel: zone list + selected detail */}
          <aside className="space-y-4">
            {selected && (
              <div className="rounded-lg border border-slate-700 bg-slate-900 p-4">
                <div className="flex items-baseline justify-between gap-3">
                  <h3 className="text-lg font-semibold">{selected.properties.name}</h3>
                  <span
                    className={`shrink-0 rounded px-2 py-1 text-xs font-medium ${
                      selected.properties.active_now
                        ? 'bg-red-900/40 text-red-300'
                        : 'bg-slate-800 text-slate-400'
                    }`}
                  >
                    {selected.properties.active_now ? 'ACTIVE' : 'inactive'}
                  </span>
                </div>
                <p className="mt-2 text-sm text-slate-300">
                  {selected.properties.description}
                </p>
                <dl className="mt-3 grid grid-cols-2 gap-2 text-sm">
                  <div>
                    <dt className="text-slate-500">Season</dt>
                    <dd>
                      {selected.properties.season_start} – {selected.properties.season_end}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-slate-500">Speed limit</dt>
                    <dd>{selected.properties.speed_limit_knots} kt</dd>
                  </div>
                  <div>
                    <dt className="text-slate-500">Applies to</dt>
                    <dd>≥{selected.properties.vessel_threshold_ft} ft vessels</dd>
                  </div>
                  <div>
                    <dt className="text-slate-500">Authority</dt>
                    <dd className="font-mono text-xs">{selected.properties.authority}</dd>
                  </div>
                </dl>
              </div>
            )}

            <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
              <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
                All zones ({displayedFeatures.length})
              </h3>
              <ul className="mt-3 space-y-1.5 text-sm">
                {displayedFeatures.map((f) => (
                  <li key={f.id}>
                    <button
                      onClick={() => setSelected(f)}
                      className="flex w-full items-center justify-between gap-2 rounded px-2 py-1 text-left hover:bg-slate-800"
                    >
                      <span className="truncate">{f.properties.name}</span>
                      <span
                        className={`shrink-0 text-xs ${
                          f.properties.active_now ? 'text-red-400' : 'text-slate-500'
                        }`}
                      >
                        {f.properties.active_now ? 'active' : 'off-season'}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>

            {data?.metadata && (
              <p className="px-2 text-xs text-slate-500">
                {data.metadata.note}
              </p>
            )}
          </aside>
        </div>
      </main>
    </div>
  )
}
