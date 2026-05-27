/**
 * Whale Zones map page — Sprint D6.97 #49 + 4-feature follow-up.
 *
 * Full-screen Leaflet map of NOAA Fisheries North Atlantic Right Whale
 * Seasonal Management Areas (SMAs) with collapsible right drawer.
 *
 * Features (2026-05-27):
 *   1. Zone-type filter (SMA today, DMA placeholder for when the
 *      NOAA WhaleAlert dynamic-area feed lands)
 *   2. Date scrubber — recomputes active-now client-side for any date
 *      so users can answer "was zone X active when we transited?"
 *   3. Auto-pan/fit on selection — flies to the selected polygon
 *   4. Vessel-position pin via opt-in browser Geolocation
 *
 * Public route, no auth required (zones are public regulatory data
 * under 50 CFR 224.105). GPS is strictly browser-prompted; we never
 * persist coordinates server-side.
 */
'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import dynamic from 'next/dynamic'
import 'leaflet/dist/leaflet.css'
import { AppHeader } from '@/components/AppHeader'

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
const CircleMarker = dynamic(
  () => import('react-leaflet').then((m) => m.CircleMarker),
  { ssr: false },
)
// MapController uses the useMap hook → must be a hook-aware component
// that itself runs only client-side. Wrap it via dynamic import too.
const MapController = dynamic(
  () => import('./MapController').then((m) => m.MapController),
  { ssr: false },
)

