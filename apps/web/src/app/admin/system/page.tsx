'use client'

// 2026-09-29 — system health plus the Sentry issue list (which used to sit
// under the old "Content" tab).

import { useAdmin } from '../_lib/AdminContext'
import { fmtRelative } from '../_lib/format'
import { SystemTab } from '../_components/SystemPanel'
import { Empty, Page, Pill, Section, Skeleton } from '../_components/ui'

export default function AdminSystemPage() {
  const { sentry } = useAdmin()
  return (
    <Page title="System" description="Database, Redis, disk and API keys, and unresolved app errors from Sentry.">
      <SystemTab />

      <Section id="errors" title="App errors" description="Unresolved Sentry issues across the web app and API (up to 20).">
        {sentry === null ? <Skeleton /> : sentry.length === 0 ? (
          <Empty tone="good">No unresolved issues.</Empty>
        ) : (
          <div className="rounded-xl border border-white/8 overflow-x-auto">
            <table className="w-full text-left font-mono text-xs" style={{ minWidth: 640 }}>
              <thead>
                <tr className="bg-red-500/10 text-red-300">
                  {['Level', 'Project', 'Issue', 'Events', 'Last seen'].map((h) => <th key={h} className="px-3 py-2.5 font-medium">{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {sentry.map((issue, i) => (
                  <tr key={issue.id} className={`border-t border-white/5 ${i % 2 === 0 ? 'bg-[#111827]' : 'bg-[#0f1629]'}`}>
                    <td className="px-3 py-2"><Pill tone={issue.level === 'fatal' || issue.level === 'error' ? 'red' : 'amber'}>{issue.level}</Pill></td>
                    <td className="px-3 py-2 text-[#8b93ad] whitespace-nowrap">{issue.project}</td>
                    <td className="px-3 py-2 max-w-[520px] truncate">
                      <a href={issue.permalink || issue.link} target="_blank" rel="noopener noreferrer" title={issue.title}
                        className="text-[#f0ece4]/90 hover:text-[#2dd4bf]">{issue.title}</a>
                    </td>
                    <td className="px-3 py-2 text-[#f0ece4]/80 tabular-nums">{issue.count.toLocaleString()}</td>
                    <td className="px-3 py-2 text-[#8b93ad] whitespace-nowrap" title={new Date(issue.last_seen).toLocaleString()}>{fmtRelative(issue.last_seen)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
    </Page>
  )
}
