'use client'

/**
 * IndexedDB-backed offline cache for conversations and vessels.
 *
 * - DB: regknots-offline, version 1
 * - Stores: 'conversations' (keyPath 'id'), 'vessels' (keyPath 'id')
 * - Conversations are capped to the 10 most recent by updated_at.
 *
 * All functions resolve silently on unsupported environments (SSR, private
 * mode without IDB). Callers should still wrap writes in try/catch so a
 * cache failure never breaks the main app flow.
 */

const DB_NAME = 'regknots-offline'
const DB_VERSION = 1
const STORE_CONVERSATIONS = 'conversations'
const STORE_VESSELS = 'vessels'
const MAX_CONVERSATIONS = 10

export interface CachedConversation {
  id: string
  title: string | null
  updated_at: string
  messages: Array<{
    id: string
    role: 'user' | 'assistant'
    content: string
    created_at: string
  }>
}

export interface CachedVessel {
  id: string
  name: string
}

function isBrowserIDBAvailable(): boolean {
  return typeof window !== 'undefined' && typeof indexedDB !== 'undefined'
}

export async function openDB(): Promise<IDBDatabase> {
  if (!isBrowserIDBAvailable()) {
    throw new Error('IndexedDB not available')
  }
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION)
    req.onupgradeneeded = () => {
      const db = req.result
      if (!db.objectStoreNames.contains(STORE_CONVERSATIONS)) {
        db.createObjectStore(STORE_CONVERSATIONS, { keyPath: 'id' })
      }
      if (!db.objectStoreNames.contains(STORE_VESSELS)) {
        db.createObjectStore(STORE_VESSELS, { keyPath: 'id' })
      }
    }
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error ?? new Error('Failed to open IndexedDB'))
  })
}

function promisifyTx(tx: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error ?? new Error('IDB transaction failed'))
    tx.onabort = () => reject(tx.error ?? new Error('IDB transaction aborted'))
  })
}

export async function cacheConversations(
  conversations: CachedConversation[],
): Promise<void> {
  if (!isBrowserIDBAvailable()) return
  const db = await openDB()
  try {
    const sorted = [...conversations].sort((a, b) =>
      b.updated_at.localeCompare(a.updated_at),
    )
    const trimmed = sorted.slice(0, MAX_CONVERSATIONS)

    const tx = db.transaction(STORE_CONVERSATIONS, 'readwrite')
    const store = tx.objectStore(STORE_CONVERSATIONS)
    store.clear()
    for (const conv of trimmed) {
      store.put(conv)
    }
    await promisifyTx(tx)
  } finally {
    db.close()
  }
}

export async function getCachedConversations(): Promise<CachedConversation[]> {
  if (!isBrowserIDBAvailable()) return []
  const db = await openDB()
  try {
    return await new Promise<CachedConversation[]>((resolve, reject) => {
      const tx = db.transaction(STORE_CONVERSATIONS, 'readonly')
      const store = tx.objectStore(STORE_CONVERSATIONS)
      const req = store.getAll()
      req.onsuccess = () => {
        const rows = (req.result ?? []) as CachedConversation[]
        rows.sort((a, b) => b.updated_at.localeCompare(a.updated_at))
        resolve(rows)
      }
      req.onerror = () => reject(req.error ?? new Error('Failed to read conversations'))
    })
  } finally {
    db.close()
  }
}

export async function cacheVessels(vessels: CachedVessel[]): Promise<void> {
  if (!isBrowserIDBAvailable()) return
  const db = await openDB()
  try {
    const tx = db.transaction(STORE_VESSELS, 'readwrite')
    const store = tx.objectStore(STORE_VESSELS)
    store.clear()
    for (const v of vessels) {
      store.put(v)
    }
    await promisifyTx(tx)
  } finally {
    db.close()
  }
}

export async function getCachedVessels(): Promise<CachedVessel[]> {
  if (!isBrowserIDBAvailable()) return []
  const db = await openDB()
  try {
    return await new Promise<CachedVessel[]>((resolve, reject) => {
      const tx = db.transaction(STORE_VESSELS, 'readonly')
      const store = tx.objectStore(STORE_VESSELS)
      const req = store.getAll()
      req.onsuccess = () => resolve((req.result ?? []) as CachedVessel[])
      req.onerror = () => reject(req.error ?? new Error('Failed to read vessels'))
    })
  } finally {
    db.close()
  }
}

export async function clearCache(): Promise<void> {
  if (!isBrowserIDBAvailable()) return
  const db = await openDB()
  try {
    const tx = db.transaction([STORE_CONVERSATIONS, STORE_VESSELS], 'readwrite')
    tx.objectStore(STORE_CONVERSATIONS).clear()
    tx.objectStore(STORE_VESSELS).clear()
    await promisifyTx(tx)
  } finally {
    db.close()
  }
}
