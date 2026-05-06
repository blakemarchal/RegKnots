'use client'

// Sprint D6.62 hotfix — robust "send email" button.
//
// `mailto:` URLs are unreliable. On Windows without a registered mail
// handler, on locked-down corporate machines, in some browsers (Chrome
// Incognito, Firefox container tabs) the click does nothing — the user
// just sees a non-event and assumes the app is broken.
//
// This component opens a modal instead. The modal:
//   - Shows the formatted message subject + body
//   - Has copy-to-clipboard buttons for each (and for the recipient)
//   - Has direct webmail compose links (Gmail, Outlook, Yahoo) that
//     pre-fill via URL parameters — works in any browser
//   - Has a fallback "Try mail app" button that does fire mailto: for
//     users whose desktop client IS configured
//
// Usable in two modes:
//   - "compose" — full message with subject/body/recipient (sea-service letter)
//   - "address" — just an email address for direct contact (landing footer)

import { useState, useEffect } from 'react'

type Mode = 'compose' | 'address'

interface ComposeProps {
  mode: 'compose'
  subject: string
  body: string
  recipient?: string  // optional; user usually fills this in their own client
  // Display
  buttonClassName?: string
  buttonChildren: React.ReactNode
}

interface AddressProps {
  mode: 'address'
  recipient: string
  // Suggested compose text (optional — for "support@" style links).
  defaultSubject?: string
  defaultBody?: string
  buttonClassName?: string
  buttonChildren: React.ReactNode
}

type Props = ComposeProps | AddressProps


function gmailUrl(to: string, subject: string, body: string): string {
  // Gmail compose URL — opens a new mail in any logged-in Gmail tab.
  const params = new URLSearchParams({
    view: 'cm',
    fs: '1',
    to,
    su: subject,
    body,
  })
  return `https://mail.google.com/mail/?${params.toString()}`
}

function outlookUrl(to: string, subject: string, body: string): string {
  const params = new URLSearchParams({ to, subject, body })
  return `https://outlook.live.com/mail/0/deeplink/compose?${params.toString()}`
}

function yahooUrl(to: string, subject: string, body: string): string {
  const params = new URLSearchParams({ to, subject, body })
  return `https://compose.mail.yahoo.com/?${params.toString()}`
}

function mailtoUrl(to: string, subject: string, body: string): string {
  const recipient = encodeURIComponent(to)
  const sub = encodeURIComponent(subject)
  const b = encodeURIComponent(body)
  return `mailto:${recipient}?subject=${sub}&body=${b}`
}


