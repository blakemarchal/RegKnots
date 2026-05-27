/**
 * Whale Zones map page — Sprint D6.97 #49 / refresh #55-follow-up.
 *
 * Full-screen Leaflet map of NOAA Fisheries North Atlantic Right Whale
 * Seasonal Management Areas (SMAs). Filters and zone-detail live in
 * a collapsible right-side drawer so the map is the hero.
 *
 * Public route, no auth required (zones are public regulatory data
 * under 50 CFR 224.105).
 *
 * The map dynamically imports `react-leaflet` because Leaflet itself
 * references `window` at module load and breaks Next.js SSR.
 *
 * Data source: GET /whale-zones/sma — returns a GeoJSON FeatureCollection
 * computed server-side from `apps/api/app/data/whale_sma_zones.py`.
 */
'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import dynamic from 'next/dynamic'
import Link from 'next/link'
import 'leaflet/dist/leaflet.css'

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

// ── Dynamic Leaflet primitives (no SSR) ─────────────────────────────────
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

// ── Types ────────────────────────────────────────────────────────────────
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

// ── Page ─────────────────────────────────────────────────────────────────
export default function WhaleZonesPage() {
  const [data, setData] = useState<ZoneCollection | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showActiveOnly, setShowActiveOnly] = useState(false)
  const [selected, setSelected] = useState<ZoneFeature | null>(null)
  // Drawer is open by default on first render so users see the filters
  // and zone list without having to discover the toggle. Setting to
  // false collapses it; persists for the session via useState (we
  // intentionally don't localStorage-persist — refresh resets to open
  // so first-time UI surface stays predictable).
  const [drawerOpen, setDrawerOpen] = useState(true)
  // Mobile-aware default: on small screens start drawer closed so the
  // map gets the full viewport. Detection runs once on mount.
  useEffect(() => {
    if (typeof window !== 'undefined' && window.innerWidth < 768) {
      setDrawerOpen(false)
    }
  }, [])

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

  const activeCount = useMemo(
    () => (data?.features ?? []).filter((f) => f.properties.active_now).length,
    [data],
  )

  // Style each feature by active / selected / inactive status.
  const zoneStyle = useCallback(
    (feature?: ZoneFeature) => {
      if (!feature) return {}
      const active = feature.properties.active_now
      const isSelected = selected?.id === feature.id
      const baseColor = active ? '#dc2626' : '#64748b'
      return {
        color: isSelected ? '#fbbf24' : baseColor, // amber-400 selected outline
        weight: isSelected ? 3 : 2,
        fillColor: active ? '#dc2626' : '#94a3b8',
        fillOpacity: active ? 0.4 : 0.15,
      }
    },
    [selected],
  )

  type LeafletLayer = { on: (event: string, handler: () => void) => void }
  const onEachZone = useCallback(
    (feature: ZoneFeature, layer: LeafletLayer) => {
      layer.on('click', () => setSelected(feature))
    },
    [],
  )

  return (
    <div className="fixed inset-0 overflow-hidden bg-slate-950 text-slate-100">
      {/* ── Full-bleed map ─────────────────────────────────────────────── */}
      {data && (
        <MapContainer
          center={[36.5, -75.5]}
          zoom={5}
          style={{ position: 'absolute', inset: 0 }}
          zoomControl={false}
        >
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          {displayedFeatures.map((feature) => (
            <GeoJSON
              key={`${feature.id}-${selected?.id === feature.id ? 'sel' : 'unsel'}`}
              data={feature}
              style={() => zoneStyle(feature)}
              onEachFeature={onEachZone}
            />
          ))}
        </MapContainer>
      )}

      {/* ── Top bar (translucent) ───────────────────────────────────────── */}
      <header
        className="pointer-events-none absolute inset-x-0 top-0 z-[400] flex items-center
          justify-between gap-3 px-4 py-3 sm:px-6"
      >
        <div className="pointer-events-auto flex items-center gap-3 rounded-lg
          border border-slate-800/60 bg-slate-950/85 px-3 py-2 backdrop-blur">
          <Link
            href="/"
            className="font-display text-sm font-semibold tracking-wide text-emerald-300
              hover:text-emerald-200"
            aria-label="Back to RegKnots home"
          >
            RegKnots
          </Link>
          <span className="text-slate-700">/</span>
          <span className="font-mono text-xs uppercase tracking-widest text-slate-400">
            Whale Zones
          </span>
          {data && (
            <span
              className={`ml-2 inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs ${
                activeCount > 0
                  ? 'bg-red-950/60 text-red-300 ring-1 ring-red-700/40'
                  : 'bg-slate-900/60 text-slate-400 ring-1 ring-slate-700/40'
              }`}
            >
              <span className={`h-1.5 w-1.5 rounded-full ${
                activeCount > 0 ? 'bg-red-400 animate-pulse' : 'bg-slate-500'
              }`} />
              {activeCount} active today
            </span>
          )}
        </div>

        {!drawerOpen && (
          <button
            onClick={() => setDrawerOpen(true)}
            className="pointer-events-auto flex items-center gap-2 rounded-lg
              border border-slate-800/60 bg-slate-950/85 px-3 py-2 text-sm
              text-slate-200 backdrop-blur hover:bg-slate-900"
            aria-label="Open filters and zone list"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="3" y1="6" x2="21" y2="6" />
              <line x1="3" y1="12" x2="21" y2="12" />
              <line x1="3" y1="18" x2="21" y2="18" />
            </svg>
            <span className="hidden sm:inline">Filters &amp; zones</span>
          </button>
        )}
      </header>

      {/* ── Loading / error overlay ─────────────────────────────────────── */}
      {loading && !data && (
        <div className="absolute inset-0 z-[300] flex items-center justify-center
          bg-slate-950/60 backdrop-blur-sm">
          <p className="rounded-lg bg-slate-900/90 px-4 py-3 text-sm text-slate-300">
            Loading whale zones…
          </p>
        </div>
      )}
      {error && (
        <div className="absolute inset-x-4 top-20 z-[300] mx-auto max-w-md rounded-lg
          border border-red-800/50 bg-red-950/80 px-4 py-3 text-sm text-red-200">
          Could not load zones: {error}
        </div>
      )}

      {/* ── Drawer ─────────────────────────────────────────────────────── */}
      <aside
        className={`absolute right-0 top-0 z-[450] flex h-full w-full max-w-[400px]
          flex-col border-l border-slate-800/60 bg-slate-950/95 shadow-2xl
          backdrop-blur transition-transform duration-300 ease-out ${
            drawerOpen ? 'translate-x-0' : 'translate-x-full'
          }`}
        aria-hidden={!drawerOpen}
      >
        {/* Drawer header */}
        <div className="flex shrink-0 items-center justify-between gap-3 border-b
          border-slate-800/60 px-4 py-3">
          <div>
            <h2 className="text-base font-semibold text-slate-100">
              Right Whale SMAs
            </h2>
            <p className="font-mono text-[10px] uppercase tracking-widest text-slate-500">
              50 CFR 224.105
            </p>
          </div>
          <button
            onClick={() => setDrawerOpen(false)}
            className="rounded-md p-1.5 text-slate-400 hover:bg-slate-800
              hover:text-slate-200"
            aria-label="Close drawer"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        {/* Drawer body — scrolls when content overflows */}
        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-5">
          {/* Filters */}
          <section>
            <h3 className="mb-2 font-mono text-[10px] uppercase tracking-widest
              text-slate-500">
              Filters
            </h3>
            <label className="flex items-center gap-2 text-sm text-slate-200">
              <input
                type="checkbox"
                checked={showActiveOnly}
                onChange={(e) => setShowActiveOnly(e.target.checked)}
                className="h-4 w-4 rounded border-slate-600 bg-slate-800
                  text-emerald-500 focus:ring-emerald-500 focus:ring-offset-slate-950"
              />
              <span>Show active zones only</span>
            </label>
          </section>

          {/* Legend */}
          <section>
            <h3 className="mb-2 font-mono text-[10px] uppercase tracking-widest
              text-slate-500">
              Legend
            </h3>
            <ul className="space-y-1.5 text-sm">
              <li className="flex items-center gap-2 text-slate-200">
                <span className="inline-block h-3 w-3 rounded-sm border border-red-600
                  bg-red-600/40" />
                <span>Active today — 10 kt limit in force</span>
              </li>
              <li className="flex items-center gap-2 text-slate-200">
                <span className="inline-block h-3 w-3 rounded-sm border border-slate-500
                  bg-slate-500/15" />
                <span>Off-season — no current restriction</span>
              </li>
              <li className="flex items-center gap-2 text-slate-200">
                <span className="inline-block h-3 w-3 rounded-sm border-2 border-amber-400" />
                <span>Selected</span>
              </li>
            </ul>
          </section>

          {/* Selected zone detail */}
          {selected && (
            <section className="rounded-lg border border-slate-700/70 bg-slate-900/70 p-3">
              <div className="flex items-baseline justify-between gap-3">
                <h3 className="text-sm font-semibold text-slate-100">
                  {selected.properties.name}
                </h3>
                <span
                  className={`shrink-0 rounded px-2 py-0.5 text-[10px] font-medium uppercase
                    tracking-wider ${
                      selected.properties.active_now
                        ? 'bg-red-950/60 text-red-300'
                        : 'bg-slate-800/60 text-slate-400'
                    }`}
                >
                  {selected.properties.active_now ? 'Active' : 'Inactive'}
                </span>
              </div>
              <p className="mt-2 text-sm leading-relaxed text-slate-300">
                {selected.properties.description}
              </p>
              <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 text-xs">
                <div>
                  <dt className="text-slate-500">Season</dt>
                  <dd className="text-slate-200">
                    {selected.properties.season_start} – {selected.properties.season_end}
                  </dd>
                </div>
                <div>
                  <dt className="text-slate-500">Speed limit</dt>
                  <dd className="text-slate-200">
                    {selected.properties.speed_limit_knots} kt
                  </dd>
                </div>
                <div>
                  <dt className="text-slate-500">Applies to</dt>
                  <dd className="text-slate-200">
                    ≥{selected.properties.vessel_threshold_ft} ft vessels
                  </dd>
                </div>
                <div>
                  <dt className="text-slate-500">Authority</dt>
                  <dd className="font-mono text-[11px] text-slate-200">
                    {selected.properties.authority}
                  </dd>
                </div>
              </dl>
            </section>
          )}

          {/* All zones list */}
          <section>
            <h3 className="mb-2 font-mono text-[10px] uppercase tracking-widest
              text-slate-500">
              All zones ({displayedFeatures.length})
            </h3>
            <ul className="space-y-0.5 text-sm">
              {displayedFeatures.map((f) => {
                const isSelected = selected?.id === f.id
                return (
                  <li key={f.id}>
                    <button
                      onClick={() => setSelected(f)}
                      className={`flex w-full items-center justify-between gap-2
                        rounded px-2 py-1.5 text-left transition-colors ${
                          isSelected
                            ? 'bg-slate-800 text-slate-100 ring-1 ring-amber-400/50'
                            : 'text-slate-300 hover:bg-slate-800/70'
                        }`}
                    >
                      <span className="truncate text-sm">{f.properties.name}</span>
                      <span
                        className={`shrink-0 text-[10px] font-medium uppercase
                          tracking-wider ${
                            f.properties.active_now
                              ? 'text-red-400'
                              : 'text-slate-500'
                          }`}
                      >
                        {f.properties.active_now ? 'Active' : 'Off-season'}
                      </span>
                    </button>
                  </li>
                )
              })}
            </ul>
          </section>

          {/* Attribution / disclaimer */}
          {data?.metadata && (
            <section className="mt-4 border-t border-slate-800/60 pt-3">
              <p className="text-xs leading-relaxed text-slate-500">
                {data.metadata.note}
              </p>
              <p className="mt-2 font-mono text-[10px] uppercase tracking-widest
                text-slate-600">
                Source: {data.metadata.source}
              </p>
            </section>
          )}
        </div>
      </aside>

      {/* ── Backdrop on mobile when drawer is open ─────────────────────── */}
      {drawerOpen && (
        <button
          onClick={() => setDrawerOpen(false)}
          className="absolute inset-0 z-[440] bg-black/40 backdrop-blur-sm md:hidden"
          aria-label="Close drawer"
        />
      )}
    </div>
  )
}
