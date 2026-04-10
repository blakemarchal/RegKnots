import type { NextConfig } from "next";
import { withSentryConfig } from "@sentry/nextjs";
import withPWA from "@ducanh2912/next-pwa";

const nextConfig: NextConfig = {};

const pwaConfig = withPWA({
  dest: "public",
  disable: process.env.NODE_ENV === "development",
  register: true,
  extendDefaultRuntimeCaching: false,
  workboxOptions: {
    cacheId: "regknots-v10",
    skipWaiting: true,
    cleanupOutdatedCaches: true,
    // CRITICAL: exclude EVERYTHING from auto-precaching.
    // Next.js chunks are content-hashed and change on every build.
    // Precaching them causes 404s after each deploy.
    // Only /offline.html (via additionalManifestEntries) should be precached.
    exclude: [/./],
    // Only precache truly static assets that never change between deploys
    additionalManifestEntries: [
      { url: "/offline.html", revision: "offline-v1" },
    ],
    // Use NetworkFirst for everything by default —
    // this means online users always get fresh content,
    // and offline users get cached content as a fallback.
    runtimeCaching: [
      // API routes: always network, never cache
      {
        urlPattern: /^https:\/\/regknots\.com\/api\/.*/i,
        handler: "NetworkOnly",
      },
      // Next.js static assets (CSS, fonts, images, webmanifest):
      // These are safe to cache because they are content-hashed
      // BUT only cache non-JS assets — JS chunks must not be cached here
      {
        urlPattern: /\/_next\/static\/(css|media|fonts)\/.*/i,
        handler: "CacheFirst",
        options: {
          cacheName: "static-assets",
          expiration: {
            maxEntries: 128,
            maxAgeSeconds: 30 * 24 * 60 * 60,
          },
        },
      },
      // App pages: NetworkFirst with offline fallback
      // Online users always get fresh HTML.
      // Offline users get cached version if available.
      {
        urlPattern:
          /^https:\/\/regknots\.com\/(|chat|history|account|reference|certificates|admin|onboarding|pricing|landing|login|register).*/i,
        handler: "NetworkFirst",
        options: {
          cacheName: "app-pages",
          networkTimeoutSeconds: 5,
          expiration: {
            maxEntries: 32,
            maxAgeSeconds: 24 * 60 * 60,
          },
        },
      },
      // Next.js JS chunks: NetworkFirst — NEVER CacheFirst
      // Chunks change hash on every deploy. NetworkFirst means
      // online users get fresh chunks always.
      {
        urlPattern: /\/_next\/static\/chunks\/.*/i,
        handler: "NetworkFirst",
        options: {
          cacheName: "js-chunks",
          networkTimeoutSeconds: 5,
          expiration: {
            maxEntries: 256,
            maxAgeSeconds: 24 * 60 * 60, // 24h only
          },
        },
      },
    ],
  },
})(nextConfig);

export default process.env.NEXT_PUBLIC_SENTRY_DSN
  ? withSentryConfig(pwaConfig, { silent: true })
  : pwaConfig;
