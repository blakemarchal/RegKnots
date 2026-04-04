import Link from 'next/link'

export const metadata = {
  title: 'Terms of Service — RegKnots',
}

export default function TermsPage() {
  return (
    <div className="min-h-dvh bg-[#0a0e1a] text-[#f0ece4]/90">
      <header className="border-b border-white/8 px-5 md:px-10 py-4">
        <div className="max-w-3xl mx-auto flex items-center justify-between">
          <Link href="/landing" className="font-display text-xl font-bold text-[#f0ece4] tracking-wide">
            RegKnots
          </Link>
          <Link href="/landing" className="font-mono text-xs text-[#6b7594] hover:text-[#f0ece4]/80 transition-colors">
            Back
          </Link>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-5 md:px-10 py-10">
        <h1 className="font-display text-3xl font-bold text-[#f0ece4] tracking-wide mb-2">
          Terms of Service
        </h1>
        <p className="font-mono text-xs text-[#6b7594] mb-8">Effective: April 3, 2026</p>

        <div className="prose-custom space-y-6 font-mono text-sm leading-relaxed text-[#f0ece4]/75">
          <section>
            <h2 className="font-display text-lg font-bold text-[#2dd4bf] mb-2">1. Acceptance</h2>
            <p>
              By accessing or using RegKnots (&quot;the Service&quot;), you agree to these Terms of Service.
              If you do not agree, do not use the Service. We may update these terms at any time;
              continued use constitutes acceptance.
            </p>
          </section>

          <section>
            <h2 className="font-display text-lg font-bold text-[#2dd4bf] mb-2">2. Description of Service</h2>
            <p>
              RegKnots is an AI-powered maritime compliance assistant. It provides navigation
              assistance for U.S. Code of Federal Regulations (CFR) Title 46 and related maritime
              regulations. The Service is a <strong>navigation aid only</strong> — it does not
              constitute legal, regulatory, or professional advice.
            </p>
          </section>

          <section>
            <h2 className="font-display text-lg font-bold text-[#2dd4bf] mb-2">3. Accounts</h2>
            <p>
              You must provide a valid email address to create an account. You are responsible for
              maintaining the security of your credentials. You must not share your account or allow
              unauthorized access. We reserve the right to suspend or terminate accounts that violate
              these terms.
            </p>
          </section>

          <section>
            <h2 className="font-display text-lg font-bold text-[#2dd4bf] mb-2">4. Subscriptions &amp; Billing</h2>
            <p>
              Free tier accounts include a limited number of messages. Paid subscriptions are billed
              monthly through Stripe. You may cancel at any time; access continues through the end
              of your billing period. Refunds are handled on a case-by-case basis — contact
              support@regknots.com.
            </p>
          </section>

          <section>
            <h2 className="font-display text-lg font-bold text-[#2dd4bf] mb-2">5. Acceptable Use</h2>
            <p>You agree not to:</p>
            <ul className="list-disc list-inside mt-2 space-y-1">
              <li>Use the Service for any unlawful purpose</li>
              <li>Attempt to reverse-engineer, scrape, or extract the underlying models or data</li>
              <li>Abuse rate limits or circumvent access controls</li>
              <li>Redistribute regulation text in violation of applicable copyright</li>
            </ul>
          </section>

          <section>
            <h2 className="font-display text-lg font-bold text-[#2dd4bf] mb-2">6. Disclaimer of Warranties</h2>
            <p>
              The Service is provided &quot;AS IS&quot; and &quot;AS AVAILABLE.&quot; We make no warranties,
              express or implied, regarding accuracy, completeness, or fitness for a particular
              purpose. AI-generated responses may contain errors. Always verify regulatory
              information against official sources before making compliance decisions.
            </p>
          </section>

          <section>
            <h2 className="font-display text-lg font-bold text-[#2dd4bf] mb-2">7. Limitation of Liability</h2>
            <p>
              To the maximum extent permitted by law, RegKnots and its operators shall not be liable
              for any indirect, incidental, special, or consequential damages arising from your use
              of the Service. Our total liability shall not exceed the fees paid by you in the
              12 months preceding the claim.
            </p>
          </section>

          <section>
            <h2 className="font-display text-lg font-bold text-[#2dd4bf] mb-2">8. Intellectual Property</h2>
            <p>
              RegKnots owns all rights to the Service, its design, and its proprietary features.
              U.S. federal regulations (CFR) are public domain. Third-party regulation texts
              (e.g., SOLAS, IMO conventions) are subject to their respective copyright holders.
            </p>
          </section>

          <section>
            <h2 className="font-display text-lg font-bold text-[#2dd4bf] mb-2">9. Termination</h2>
            <p>
              We may suspend or terminate your access at any time, with or without cause. Upon
              termination, your right to use the Service ceases immediately. Sections 6, 7, and 8
              survive termination.
            </p>
          </section>

          <section>
            <h2 className="font-display text-lg font-bold text-[#2dd4bf] mb-2">10. Contact</h2>
            <p>
              Questions about these terms? Email us at{' '}
              <a href="mailto:support@regknots.com" className="text-[#2dd4bf] hover:underline">
                support@regknots.com
              </a>.
            </p>
          </section>
        </div>
      </main>
    </div>
  )
}
