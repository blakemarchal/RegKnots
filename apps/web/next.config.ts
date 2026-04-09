import type { NextConfig } from "next";
import { withSentryConfig } from "@sentry/nextjs";
import withPWA from "@ducanh2912/next-pwa";

const nextConfig: NextConfig = {};

const pwaConfig = withPWA({
  dest: "public",
  disable: process.env.NODE_ENV === "development",
  register: true,
  // Aggressively cache every page the user visits on client-side nav. This
  // is what makes offline navigation *actually* work after a first visit —
  // without it, route transitions that rely on RSC data fetches won't warm
  // the cache.
  cacheOnFrontEndNav: true,
  aggressiveFrontEndNavCaching: true,
  cacheStartUrl: false,
  dynamicStartUrl: false,
  extendDefaultRuntimeCaching: false,
  workboxOptions: {
    cacheId: "regknots-v8",
    disableDevLogs: true,
    // Targeted exclude — only block the manifests and server bundles that
    // would otherwise bloat the precache with 404-prone entries. CRITICALLY
    // this does NOT exclude `/_next/static/chunks/**`, so page-specific JS
    // chunks (app/reference/page-*.js, app/login/page-*.js, etc.) ARE
    // auto-precached, fixing the offline nav bug where chunks errored with
    // net::ERR_INTERNET_DISCONNECTED on first offline visit.
    exclude: [
      /middleware-manifest\.json$/,
      /build-manifest\.json$/,
      /react-loadable-manifest\.json$/,
      /server\//,
      /api\//,
    ],
    // Additional static routes we want guaranteed-cached on SW install.
    additionalManifestEntries: [
      { url: "/offline.html", revision: "offline-v2" },
      { url: "/reference", revision: "reference-v2" },
    ],
    runtimeCaching: [
      // ── 1. Never cache /api/* — always hit the network ────────────────
      // Covers /api/auth, /api/chat, /api/vessels, /api/billing, /api/admin,
      // and every other route. Auth and mutating writes must be authoritative.
      {
        urlPattern: /\/api\//i,
        handler: "NetworkOnly",
      },

      // ── 2. CacheFirst for every hashed Next.js static asset ──────────
      // Chunks/css/media are content-hashed so they're safe to keep forever.
      // This rule is the runtime fallback for any chunk that slipped past
      // the build-time precache (e.g. lazy-loaded code splits).
      {
        urlPattern: /\/_next\/static\/.*/i,
        handler: "CacheFirst",
        options: {
          cacheName: "next-static-assets",
          expiration: {
            maxEntries: 512,
            maxAgeSeconds: 30 * 24 * 60 * 60, // 30 days
          },
          cacheableResponse: {
            statuses: [0, 200],
          },
        },
      },

      // ── 3. SWR for Next.js RSC data requests ──────────────────────────
      {
        urlPattern: /\/_next\/data\/.*/i,
        handler: "StaleWhileRevalidate",
        options: {
          cacheName: "next-data",
          expiration: {
            maxEntries: 64,
            maxAgeSeconds: 24 * 60 * 60, // 24h
          },
        },
      },

      // ── 4. SWR for in-app page routes ─────────────────────────────────
      // Matches the authenticated app shell pages. Cached HTML shells load
      // instantly offline; background revalidation keeps them fresh.
      {
        urlPattern: /^https:\/\/regknots\.com\/(chat|history|account|reference|certificates|admin|onboarding).*/i,
        handler: "StaleWhileRevalidate",
        options: {
          cacheName: "app-pages",
          expiration: {
            maxEntries: 32,
            maxAgeSeconds: 24 * 60 * 60,
          },
        },
      },

      // ── 5. Catch-all: other same-origin GETs (fonts, images, root /) ──
      // Keeps the offline safety net wide without resorting to NetworkFirst,
      // which would timeout and fail on truly offline navigations.
      {
        urlPattern: ({ url, sameOrigin }: { url: URL; sameOrigin: boolean }) =>
          sameOrigin && !url.pathname.startsWith("/api/"),
        handler: "StaleWhileRevalidate",
        options: {
          cacheName: "app-shell",
          expiration: {
            maxEntries: 64,
            maxAgeSeconds: 7 * 24 * 60 * 60,
          },
        },
      },
    ],
  },
})(nextConfig);

export default process.env.NEXT_PUBLIC_SENTRY_DSN
  ? withSentryConfig(pwaConfig, { silent: true })
  : pwaConfig;
