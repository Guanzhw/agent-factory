import type { SessionAction, SessionLimits } from './researchSessionsClient.js';

export interface SessionDraft { title: string; goal: string; boundaries: string; modelConnectionRef: string; limits: SessionLimits }
export interface PendingSessionRequest { requestId: string; action: SessionAction; sessionId: string | null }
const prefix = (owner: string) => `factory:research-sessions:${encodeURIComponent(owner)}:`;
export const draftKey = (owner: string, sessionId = '') => `${prefix(owner)}draft:${sessionId || 'new'}`;
export const requestKey = (owner: string) => `${prefix(owner)}requests`;
export function readStored<T>(key: string, fallback: T): T {
  try { const value = sessionStorage.getItem(key); return value ? JSON.parse(value) as T : fallback; } catch { return fallback; }
}
export function writeStored(key: string, value: unknown): boolean {
  try { sessionStorage.setItem(key, JSON.stringify(value)); return true; } catch { return false; }
}
export function removeStored(key: string) { try { sessionStorage.removeItem(key); } catch { /* Existing input stays visible. */ } }
/** Clear private text on logout; retain owner-scoped opaque pointers for read-only recovery. */
export function clearSessionDrafts(owner: string) {
  try {
    const keys = Array.from({ length: sessionStorage.length }, (_, index) => sessionStorage.key(index));
    for (const key of keys) if (key?.startsWith(`${prefix(owner)}draft:`)) sessionStorage.removeItem(key);
  } catch { /* Storage can be disabled by the browser. */ }
}
