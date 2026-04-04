"use client"
import * as Sentry from "@sentry/nextjs"
import { useEffect } from "react"

export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => { Sentry.captureException(error) }, [error])
  return (
    <html><body>
      <div style={{ padding: "2rem", fontFamily: "monospace", color: "#f0ece4", background: "#0a0e1a", minHeight: "100vh", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
        <h2 style={{ color: "#2dd4bf", marginBottom: "1rem" }}>Something went wrong</h2>
        <p style={{ color: "#6b7594", marginBottom: "1.5rem" }}>The error has been reported. Please try again.</p>
        <button onClick={reset} style={{ padding: "0.5rem 1.5rem", background: "#2dd4bf", color: "#0a0e1a", border: "none", borderRadius: "8px", cursor: "pointer", fontWeight: "bold" }}>Try again</button>
      </div>
    </body></html>
  )
}
