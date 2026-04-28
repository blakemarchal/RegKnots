import type { NextConfig } from "next";
import { withSentryConfig } from "@sentry/nextjs";
import withPWA from "@ducanh2912/next-pwa";

const nextConfig: NextConfig = {};

// Sprint D6.23f — DISABLE next-pwa entirely. The generated workbox SW
// was caching `/` content under a NetworkFirst start-url cache, and
// existing PWA users kept seeing the stale page even after we set
// runtimeCaching: []. We're shipping a custom self-destructing sw.js
// in /public/sw.js (committed by hand) that wipes caches and
// unregisters itself — the browser fetches /sw.js direct on each
// navigation (SW spec), bypassing the existing SW's fetch handler,
// so the kill SW WILL install + activate even on stuck PWA clients.
//
// This also stops next-pwa from regenerating sw.js during build, so
// the static kill SW survives every future deploy.
const pwaConfig = withPWA({
  dest: "public",
  disable: true,
  register: false,
  cacheStartUrl: false,
  reloadOnOnline: false,
  workboxOptions: {
    cacheId: "regknots-kill",
    skipWaiting: true,
    cleanupOutdatedCaches: true,
    exclude: [/./],
    runtimeCaching: [],
  },
})(nextConfig);

export default process.env.NEXT_PUBLIC_SENTRY_DSN
  ? withSentryConfig(pwaConfig, { silent: true })
  : pwaConfig;
