'use client'

import { useEffect, useRef } from 'react'
import type { Message } from '@/types/chat'
import { ChatMessage } from './ChatMessage'
import { TypingIndicator } from './TypingIndicator'
import { EmptyState } from './EmptyState'

interface Props {
  messages: Message[]
  loading: boolean
  onPrompt: (text: string) => void
  onCitationTap: (source: string, sectionNumber: string, sectionTitle: string) => void
}

export function ChatThread({ messages, loading, onPrompt, onCitationTap }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  return (
    <div className="flex flex-col min-h-full">
      {messages.length === 0 && !loading ? (
        <EmptyState onPrompt={onPrompt} />
      ) : (
        <div className="flex flex-col py-3 gap-0.5">
          {messages.map(msg => (
            <ChatMessage key={msg.id} message={msg} onCitationTap={onCitationTap} />
          ))}
          {loading && <TypingIndicator />}
        </div>
      )}
      <div ref={bottomRef} />
    </div>
  )
}
