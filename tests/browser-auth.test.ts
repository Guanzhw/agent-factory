import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../web/api.js';
import { authEpoch, assertAuthEpoch, authorizationDestination, browserAuthConfig, browserCsrf, clearBrowserSession, configureBrowserAuth, consumeSigninFailure, startBrowserLogin, subscribeSessionExpiry } from '../web/browserAuth.js';

const config = (enabled = true) => ({ enabled, loginPath: '/api/factory/auth/login', logoutPath: '/api/factory/auth/logout' });
const token = 'a'.repeat(43);
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
beforeEach(() => { clearBrowserSession(); configureBrowserAuth(config()); });
afterEach(() => { clearBrowserSession(); configureBrowserAuth(config(false)); vi.unstubAllGlobals(); });

describe('browser SSO boundary', () => {
  it('loads fixed public configuration without caching or forwarding credentials off origin', async () => {
    const fetch = vi.fn().mockResolvedValue(json(config())); vi.stubGlobal('fetch', fetch);
    await expect(browserAuthConfig()).resolves.toEqual(config());
    expect(fetch).toHaveBeenCalledWith('/api/factory/auth/config', expect.objectContaining({ credentials: 'same-origin', cache: 'no-store', redirect: 'error' }));
    for (const bad of [null, {}, { ...config(), enabled: 'true' }, { ...config(), loginPath: 'https://foreign.test' }]) expect(() => configureBrowserAuth(bad)).toThrow();
  });
  it('starts a fresh login without a token request or leaking provider error contents', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(json({ authorizationUrl: 'https://identity.example/authorize?state=public-fixture' }))
      .mockResolvedValueOnce(json({ detail: 'sensitive-provider-debug' }, 500));
    vi.stubGlobal('fetch', fetch);
    await expect(startBrowserLogin()).resolves.toBe('https://identity.example/authorize?state=public-fixture');
    expect(fetch).toHaveBeenCalledWith('/api/factory/auth/login', expect.objectContaining({ method: 'POST', body: '{}', headers: { 'Content-Type': 'application/json' } }));
    await expect(startBrowserLogin()).rejects.toThrow('身份认证暂时不可用');
    expect(fetch).toHaveBeenCalledTimes(2);
  });
  it('rejects script, insecure and embedded-credential authorization destinations', () => {
    for (const authorizationUrl of ['javascript:alert(1)', 'http://identity.example/', '//identity.example/', 'https://user:password@identity.example/', 'not-url']) {
      expect(() => authorizationDestination({ authorizationUrl })).toThrow();
    }
  });
  it('uses one in-memory CSRF acquisition for concurrent mutations and clears it on logout', async () => {
    const fetch = vi.fn().mockImplementation((url: string) => Promise.resolve(url.endsWith('/auth/session') ? json({ authenticated: true, csrfToken: token }) : new Response(null, { status: 204 })));
    vi.stubGlobal('fetch', fetch);
    await Promise.all([api.logout(), api.logout()]);
    expect(fetch.mock.calls.filter(call => call[0].endsWith('/auth/session'))).toHaveLength(1);
    expect(fetch.mock.calls.filter(call => call[0].endsWith('/logout'))).toHaveLength(2);
    expect(fetch.mock.calls[1][1]).toMatchObject({ headers: { 'X-Factory-CSRF': token }, credentials: 'same-origin', cache: 'no-store', redirect: 'error' });
    clearBrowserSession();
    await api.logout();
    expect(fetch.mock.calls.filter(call => call[0].endsWith('/auth/session'))).toHaveLength(2);
  });
  it('does not dispatch unsafe requests if the cookie session is absent or CSRF is malformed', async () => {
    for (const session of [{ authenticated: false }, { authenticated: true, csrfToken: 'bad\nheader' }, { authenticated: true }, null]) {
      clearBrowserSession();
      const fetch = vi.fn().mockResolvedValue(json(session)); vi.stubGlobal('fetch', fetch);
      await expect(api.logout()).rejects.toThrow();
      expect(fetch).toHaveBeenCalledTimes(1);
      expect(fetch.mock.calls[0][0]).toBe('/api/factory/auth/session');
    }
  });
  it('invalidates late old-user GET responses after session expiry without replaying mutations', async () => {
    let complete!: (value: Response) => void;
    const fetch = vi.fn().mockImplementationOnce(() => new Promise<Response>(resolve => { complete = resolve; }))
      .mockResolvedValueOnce(json({ detail: 'unauthenticated' }, 401));
    vi.stubGlobal('fetch', fetch);
    const expired = vi.fn(); const unsubscribe = subscribeSessionExpiry(expired);
    try {
      const oldUser = api.jobs();
      await expect(api.session()).rejects.toMatchObject({ status: 401 });
      complete(json([{ ownerId: 'old-user' }]));
      await expect(oldUser).rejects.toMatchObject({ name: 'AbortError' });
      expect(expired).toHaveBeenCalledTimes(1);
    } finally { unsubscribe(); }
  });
  it('does not reuse a pending CSRF result after a session generation change', async () => {
    let complete!: (value: Response) => void;
    const fetch = vi.fn().mockImplementationOnce(() => new Promise<Response>(resolve => { complete = resolve; }))
      .mockResolvedValueOnce(json({ authenticated: true, csrfToken: 'b'.repeat(43) }));
    vi.stubGlobal('fetch', fetch);
    const old = browserCsrf(); clearBrowserSession();
    complete(json({ authenticated: true, csrfToken: token }));
    await expect(old).rejects.toMatchObject({ name: 'AbortError' });
    await expect(browserCsrf()).resolves.toBe('b'.repeat(43));
  });
  it('does not let a late old-session unauthorized reply invalidate the replacement session', async () => {
    let complete!: (value: Response) => void;
    const fetch = vi.fn().mockImplementationOnce(() => new Promise<Response>(resolve => { complete = resolve; }))
      .mockResolvedValueOnce(json({ authenticated: true, csrfToken: 'b'.repeat(43) }));
    vi.stubGlobal('fetch', fetch);
    const expired = vi.fn(); const unsubscribe = subscribeSessionExpiry(expired);
    try {
      const old = browserCsrf(); clearBrowserSession();
      await expect(browserCsrf()).resolves.toBe('b'.repeat(43));
      complete(json({}, 401));
      await expect(old).rejects.toMatchObject({ name: 'AbortError' });
      expect(expired).not.toHaveBeenCalled();
      await expect(browserCsrf()).resolves.toBe('b'.repeat(43));
      expect(fetch).toHaveBeenCalledTimes(2);
    } finally { unsubscribe(); }
  });
  it('preserves demo requests without CSRF requests or headers', async () => {
    configureBrowserAuth(config(false));
    const fetch = vi.fn().mockResolvedValue(json({ id: 'alice' })); vi.stubGlobal('fetch', fetch);
    await api.login('alice');
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe('/api/factory/demo/login');
    expect(fetch.mock.calls[0][1].headers).toEqual({ 'Content-Type': 'application/json' });
    await expect(startBrowserLogin()).rejects.toThrow();
  });
  it('consumes callback failure without displaying its value or retaining it in history', () => {
    const replace = vi.fn();
    expect(consumeSigninFailure({ href: 'https://factory.example/?auth_error=untrusted-secret#start' }, replace)).toBe(true);
    expect(replace).toHaveBeenCalledWith('/#start');
    expect(consumeSigninFailure({ href: 'https://factory.example/' }, replace)).toBe(false);
    const before = authEpoch(); clearBrowserSession();
    expect(() => assertAuthEpoch(before)).toThrow();
  });
});