// ── Types ────────────────────────────────────────────────────────────────
interface ZoneProps {
  name: string
  season_start: string  // "MM-DD"
  season_end: string    // "MM-DD"
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

// ── Pure helpers ────────────────────────────────────────────────────────

/** True when (month, day) of `date` falls inside the season window. Handles
 *  wrap-around windows like Nov 1 – Apr 30 that cross year boundary.
 *  Mirrors `_is_active` in apps/api/app/routers/whale_zones.py. */
function dateIsActive(
  dateISO: string,         // "YYYY-MM-DD"
  seasonStart: string,     // "MM-DD"
  seasonEnd: string,       // "MM-DD"
): boolean {
  const [, mStr, dStr] = dateISO.split('-')
  const today: [number, number] = [Number(mStr), Number(dStr)]
  const start: [number, number] =
    seasonStart.split('-').map(Number) as [number, number]
  const end: [number, number] =
    seasonEnd.split('-').map(Number) as [number, number]
  const leq = (a: [number, number], b: [number, number]) =>
    a[0] < b[0] || (a[0] === b[0] && a[1] <= b[1])
  if (leq(start, end)) {
    return leq(start, today) && leq(today, end)
  }
  // Wrap-around window (Nov-Apr) — active if today ≥ start OR today ≤ end
  return leq(start, today) || leq(today, end)
}

/** Format YYYY-MM-DD for an HTML date input from today's date. */
function todayISO(): string {
  const d = new Date()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${m}-${day}`
}

/** Compute the polygon's bounding box as [[south,west],[north,east]]
 *  in Leaflet lat/lng order. GeoJSON stores lon-first. */
function bboxLatLng(
  coords: number[][][],
): [[number, number], [number, number]] {
  let minLat = +Infinity, maxLat = -Infinity
  let minLon = +Infinity, maxLon = -Infinity
  for (const ring of coords) {
    for (const [lon, lat] of ring) {
      if (lat < minLat) minLat = lat
      if (lat > maxLat) maxLat = lat
      if (lon < minLon) minLon = lon
      if (lon > maxLon) maxLon = lon
    }
  }
  return [
    [minLat, minLon],
    [maxLat, maxLon],
  ]
}

/** Haversine distance in nautical miles between two [lat,lon] points. */
function distanceNm(a: [number, number], b: [number, number]): number {
  const R = 3440.065 // Earth radius in nm
  const toRad = (x: number) => (x * Math.PI) / 180
  const dLat = toRad(b[0] - a[0])
  const dLon = toRad(b[1] - a[1])
  const lat1 = toRad(a[0])
  const lat2 = toRad(b[0])
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2
  return 2 * R * Math.asin(Math.sqrt(h))
}

// ── Page ─────────────────────────────────────────────────────────────────
export default function WhaleZonesPage() {
  const [data, setData] = useState<ZoneCollection | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showActiveOnly, setShowActiveOnly] = useState(false)
  const [selected, setSelected] = useState<ZoneFeature | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(true)

  // Feature 1: zone-type filter. SMA today; DMA placeholder for when
  // the WhaleAlert dynamic-area feed lands.
  const [showSMA] = useState(true)

  // Feature 2: date scrubber. Default to today; user can pick any date
  // and zones recompute active/inactive client-side.
  const [dateISO, setDateISO] = useState(todayISO())
  const isToday = dateISO === todayISO()

  // Feature 4: user-opted-in geolocation. Pin only renders after
  // explicit click → browser permission grant. Server-side persistence
  // is gated by the separate account-page toggle
  // (`users.location_tracking_enabled`). When that toggle is OFF, the
  // pin is browser-session only. When ON, the page POSTs to
  // /me/location on initial share and again every 5 min while mounted.
  const [userLocation, setUserLocation] = useState<[number, number] | null>(null)
  const [locStatus, setLocStatus] = useState<'idle' | 'requesting' | 'denied' | 'unavailable' | 'ok'>('idle')
  const [serverTrackingEnabled, setServerTrackingEnabled] = useState<boolean>(false)
  const [lastPersistedAt, setLastPersistedAt] = useState<string | null>(null)

  // Mobile default: drawer closed on <768px so map gets full viewport.
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

  // Sprint D6.97 #56 — check whether the user has the account-page
  // toggle on for opt-in GPS persistence. Determines whether
  // "Show my location" POSTs to /me/location or stays browser-only.
  // 401 (unauthenticated public visitor) is expected and silent.
  useEffect(() => {
    fetch(`${API_URL}/onboarding/persona`, { credentials: 'include' })
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => {
        if (j && typeof j.location_tracking_enabled === 'boolean') {
          setServerTrackingEnabled(j.location_tracking_enabled)
        }
      })
      .catch(() => {})
  }, [])

  // Helper: POST current position to the server if the user has
  // opted-in via /account. Silent on 401/403 (unauthed or toggle-off).
  const persistLocation = useCallback(
    (lat: number, lon: number, accuracy?: number) => {
      if (!serverTrackingEnabled) return
      fetch(`${API_URL}/me/location`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          lat,
          lon,
          accuracy_m: accuracy ?? null,
          source: 'whale_zones',
        }),
      })
        .then((r) => (r.ok ? r.json() : null))
        .then((j) => {
          if (j?.stored_at) setLastPersistedAt(j.stored_at)
        })
        .catch(() => {})
    },
    [serverTrackingEnabled],
  )

  // Periodic refresh: if the user has GPS on AND the account toggle
  // is on, re-request position every 5 minutes while the page is
  // mounted so the stored position stays warm. Stops if either flag
  // turns off or the page unmounts. We use silent permission (user
  // already granted; getCurrentPosition won't re-prompt).
  useEffect(() => {
    if (!userLocation || !serverTrackingEnabled) return
    const REFRESH_MS = 5 * 60 * 1000  // 5 min
    const interval = setInterval(() => {
      if (typeof navigator === 'undefined' || !navigator.geolocation) return
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          setUserLocation([pos.coords.latitude, pos.coords.longitude])
          persistLocation(pos.coords.latitude, pos.coords.longitude, pos.coords.accuracy)
        },
        () => {}, // silent fail; user revoked permission or no signal
        { enableHighAccuracy: false, timeout: 10_000, maximumAge: 60_000 },
      )
    }, REFRESH_MS)
    return () => clearInterval(interval)
  }, [userLocation, serverTrackingEnabled, persistLocation])

  // Compute active state per zone for the selected date. Falls back to
  // server-computed active_now when the date is today (consistent with
  // server's idea of "now").
  const featuresWithActive: ZoneFeature[] = useMemo(() => {
    if (!data) return []
    if (isToday) return data.features
    return data.features.map((f) => ({
      ...f,
      properties: {
        ...f.properties,
        active_now: dateIsActive(
          dateISO,
          f.properties.season_start,
          f.properties.season_end,
        ),
      },
    }))
  }, [data, dateISO, isToday])

  const displayedFeatures = useMemo(
    () =>
      featuresWithActive.filter((f) => {
        if (!showSMA && f.properties.zone_type === 'SMA') return false
        if (showActiveOnly && !f.properties.active_now) return false
        return true
      }),
    [featuresWithActive, showSMA, showActiveOnly],
  )

  const activeCount = useMemo(
    () => featuresWithActive.filter((f) => f.properties.active_now).length,
    [featuresWithActive],
  )

  // Style each feature by active / selected / inactive status.
  const zoneStyle = useCallback(
    (feature?: ZoneFeature) => {
      if (!feature) return {}
      const active = feature.properties.active_now
      const isSelected = selected?.id === feature.id
      const baseColor = active ? '#dc2626' : '#64748b'
      return {
        color: isSelected ? '#fbbf24' : baseColor,
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

  // Feature 4 handler: user clicks "Show my location" → request browser
  // geolocation. Privacy: the browser's own prompt is the consent flow
  // for sharing on-screen. Server-side persistence has a SEPARATE
  // consent gate (account-page toggle); persistLocation() is silent
  // when that toggle is off.
  const requestUserLocation = useCallback(() => {
    if (typeof navigator === 'undefined' || !navigator.geolocation) {
      setLocStatus('unavailable')
      return
    }
    setLocStatus('requesting')
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setUserLocation([pos.coords.latitude, pos.coords.longitude])
        setLocStatus('ok')
        persistLocation(pos.coords.latitude, pos.coords.longitude, pos.coords.accuracy)
      },
      (err) => {
        setLocStatus(err.code === err.PERMISSION_DENIED ? 'denied' : 'unavailable')
      },
      { enableHighAccuracy: false, timeout: 10_000, maximumAge: 60_000 },
    )
  }, [persistLocation])

  // Selected-zone bounds for the auto-pan controller.
  const selectedBounds = useMemo(
    () => (selected ? bboxLatLng(selected.geometry.coordinates) : null),
    [selected],
  )

  // Distance from user to selected zone (if both available).
  const userDistanceToSelected = useMemo(() => {
    if (!userLocation || !selectedBounds) return null
    const center: [number, number] = [
      (selectedBounds[0][0] + selectedBounds[1][0]) / 2,
      (selectedBounds[0][1] + selectedBounds[1][1]) / 2,
    ]
    return distanceNm(userLocation, center)
  }, [userLocation, selectedBounds])

  // Active-zone badge rendered in the AppHeader's trailing slot so
  // users keep the count visible whether the drawer is open or not.
  const activeBadge = data ? (
    <span
      className={`ml-2 inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] ${
        activeCount > 0
          ? 'bg-red-950/60 text-red-300 ring-1 ring-red-700/40'
          : 'bg-slate-900/60 text-slate-400 ring-1 ring-slate-700/40'
      }`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${
        activeCount > 0 ? 'bg-red-400 animate-pulse' : 'bg-slate-500'
      }`} />
      {activeCount} active {isToday ? 'today' : `on ${dateISO}`}
    </span>
  ) : null

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-slate-950 text-slate-100">
      {/* ── Global header (logo + page title + hamburger nav) ─────────── */}
      <AppHeader title="Whale Zones" trailing={activeBadge} />

      {/* ── Map + drawer fill the remainder of the viewport ───────────── */}
      <div className="relative flex-1 overflow-hidden">
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
              key={`${feature.id}-${selected?.id === feature.id ? 'sel' : 'unsel'}-${feature.properties.active_now ? 'on' : 'off'}`}
              data={feature}
              style={() => zoneStyle(feature)}
              onEachFeature={onEachZone}
            />
          ))}
          {userLocation && (
            <CircleMarker
              center={userLocation}
              radius={7}
              pathOptions={{
                color: '#22d3ee',          // cyan-400
                fillColor: '#22d3ee',
                fillOpacity: 0.8,
                weight: 2,
              }}
            />
          )}
          <MapController selectedBounds={selectedBounds} userLocation={userLocation} />
        </MapContainer>
      )}

      {/* ── Floating filters toggle (when drawer collapsed) ─────────────── */}
      {!drawerOpen && (
        <button
          onClick={() => setDrawerOpen(true)}
          className="absolute right-4 top-4 z-[400] flex items-center gap-2 rounded-lg
            border border-slate-800/60 bg-slate-950/85 px-3 py-2 text-sm text-slate-200
            backdrop-blur hover:bg-slate-900"
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
        className={`absolute right-0 top-0 z-[450] flex h-full w-full max-w-[420px]
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

        {/* Drawer body */}
        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-5">
          {/* Date scrubber */}
          <section>
            <h3 className="mb-2 font-mono text-[10px] uppercase tracking-widest
              text-slate-500">
              Date
            </h3>
            <div className="flex items-center gap-2">
              <input
                type="date"
                value={dateISO}
                onChange={(e) => setDateISO(e.target.value)}
                className="flex-1 rounded-md border border-slate-700 bg-slate-900 px-2 py-1.5
                  text-sm text-slate-100 focus:border-emerald-500 focus:outline-none"
              />
              {!isToday && (
                <button
                  onClick={() => setDateISO(todayISO())}
                  className="rounded-md border border-slate-700 bg-slate-900 px-2 py-1.5
                    text-xs text-slate-300 hover:bg-slate-800"
                >
                  Today
                </button>
              )}
            </div>
            <p className="mt-1.5 text-[11px] leading-relaxed text-slate-500">
              Pick a date to see which zones were/are/will be active.
              Useful for transit-audit lookups.
            </p>
          </section>

          {/* Zone-type filter */}
          <section>
            <h3 className="mb-2 font-mono text-[10px] uppercase tracking-widest
              text-slate-500">
              Zone types
            </h3>
            <ul className="space-y-1.5 text-sm">
              <li className="flex items-center justify-between gap-2 text-slate-200">
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={showSMA}
                    readOnly
                    className="h-4 w-4 rounded border-slate-600 bg-slate-800
                      text-emerald-500 focus:ring-emerald-500"
                  />
                  <span>SMA — Seasonal (mandatory)</span>
                </label>
                <span className="font-mono text-[10px] text-slate-500">
                  {data?.features.length ?? 0}
                </span>
              </li>
              <li className="flex items-center justify-between gap-2 text-slate-500">
                <label className="flex items-center gap-2 opacity-60">
                  <input
                    type="checkbox"
                    disabled
                    className="h-4 w-4 rounded border-slate-700 bg-slate-800"
                  />
                  <span>DMA — Dynamic (voluntary)</span>
                </label>
                <span className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-[9px]
                  uppercase tracking-wider text-slate-400">
                  Soon
                </span>
              </li>
            </ul>
          </section>

          {/* Active-only toggle */}
          <section>
            <label className="flex items-center gap-2 text-sm text-slate-200">
              <input
                type="checkbox"
                checked={showActiveOnly}
                onChange={(e) => setShowActiveOnly(e.target.checked)}
                className="h-4 w-4 rounded border-slate-600 bg-slate-800
                  text-emerald-500 focus:ring-emerald-500 focus:ring-offset-slate-950"
              />
              <span>Show only zones active on {isToday ? 'today' : dateISO}</span>
            </label>
          </section>

          {/* My location (GPS opt-in) */}
          <section>
            <h3 className="mb-2 font-mono text-[10px] uppercase tracking-widest
              text-slate-500">
              My position
            </h3>
            {!userLocation && (
              <button
                onClick={requestUserLocation}
                disabled={locStatus === 'requesting'}
                className="flex w-full items-center justify-between gap-2 rounded-md
                  border border-cyan-700/60 bg-cyan-950/40 px-3 py-2 text-sm text-cyan-200
                  hover:bg-cyan-900/40 disabled:opacity-50"
              >
                <span>
                  {locStatus === 'requesting' ? 'Requesting…' : 'Show my location'}
                </span>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
                  stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="3" />
                  <line x1="12" y1="2" x2="12" y2="5" />
                  <line x1="12" y1="19" x2="12" y2="22" />
                  <line x1="2" y1="12" x2="5" y2="12" />
                  <line x1="19" y1="12" x2="22" y2="12" />
                </svg>
              </button>
            )}
            {userLocation && (
              <div className="rounded-md border border-cyan-700/60 bg-cyan-950/30 p-2.5
                text-xs text-cyan-200">
                <p className="font-mono">
                  {userLocation[0].toFixed(4)}, {userLocation[1].toFixed(4)}
                </p>
                <button
                  onClick={() => {
                    setUserLocation(null)
                    setLocStatus('idle')
                  }}
                  className="mt-1 text-[11px] text-cyan-300/70 underline-offset-2 hover:underline"
                >
                  Hide my location
                </button>
              </div>
            )}
            {locStatus === 'denied' && !userLocation && (
              <p className="mt-1.5 text-[11px] text-amber-300/80">
                Permission denied. Enable location in your browser to retry.
              </p>
            )}
            {locStatus === 'unavailable' && !userLocation && (
              <p className="mt-1.5 text-[11px] text-amber-300/80">
                Location unavailable from this browser/device.
              </p>
            )}
            {!userLocation && locStatus !== 'requesting' && locStatus !== 'denied' && locStatus !== 'unavailable' && (
              <p className="mt-1.5 text-[11px] leading-relaxed text-slate-500">
                Optional. Your browser will prompt for permission.
                {serverTrackingEnabled
                  ? ' Your last position will be saved to your account for personalized chat responses (enable/disable on /account).'
                  : ' Position stays in this browser session only. Enable location tracking on /account to use it for personalized chat responses.'}
              </p>
            )}
            {userLocation && serverTrackingEnabled && lastPersistedAt && (
              <p className="mt-1.5 text-[11px] leading-relaxed text-cyan-300/70">
                Saved to your account · refreshes every 5 min while this page is open
              </p>
            )}
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
                <span>Active — 10 kt limit in force</span>
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
              {userLocation && (
                <li className="flex items-center gap-2 text-slate-200">
                  <span className="inline-block h-3 w-3 rounded-full border-2 border-cyan-400
                    bg-cyan-400/60" />
                  <span>You</span>
                </li>
              )}
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
                      // Reflect the DATE-SCRUBBER computed state, not the
                      // server's frozen active_now (which is "today" only).
                      featuresWithActive.find((f) => f.id === selected.id)?.properties.active_now
                        ? 'bg-red-950/60 text-red-300'
                        : 'bg-slate-800/60 text-slate-400'
                    }`}
                >
                  {featuresWithActive.find((f) => f.id === selected.id)?.properties.active_now
                    ? 'Active'
                    : 'Inactive'}
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
                {userDistanceToSelected !== null && (
                  <div className="col-span-2 mt-1 rounded bg-cyan-950/30
                    px-2 py-1.5 ring-1 ring-cyan-800/40">
                    <dt className="text-cyan-400/80 text-[10px] uppercase tracking-wider">
                      Distance from you
                    </dt>
                    <dd className="text-cyan-200">
                      ~{userDistanceToSelected.toFixed(1)} nm to centroid
                    </dd>
                  </div>
                )}
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

      {/* ── Mobile backdrop when drawer is open ────────────────────────── */}
      {drawerOpen && (
        <button
          onClick={() => setDrawerOpen(false)}
          className="absolute inset-0 z-[440] bg-black/40 backdrop-blur-sm md:hidden"
          aria-label="Close drawer"
        />
      )}
      </div>
    </div>
  )
}
