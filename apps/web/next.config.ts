import type { NextConfig } from "next";
import { withSentryConfig } from "@sentry/nextjs";
import withPWA from "@ducanh2912/next-pwa";

const nextConfig: NextConfig = {};

const pwaConfig = withPWA({
  dest: "public",
  // Register SW manually after hydration to avoid MessagePort
  // interference during React hydration (React error #418).
  register: false,
  cacheStartUrl: false,
  reloadOnOnline: false,
  workboxOptions: {
    // D6.23e — bumped from v12 → v13 to force cleanupOutdatedCaches()
    // to delete stale start-url caches in any clients that still load
    // the old SW before Providers.tsx unregisters it.
    cacheId: "regknots-v13",
    skipWaiting: true,
    cleanupOutdatedCaches: true,
    // Exclude everything from precache — SW does zero caching
    exclude: [/./],
    // No runtimeCaching rules — SW is a no-op
    runtimeCaching: [],
  },
})(nextConfig);

export default process.env.NEXT_PUBLIC_SENTRY_DSN
  ? withSentryConfig(pwaConfig, { silent: true })
  : pwaConfig;
