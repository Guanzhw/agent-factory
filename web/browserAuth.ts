import type { User } from './models.js';

/** Browser credentials remain in the server cookie; CSRF stays in memory only. */
export class BrowserAuthError extends Error {
  constructor(public readonly status: number) { super(status === 401 ? '登录会话已过期，请重新登录。' : '身份认证暂时不可用，请重新尝试。'); }
}
let epoch = 0;
let csrf: string | undefined;
let pending: Promise<string> | undefined;
const listeners = new Set<() => void>();
export const authEpoch = () => epoch;
export function assertAuthEpoch(expected: number) {
  if (expected !== epoch) throw new DOMException('Session changed', 'AbortError');
}
export function clearBrowserSession(notify = false) {
  epoch++; csrf = undefined; pending = undefined;
  if (notify) for (const listener of listeners) listener();
}
export function subscribeSessionExpiry(listener: () => void) {
  listeners.add(listener); return () => { listeners.delete(listener); };
}
export function expireBrowserSession() { clearBrowserSession(true); }
async function authJson(path: string, method = 'GET', signal?: AbortSignal, body: object = {}) {
  const started = epoch;
  let response: Response;
  try {
    response = await fetch(path, { method, credentials: 'same-origin', cache: 'no-store', redirect: 'error', signal,
      ...(method === 'POST' ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {}) });
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') throw error;
    throw new BrowserAuthError(0);
  }
  assertAuthEpoch(started);
  if (!response.ok) { if (response.status === 401) expireBrowserSession(); throw new BrowserAuthError(response.status); }
  let value: unknown;
  try { value = await response.json(); } catch { throw new BrowserAuthError(0); }
  assertAuthEpoch(started);
  return value;
}
export async function readBrowserSession(signal?: AbortSignal): Promise<User | null> {
  const session = await authJson('/api/factory/auth/session', 'GET', signal) as {
    authenticated?: boolean; csrfToken?: string; user?: User;
  } | null;
  if (session?.authenticated === false) { csrf = undefined; return null; }
  if (session?.authenticated !== true || !session.user?.id || typeof session.csrfToken !== 'string'
      || !/^[\x21-\x7e]{16,512}$/.test(session.csrfToken)) throw new BrowserAuthError(0);
  csrf = session.csrfToken;
  return session.user;
}
export async function browserCsrf(): Promise<string> {
  if (csrf) return csrf;
  if (!pending) {
    const work = readBrowserSession().then(user => {
      if (!user || !csrf) { expireBrowserSession(); throw new BrowserAuthError(401); }
      return csrf;
    });
    pending = work;
    void work.finally(() => { if (pending === work) pending = undefined; }).catch(() => {});
  }
  return pending;
}
export async function startLocalLogin(username: string, password: string): Promise<void> {
  clearBrowserSession();
  const value = await authJson('/api/factory/auth/local-login', 'POST', undefined, { username, password });
  if (!value || typeof value !== 'object' || (value as { authenticated?: unknown }).authenticated !== true) throw new BrowserAuthError(0);
}
