export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    const Sentry = await import("@sentry/nextjs");
    const { scrubSentryBreadcrumb, scrubSentryEvent } = await import("./lib/sentryScrub");

    if (process.env.NEXT_PUBLIC_SENTRY_DSN) {
      Sentry.init({
        dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
        tracesSampleRate: 0.1,
        // 2026-09-26 — events carried no environment, so dev and prod errors mixed
        // (open since the May audit). NEXT_PUBLIC_* is inlined at build time.
        environment: process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT || process.env.NODE_ENV,
        // 2026-10-16 security review: no tokens, bodies or emails (lib/sentryScrub.ts).
        sendDefaultPii: false,
        beforeSend: (event) => scrubSentryEvent(event),
        beforeBreadcrumb: (breadcrumb) => scrubSentryBreadcrumb(breadcrumb),
      });
    }
  }
}