export function EmailComposeButton(props: Props) {
  const [open, setOpen] = useState(false)
  const [copied, setCopied] = useState<'recipient' | 'subject' | 'body' | 'all' | null>(null)

  const mode: Mode = props.mode
  const recipient = props.recipient || ''
  const subject =
    props.mode === 'compose' ? props.subject :
    (props.defaultSubject ?? '')
  const body =
    props.mode === 'compose' ? props.body :
    (props.defaultBody ?? '')

  useEffect(() => {
    if (!copied) return
    const t = setTimeout(() => setCopied(null), 1500)
    return () => clearTimeout(t)
  }, [copied])

  async function copy(text: string, which: typeof copied) {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(which)
    } catch { /* clipboard API may be blocked; just no-op */ }
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={props.buttonClassName}
      >
        {props.buttonChildren}
      </button>

      {open && (
        <div className="fixed inset-0 z-[60] flex items-end md:items-center justify-center
          bg-[#0a0e1a]/85 backdrop-blur-sm p-0 md:p-4"
          onClick={() => setOpen(false)}
        >
          <div
            className="w-full max-w-lg bg-[#111827] border border-white/10
              rounded-t-2xl md:rounded-2xl p-5 md:p-6 max-h-[90vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-display font-bold text-[#f0ece4] text-lg">
                {mode === 'address' ? 'Email us' : 'Send this email'}
              </h3>
              <button
                onClick={() => setOpen(false)}
                className="text-[#6b7594] hover:text-[#f0ece4] text-xl leading-none"
                aria-label="Close"
              >
                ×
              </button>
            </div>

            {/* Recipient (always shown if present) */}
            {recipient && (
              <div className="mb-3">
                <label className="block font-mono text-[10px] text-[#6b7594] uppercase tracking-wider mb-1">
                  To
                </label>
                <div className="flex items-center gap-2">
                  <input
                    readOnly
                    value={recipient}
                    className="flex-1 bg-[#0a0e1a] border border-white/10 rounded
                      px-2 py-2 font-mono text-sm text-[#f0ece4] truncate"
                    onClick={(e) => (e.target as HTMLInputElement).select()}
                  />
                  <button
                    type="button"
                    onClick={() => void copy(recipient, 'recipient')}
                    className="font-mono text-xs px-3 py-2 rounded
                      bg-[#2dd4bf]/10 border border-[#2dd4bf]/30 text-[#2dd4bf]
                      hover:bg-[#2dd4bf]/15"
                  >
                    {copied === 'recipient' ? '✓' : 'Copy'}
                  </button>
                </div>
              </div>
            )}

            {/* Subject */}
            {mode === 'compose' && (
              <div className="mb-3">
                <label className="block font-mono text-[10px] text-[#6b7594] uppercase tracking-wider mb-1">
                  Subject
                </label>
                <div className="flex items-center gap-2">
                  <input
                    readOnly
                    value={subject}
                    className="flex-1 bg-[#0a0e1a] border border-white/10 rounded
                      px-2 py-2 font-mono text-sm text-[#f0ece4] truncate"
                  />
                  <button
                    type="button"
                    onClick={() => void copy(subject, 'subject')}
                    className="font-mono text-xs px-3 py-2 rounded
                      bg-[#2dd4bf]/10 border border-[#2dd4bf]/30 text-[#2dd4bf]
                      hover:bg-[#2dd4bf]/15"
                  >
                    {copied === 'subject' ? '✓' : 'Copy'}
                  </button>
                </div>
              </div>
            )}

            {/* Body */}
            {mode === 'compose' && (
              <div className="mb-4">
                <label className="block font-mono text-[10px] text-[#6b7594] uppercase tracking-wider mb-1">
                  Message
                </label>
                <textarea
                  readOnly
                  value={body}
                  rows={8}
                  className="w-full bg-[#0a0e1a] border border-white/10 rounded
                    px-2 py-2 font-mono text-xs text-[#f0ece4] resize-none"
                />
                <button
                  type="button"
                  onClick={() => void copy(body, 'body')}
                  className="mt-2 font-mono text-xs px-3 py-1.5 rounded
                    bg-[#2dd4bf]/10 border border-[#2dd4bf]/30 text-[#2dd4bf]
                    hover:bg-[#2dd4bf]/15"
                >
                  {copied === 'body' ? '✓ Copied' : 'Copy message'}
                </button>
              </div>
            )}

            {/* Webmail compose buttons */}
            <div className="border-t border-white/8 pt-4">
              <p className="font-mono text-[10px] text-[#6b7594] uppercase tracking-wider mb-2">
                Or open in
              </p>
              <div className="flex flex-wrap gap-2">
                <a
                  href={gmailUrl(recipient, subject, body)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="font-mono text-xs px-3 py-2 rounded
                    bg-white/5 border border-white/10 text-[#f0ece4]
                    hover:bg-white/10"
                >
                  Gmail
                </a>
                <a
                  href={outlookUrl(recipient, subject, body)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="font-mono text-xs px-3 py-2 rounded
                    bg-white/5 border border-white/10 text-[#f0ece4]
                    hover:bg-white/10"
                >
                  Outlook
                </a>
                <a
                  href={yahooUrl(recipient, subject, body)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="font-mono text-xs px-3 py-2 rounded
                    bg-white/5 border border-white/10 text-[#f0ece4]
                    hover:bg-white/10"
                >
                  Yahoo
                </a>
                <a
                  href={mailtoUrl(recipient, subject, body)}
                  className="font-mono text-xs px-3 py-2 rounded
                    bg-white/5 border border-white/10 text-[#f0ece4]
                    hover:bg-white/10"
                  title="Use your default mail app — only works if one is configured"
                >
                  Mail app
                </a>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
