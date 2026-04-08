'use client'

import { useState } from 'react'
import Link from 'next/link'
import { CompassRose } from '@/components/CompassRose'

const PLAIN_TEXT = `Ship Network Whitelisting Request — RegKnot Maritime Compliance Tool

If RegKnot is blocked on your vessel's Wi-Fi, forward this information to your IT department or network administrator.

──────────────────────────────────────

DOMAIN TO WHITELIST

  Domain:    regknots.com
  IP:        68.183.130.3
  Port:      443 (HTTPS only)
  Protocol:  TLS 1.2 / TLS 1.3
  Type:      Web application — no downloads, no software installation

──────────────────────────────────────

WHAT IS REGKNOT?

RegKnot is a maritime regulatory compliance reference tool used by U.S. commercial vessel officers and engineers. It provides instant lookup of U.S. Code of Federal Regulations (Titles 33, 46, 49), COLREGs, SOLAS 2024 + amendments, STCW 2017 + amendments, the ISM Code, and USCG NVICs.

──────────────────────────────────────

SECURITY PROFILE

  HTTPS only (no HTTP)                 YES
  Valid TLS certificate (auto-renewed) YES
  HSTS enabled                         YES
  Content Security Policy headers      YES
  X-Frame-Options: DENY                YES
  No downloads or executable files     YES
  No browser extensions required       YES

──────────────────────────────────────

BANDWIDTH USAGE

Text-based application. Initial load ~500 KB, each query ~5-10 KB. Estimated monthly usage: 10-50 MB per user — comparable to basic email.

──────────────────────────────────────

If you use domain-based filtering, add:
  regknots.com
  *.regknots.com

If you use IP-based filtering, the current server IP is:
  68.183.130.3

──────────────────────────────────────

CONTACT

  support@regknots.com
  https://regknots.com/whitelisting`

const SECURITY_ITEMS = [
  { label: 'HTTPS only (no HTTP)', check: true },
  { label: 'Valid TLS certificate (auto-renewed)', check: true },
  { label: 'HSTS enabled', check: true },
  { label: 'Content Security Policy headers', check: true },
  { label: 'X-Frame-Options: DENY', check: true },
  { label: 'No downloads or executable files', check: true },
  { label: 'No browser extensions required', check: true },
]

