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
    cacheId: "regknots-v3",
    disableDevLogs: true,
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
    ],
  },
})(nextConfig);

export default process.env.NEXT_PUBLIC_SENTRY_DSN
  ? withSentryConfig(pwaConfig, { silent: true })
  : pwaConfig;
