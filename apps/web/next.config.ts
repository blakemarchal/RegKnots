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
  workboxOptions: {
    cacheId: "regknots-v6",
    disableDevLogs: true,
    // Eliminate the precache manifest entirely. Hashed chunk URLs in a stale
    // precache list cause bad-precaching-response 404s after every redeploy.
    // We rely solely on runtime caching (defaults extended below).
    exclude: [/.*/],
    // Explicit precache entries. The /reference quick-reference page is the
    // only HTML route precached on SW install — it's the offline safety net
    // so mariners can pull up rules even without a prior visit. Bump the
    // revision string when the page content changes to force re-precache.
    additionalManifestEntries: [
      { url: "/reference", revision: "reference-v1" },
    ],
    runtimeCaching: [
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
        // Chat messages and streaming must always hit the network — serving
        // stale regulation answers from cache would be dangerous.
        urlPattern: /\/api\/chat(\/.*)?$/,
        handler: "NetworkOnly",
      },
      {
        // Vessel profile CRUD — must be authoritative.
        urlPattern: /\/api\/vessels(\/.*)?$/,
        handler: "NetworkOnly",
      },
      {
        // Runtime backstop for /reference in case the precache install is
        // skipped. First visit caches it; offline visits are served from
        // cache while the background fetch revalidates.
        urlPattern: ({ url }: { url: URL }) => url.pathname === "/reference",
        handler: "StaleWhileRevalidate",
        options: {
          cacheName: "regknots-reference",
        },
      },
    ],
  },
})(nextConfig);

export default process.env.NEXT_PUBLIC_SENTRY_DSN
  ? withSentryConfig(pwaConfig, { silent: true })
  : pwaConfig;