export default function WhitelistingPage() {
  const [copied, setCopied] = useState(false)

  function copyToClipboard() {
    navigator.clipboard.writeText(PLAIN_TEXT).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2500)
    })
  }

  function printPage() {
    window.print()
  }

  function emailIT() {
    const subject = encodeURIComponent('Request to whitelist RegKnot maritime compliance tool')
    const body = encodeURIComponent(PLAIN_TEXT)
    window.open(`mailto:?subject=${subject}&body=${body}`, '_self')
  }

  return (
    <>
      {/* Print stylesheet */}
      <style>{`
        @media print {
          body { background: white !important; color: black !important; }
          .no-print { display: none !important; }
          .print-only { display: block !important; }
          .print-white { background: white !important; color: black !important; border-color: #ddd !important; }
          .print-white * { color: black !important; }
          .print-white .print-teal { color: #0d9488 !important; }
        }
      `}</style>

      <div className="min-h-screen bg-[#0a0e1a] print-white">
        {/* Nav */}
        <nav className="no-print flex items-center justify-between px-5 md:px-10 py-4
          bg-[#0a0e1a]/80 backdrop-blur-md border-b border-white/5">
          <Link href="/landing" className="flex items-center gap-2">
            <CompassRose className="w-5 h-5 text-[#2dd4bf]" />
            <span className="font-display text-xl font-bold text-[#f0ece4] tracking-widest uppercase">
              RegKnot
            </span>
          </Link>
          <div className="flex items-center gap-3">
            <Link href="/login"
              className="font-mono text-sm text-[#6b7594] hover:text-[#f0ece4] transition-colors">
              Sign In
            </Link>
            <Link href="/register"
              className="font-mono text-sm font-bold text-[#0a0e1a] bg-[#2dd4bf]
                hover:brightness-110 transition-[filter] rounded-lg px-4 py-1.5">
              Get Access
            </Link>
          </div>
        </nav>

        {/* Content */}
        <main className="max-w-2xl mx-auto px-5 py-12 md:py-16">

          {/* Header */}
          <div className="mb-10">
            <div className="flex items-center gap-3 mb-4">
              <CompassRose className="w-7 h-7 text-[#2dd4bf] print-teal flex-shrink-0" />
              <h1 className="font-display text-3xl md:text-4xl font-black text-[#f0ece4] tracking-tight leading-tight">
                Ship Network Whitelisting Request
              </h1>
            </div>
            <p className="font-mono text-sm text-[#6b7594] leading-relaxed">
              If RegKnot is blocked on your vessel&apos;s Wi-Fi, forward this information to your IT department.
            </p>
          </div>

          {/* Whitelisting details */}
          <section className="bg-[#111827] border border-white/8 rounded-xl p-5 md:p-6 mb-6 print-white">
            <p className="font-display text-lg font-bold text-[#2dd4bf] print-teal tracking-wide mb-4">
              Domain to Whitelist
            </p>
            <div className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2">
              <span className="font-mono text-xs text-[#6b7594] uppercase tracking-wider">Domain</span>
              <span className="font-mono text-sm text-[#f0ece4] font-bold">regknots.com</span>

              <span className="font-mono text-xs text-[#6b7594] uppercase tracking-wider">IP Address</span>
              <span className="font-mono text-sm text-[#f0ece4]">68.183.130.3</span>

              <span className="font-mono text-xs text-[#6b7594] uppercase tracking-wider">Port</span>
              <span className="font-mono text-sm text-[#f0ece4]">443 (HTTPS only)</span>

              <span className="font-mono text-xs text-[#6b7594] uppercase tracking-wider">Protocol</span>
              <span className="font-mono text-sm text-[#f0ece4]">TLS 1.2 / TLS 1.3</span>

              <span className="font-mono text-xs text-[#6b7594] uppercase tracking-wider">Type</span>
              <span className="font-mono text-sm text-[#f0ece4]">Web application — no downloads, no software installation</span>
            </div>
          </section>

          {/* What is RegKnot */}
          <section className="bg-[#111827] border border-white/8 rounded-xl p-5 md:p-6 mb-6 print-white">
            <p className="font-display text-lg font-bold text-[#2dd4bf] print-teal tracking-wide mb-3">
              What is RegKnot?
            </p>
            <p className="font-mono text-sm text-[#f0ece4]/80 leading-relaxed">
              RegKnot is a maritime regulatory compliance reference tool used by U.S. commercial vessel officers
              and engineers. It provides instant lookup of U.S. Code of Federal Regulations (Titles 33, 46, 49),
              COLREGs, SOLAS 2024 + amendments, STCW 2017 + amendments, the ISM Code, and USCG NVICs.
            </p>
          </section>

          {/* Security profile */}
          <section className="bg-[#111827] border border-white/8 rounded-xl p-5 md:p-6 mb-6 print-white">
            <p className="font-display text-lg font-bold text-[#2dd4bf] print-teal tracking-wide mb-4">
              Security Profile
            </p>
            <div className="flex flex-col gap-2">
              {SECURITY_ITEMS.map((item) => (
                <div key={item.label} className="flex items-center gap-3">
                  <span className="text-[#2dd4bf] print-teal flex-shrink-0 text-sm" aria-hidden="true">
                    {item.check ? '\u2713' : '\u2717'}
                  </span>
                  <span className="font-mono text-sm text-[#f0ece4]/80">{item.label}</span>
                </div>
              ))}
            </div>
          </section>

          {/* Bandwidth */}
          <section className="bg-[#111827] border border-white/8 rounded-xl p-5 md:p-6 mb-6 print-white">
            <p className="font-display text-lg font-bold text-[#2dd4bf] print-teal tracking-wide mb-3">
              Bandwidth Usage
            </p>
            <p className="font-mono text-sm text-[#f0ece4]/80 leading-relaxed">
              Text-based application. Initial load ~500 KB, each query ~5-10 KB.
              Estimated monthly usage: 10-50 MB per user — comparable to basic email.
            </p>
          </section>

          {/* Fleet subdomain note */}
          <section className="bg-[#111827] border border-white/8 rounded-xl p-5 md:p-6 mb-6 print-white">
            <p className="font-display text-lg font-bold text-[#2dd4bf] print-teal tracking-wide mb-3">
              Fleet Operators
            </p>
            <p className="font-mono text-sm text-[#f0ece4]/80 leading-relaxed">
              Your company can request a custom subdomain (e.g.{' '}
              <span className="text-[#f0ece4] font-bold">yourcompany.regknots.com</span>) for
              easier fleet-wide whitelisting. Contact{' '}
              <a href="mailto:support@regknots.com" className="text-[#2dd4bf] print-teal hover:underline">
                support@regknots.com
              </a>{' '}
              to set up your subdomain.
            </p>
          </section>

          {/* Contact */}
          <section className="bg-[#111827] border border-white/8 rounded-xl p-5 md:p-6 mb-10 print-white">
            <p className="font-display text-lg font-bold text-[#2dd4bf] print-teal tracking-wide mb-3">
              Contact
            </p>
            <p className="font-mono text-sm text-[#f0ece4]/80">
              <a href="mailto:support@regknots.com" className="text-[#2dd4bf] print-teal hover:underline">
                support@regknots.com
              </a>
            </p>
          </section>

          {/* Action buttons */}
          <div className="no-print flex flex-col sm:flex-row items-stretch sm:items-center gap-3">
            <button
              onClick={copyToClipboard}
              className="flex-1 font-mono text-sm font-bold text-[#0a0e1a] bg-[#2dd4bf]
                hover:brightness-110 rounded-xl py-3 transition-[filter] duration-150"
            >
              {copied ? 'Copied to clipboard \u2713' : 'Copy to clipboard'}
            </button>
            <button
              onClick={printPage}
              className="flex-1 font-mono text-sm font-bold text-[#2dd4bf]
                border border-[#2dd4bf]/40 hover:bg-[#2dd4bf]/10
                rounded-xl py-3 transition-colors duration-150"
            >
              Print / Save PDF
            </button>
            <button
              onClick={emailIT}
              className="flex-1 font-mono text-sm font-bold text-[#f0ece4]/70
                border border-white/15 hover:border-white/30 hover:text-[#f0ece4]
                rounded-xl py-3 transition-colors duration-150"
            >
              Email to IT department
            </button>
          </div>

          {/* Footer note */}
          <p className="no-print font-mono text-[10px] text-[#6b7594] text-center mt-8">
            RegKnot is a navigation aid only and does not constitute legal advice.
          </p>
        </main>
      </div>
    </>
  )
}
