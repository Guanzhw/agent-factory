import type { SessionAction } from './researchSessionsClient.js';

export interface SessionDraft { repositoryPath?: string; projectId?: string; title: string; goal: string; boundaries: string; modelConnectionRef: string; reasoningEffort?: string }
export interface PendingSessionRequest { detached?: boolean; requestId: string; action: SessionAction; sessionId: string | null }
const prefix = (owner: string) => `factory:research-sessions:${encodeURIComponent(owner)}:`;
export const draftKey = (owner: string, sessionId = '') => `${prefix(owner)}draft:${sessionId || 'new'}`;
export const requestKey = (owner: string) => `${prefix(owner)}requests`;
const volatile = new Map<string, string | null>();
export function readStored<T>(key: string, fallback: T): T {
  try { const value = volatile.has(key) ? volatile.get(key) : sessionStorage.getItem(key); return value ? JSON.parse(value) as T : fallback; } catch { return fallback; }
}
export function writeStored(key: string, value: unknown): boolean {
  const serialized = JSON.stringify(value);
  try { sessionStorage.setItem(key, serialized); volatile.delete(key); return true; }
  catch { volatile.set(key, serialized); return false; }
}
export function removeStored(key: string) { try { sessionStorage.removeItem(key); volatile.delete(key); } catch { volatile.set(key, null); } }
/** Clear private text on logout; retain owner-scoped opaque pointers for read-only recovery. */
export function clearSessionDrafts(owner: string) {
  for (const key of volatile.keys()) if (key.startsWith(`${prefix(owner)}draft:`)) removeStored(key);
  try {
    const keys = Array.from({ length: sessionStorage.length }, (_, index) => sessionStorage.key(index));
    for (const key of keys) if (key?.startsWith(`${prefix(owner)}draft:`)) sessionStorage.removeItem(key);
  } catch { /* Storage can be disabled by the browser. */ }
}
