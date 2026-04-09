import type { NextConfig } from "next";
import { withSentryConfig } from "@sentry/nextjs";
import withPWA from "@ducanh2912/next-pwa";

const nextConfig: NextConfig = {};

const pwaConfig = withPWA({
  dest: "public",
  disable: process.env.NODE_ENV === "development",
  register: true,
  cacheOnFrontEndNav: false,
  aggressiveFrontEndNavCaching: false,
  cacheStartUrl: false,
  dynamicStartUrl: false,
  extendDefaultRuntimeCaching: true,
  // Navigation fallback — when a navigation request fails and no cache
  // entry is available (e.g. fresh offline visit), serve /offline.html
  // instead of the browser's default ERR_INTERNET_DISCONNECTED page.
  // `fallbacks` is a top-level next-pwa option, not a Workbox GenerateSW one.
  fallbacks: {
    document: "/offline.html",
  },
  workboxOptions: {
    cacheId: "regknots-v7",
    disableDevLogs: true,
    // Eliminate the precache manifest entirely for Next build assets. Hashed
    // chunk URLs in a stale precache list caused bad-precaching-response 404s
    // after every redeploy; we precache only the explicit entries below and
    // rely on runtime caching (defined below) to populate chunks on visit.
    exclude: [/.*/],
    // Explicit precache entries. /offline.html is always available as the
    // navigation fallback. /reference is the offline safety net so mariners
    // can pull up rules even without a prior visit. Bump the revision string
    // when the page content changes to force re-precache.
    additionalManifestEntries: [
      { url: "/offline.html", revision: "offline-v1" },
      { url: "/reference", revision: "reference-v1" },
    ],
    runtimeCaching: [
      // ── NetworkOnly: auth + mutating API routes ────────────────────────
      // These MUST always hit the network — no cached auth, no cached chat.
      {
        urlPattern: /\/api\/auth\/.*/,
        handler: "NetworkOnly",
      },
      {
        urlPattern: /\/api\/billing\/.*/,
        handler: "NetworkOnly",
      },
      {
        urlPattern: /\/api\/admin\/.*/,
        handler: "NetworkOnly",
      },
      {
        urlPattern: /\/api\/chat(\/.*)?$/,
        handler: "NetworkOnly",
      },
      {
        urlPattern: /\/api\/vessels(\/.*)?$/,
        handler: "NetworkOnly",
      },
      {
        // Catch-all for every other /api/* route — must stay NetworkOnly
        // so the default next-pwa `apis` NetworkFirst rule never catches
        // them and accidentally serves stale API responses offline.
        urlPattern: ({ url, sameOrigin }: { url: URL; sameOrigin: boolean }) =>
          sameOrigin && url.pathname.startsWith("/api/"),
        handler: "NetworkOnly",
      },

      // ── CacheFirst: immutable Next.js static assets ────────────────────
      // Hashed chunks/css/media never change for a given build. CacheFirst
      // gives instant offline loads once the user has been online at least
      // once. The default next-pwa `next-static-js-assets` rule only covers
      // .js — this covers the full /_next/static/** tree.
      {
        urlPattern: /\/_next\/static\/.+/i,
        handler: "CacheFirst",
        options: {
          cacheName: "next-static",
          expiration: {
            maxEntries: 256,
            maxAgeSeconds: 30 * 24 * 60 * 60, // 30 days
          },
        },
      },

      // ── StaleWhileRevalidate: app shell navigation requests ────────────
      // Serves the cached HTML shell instantly offline and updates in the
      // background when online. Placed BEFORE the next-pwa default `pages`
      // NetworkFirst rule so cached routes load immediately without the
      // NetworkFirst timeout when the network is slow or unavailable.
      {
        urlPattern: ({ url, request, sameOrigin }: {
          url: URL
          request: Request
          sameOrigin: boolean
        }) => {
          if (!sameOrigin) return false
          if (request.mode !== "navigate") return false
          if (url.pathname.startsWith("/api/")) return false
          return true
        },
        handler: "StaleWhileRevalidate",
        options: {
          cacheName: "app-pages",
          expiration: {
            maxEntries: 32,
            maxAgeSeconds: 7 * 24 * 60 * 60, // 7 days
          },
        },
      },

      // ── StaleWhileRevalidate: Next.js data fetching ────────────────────
      {
        urlPattern: /\/_next\/data\/.+/i,
        handler: "StaleWhileRevalidate",
        options: {
          cacheName: "next-data",
          expiration: {
            maxEntries: 32,
            maxAgeSeconds: 24 * 60 * 60, // 24h
          },
        },
      },
    ],
  },
})(nextConfig);

export default process.env.NEXT_PUBLIC_SENTRY_DSN
  ? withSentryConfig(pwaConfig, { silent: true })
  : pwaConfig;
