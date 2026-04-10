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
    cacheId: "regknots-v12",
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
