import { authEpoch, assertAuthEpoch, browserCsrf, BrowserAuthError, expireBrowserSession } from './browserAuth.js';
import type { User } from './models.js';

export class ApiError extends Error {
  constructor(message: string, public readonly status: number, public readonly code?: string, public readonly rejected = false) { super(message); }
}
const base = '/api/factory';
async function request<T>(path: string, method = 'GET', body?: unknown, signal?: AbortSignal, expectedOwner?: string): Promise<T> {
  const started = authEpoch();
  let response: Response;
  try {
    const csrf = ['GET', 'HEAD', 'OPTIONS'].includes(method) ? undefined : await browserCsrf();
    assertAuthEpoch(started);
    response = await fetch(`${base}${path}`, {
      method, credentials: 'same-origin', cache: 'no-store', redirect: 'error', signal,
      headers: { ...(body === undefined ? {} : { 'Content-Type': 'application/json' }), ...(csrf ? { 'X-Factory-CSRF': csrf } : {}), ...(expectedOwner === undefined ? {} : { 'X-Factory-Expected-Owner': expectedOwner }) },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') throw error;
    if (error instanceof BrowserAuthError) throw new ApiError(error.message, error.status, 'BROWSER_AUTH');
    throw new ApiError('无法连接服务。检查网络后重试；创建请求会沿用原请求标识。', 0, 'OFFLINE');
  }
  const text = await response.text();
  assertAuthEpoch(started);
  if (response.status === 401) expireBrowserSession();
  let data: unknown;
  try { data = text ? JSON.parse(text) : undefined; } catch { data = undefined; }
  if (!response.ok) {
    const value = data && typeof data === 'object' ? data as Record<string, unknown> : {};
    const nested = value.error && typeof value.error === 'object' ? value.error as Record<string, unknown> : {};
    const detail = value.detail && typeof value.detail === 'object' ? value.detail as Record<string, unknown> : {};
    const message = value.message ?? nested.message ?? detail.message ?? (typeof value.detail === 'string' ? value.detail : undefined) ?? value.error;
    const code = value.code ?? nested.code ?? detail.code;
    throw new ApiError(typeof message === 'string' ? message : `服务返回 ${response.status}，操作未确认。`, response.status, typeof code === 'string' ? code : undefined, response.headers.get('X-Factory-Command-Rejected') === 'true');
  }
  if (response.status === 204) return undefined as T;
  if (data === undefined) throw new ApiError('服务未返回可识别的数据，请重试。', response.status, 'INVALID_RESPONSE');
  return data as T;
}
export const api = {
  session: (signal?: AbortSignal) => request<User>('/session', 'GET', undefined, signal),
  logout: () => request<void>('/logout', 'POST'),
};
export { request as factoryRequest };
