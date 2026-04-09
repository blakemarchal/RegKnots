'use client'

import { useState } from 'react'

interface Props {
  title: string
  defaultOpen?: boolean
  children: React.ReactNode
}

/**
 * Simple collapsible section used by the static /reference page. Kept as a
 * tiny client island so the surrounding page can remain a pure server
 * component suitable for build-time static generation.
 */
export function ReferenceAccordion({ title, defaultOpen = false, children }: Props) {
  const [open, setOpen] = useState(defaultOpen)

  return (
    <section className="rounded-2xl border border-white/8 bg-[#111827] overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen(v => !v)}
        aria-expanded={open}
        className="w-full flex items-center justify-between gap-4 px-5 py-4
          text-left hover:bg-white/5 transition-colors duration-150"
      >
        <h2 className="font-display text-lg font-bold text-[#f0ece4] tracking-wide">
          {title}
        </h2>
        <span
          className={`text-[#2dd4bf] text-lg transition-transform duration-200 flex-shrink-0
            ${open ? 'rotate-90' : ''}`}
          aria-hidden="true"
        >
          &#9656;
        </span>
      </button>
      {open && (
        <div className="px-5 pb-5 pt-1 border-t border-white/5">
          {children}
        </div>
      )}
    </section>
  )
}
