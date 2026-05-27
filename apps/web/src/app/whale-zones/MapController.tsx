/**
 * MapController — bridges parent-page state (selected zone bounds, user
 * GPS location) to imperative Leaflet calls (flyToBounds, flyTo).
 *
 * Must be a child of <MapContainer> because react-leaflet's `useMap`
 * hook only works inside a MapContainer subtree. The parent page lazy-
 * loads this component via `next/dynamic` because the useMap hook
 * (and Leaflet itself) reference `window` at module-load time and
 * break Next.js SSR.
 */
'use client'

import { useEffect } from 'react'
import { useMap } from 'react-leaflet'
import type { LatLngBoundsExpression } from 'leaflet'

interface Props {
  selectedBounds: [[number, number], [number, number]] | null
  userLocation: [number, number] | null
}

export function MapController({ selectedBounds, userLocation }: Props) {
  const map = useMap()

  // Feature 3: auto-pan/fit on zone selection. When the user clicks a
  // zone (either on the map or in the drawer list) the map flies to
  // its bounds with a smooth animation, clamped to maxZoom=8 so we
  // don't zoom past the regional scale that gives the zone context.
  useEffect(() => {
    if (!selectedBounds) return
    map.flyToBounds(selectedBounds as LatLngBoundsExpression, {
      padding: [60, 60],
      maxZoom: 8,
      duration: 0.8,
    })
  }, [selectedBounds, map])

  // Feature 4 follow-up: pan-to-user when geolocation lands for the
  // first time, but ONLY if the user hasn't already focused a zone.
  // Avoids fighting the user's selection intent.
  useEffect(() => {
    if (!userLocation || selectedBounds) return
    map.flyTo(userLocation, Math.max(map.getZoom(), 6), { duration: 0.8 })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userLocation])

  return null
}
