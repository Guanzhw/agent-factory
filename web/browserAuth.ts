/** Browser credentials remain in the server cookie; CSRF stays in memory only. */
export interface BrowserAuthConfig { enabled: boolean; developmentOnly?: boolean; loginPath: '/api/factory/auth/login'; logoutPath: '/api/factory/auth/logout' }
export class BrowserAuthError extends Error {
  constructor(public readonly status: number) { super(status === 401 ? '登录会话已过期，请重新登录。' : '身份认证暂时不可用，请重新尝试。'); }
}
let enabled = false;
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
export function expireBrowserSession() { if (enabled) clearBrowserSession(true); }
export function configureBrowserAuth(value: unknown): BrowserAuthConfig {
  if (!value || typeof value !== 'object') throw new BrowserAuthError(0);
  const config = value as Partial<BrowserAuthConfig>;
  if (config.developmentOnly !== undefined && typeof config.developmentOnly !== 'boolean') throw new BrowserAuthError(0);
  if (config.developmentOnly === true && config.enabled !== true) throw new BrowserAuthError(0);
  if (typeof config.enabled !== 'boolean' || config.loginPath !== '/api/factory/auth/login' || config.logoutPath !== '/api/factory/auth/logout') throw new BrowserAuthError(0);
  if (enabled !== config.enabled) clearBrowserSession();
  enabled = config.enabled;
  return config as BrowserAuthConfig;
}
async function authJson(path: string, method = 'GET', signal?: AbortSignal) {
  const started = epoch;
  let response: Response;
  try {
    response = await fetch(path, { method, credentials: 'same-origin', cache: 'no-store', redirect: 'error', signal,
      ...(method === 'POST' ? { headers: { 'Content-Type': 'application/json' }, body: '{}' } : {}) });
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
export async function browserAuthConfig(signal?: AbortSignal) {
  const value = await authJson('/api/factory/auth/config', 'GET', signal);
  if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
  return configureBrowserAuth(value);
}
export async function browserCsrf(): Promise<string | undefined> {
  if (!enabled) return undefined;
  if (csrf) return csrf;
  if (!pending) {
    const started = epoch;
    const work = (async () => {
      const value = await authJson('/api/factory/auth/session');
      assertAuthEpoch(started);
      const session = value as { authenticated?: unknown; csrfToken?: unknown } | null;
      if (!session || session.authenticated !== true) { expireBrowserSession(); throw new BrowserAuthError(401); }
      if (typeof session.csrfToken !== 'string' || !/^[\x21-\x7e]{16,512}$/.test(session.csrfToken)) throw new BrowserAuthError(0);
      csrf = session.csrfToken; return csrf;
    })();
    pending = work;
    void work.finally(() => { if (pending === work) pending = undefined; }).catch(() => {});
  }
  return pending;
}
export function authorizationDestination(value: unknown): string {
  if (!value || typeof value !== 'object' || typeof (value as { authorizationUrl?: unknown }).authorizationUrl !== 'string') throw new BrowserAuthError(0);
  const raw = (value as { authorizationUrl: string }).authorizationUrl;
  let url: URL;
  try { url = new URL(raw); } catch { throw new BrowserAuthError(0); }
  if (url.protocol !== 'https:' || url.username || url.password || raw.length > 8192) throw new BrowserAuthError(0);
  return url.href;
}
export async function startBrowserLogin(): Promise<string> {
  if (!enabled) throw new BrowserAuthError(0);
  clearBrowserSession();
  const started = epoch;
  const value = await authJson('/api/factory/auth/login', 'POST');
  assertAuthEpoch(started);
  return authorizationDestination(value);
}
export function consumeSigninFailure(location: Pick<Location, 'href'>, replace: (url: string) => void): boolean {
  const url = new URL(location.href);
  const failed = url.searchParams.has('auth_error');
  if (failed) { url.searchParams.delete('auth_error'); replace(url.pathname + url.search + url.hash); }
  return failed;
}
