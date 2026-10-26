// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import App, { type WorkspaceSessionProps } from '../web/App.js';
import { clearBrowserSession, configureBrowserAuth } from '../web/browserAuth.js';

const config = { enabled: true, oidcEnabled: true, localLoginEnabled: false, loginPath: '/api/factory/auth/login', logoutPath: '/api/factory/auth/logout' };
let root: Root; let host: HTMLDivElement;
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  window.history.replaceState(null, '', '/?tab=research&project=original#evidence');
  clearBrowserSession(); configureBrowserAuth({ ...config, enabled: false, oidcEnabled: false });
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
it('keeps the original URL and offers only configured OIDC login', async () => {
  const fetch = vi.fn((path: string) => Promise.resolve(path.endsWith('/auth/config') ? json(config) : json({}, 401)));
  vi.stubGlobal('fetch', fetch);
  await act(async () => root.render(createElement(App)));
  expect(host.textContent).toContain('使用企业账号登录');
  expect(host.querySelector('input[name="password"]')).toBeNull();
  expect(host.textContent).not.toMatch(/Alice|Bob|开发测试身份|演示/);
  expect(window.location.search + window.location.hash).toBe('?tab=research&project=original#evidence');
  expect(fetch.mock.calls.map(([path]) => path)).toEqual(['/api/factory/auth/config', '/api/factory/session']);
});
it.each([{ ...config, enabled: false, oidcEnabled: false }, { ...config, developmentOnly: true }])('does not fall back to a persona or existing session for unavailable identity %#', async value => {
  const fetch = vi.fn(() => Promise.resolve(json(value))); vi.stubGlobal('fetch', fetch);
  await act(async () => root.render(createElement(App)));
  expect(host.textContent).toContain('身份认证未就绪');
  expect(host.textContent).not.toMatch(/使用企业账号登录|Alice|Bob|开发测试身份/);
  expect(fetch).toHaveBeenCalledOnce();
  expect(host.querySelector('[role="alert"]')).not.toBeNull();
});

const localConfig = { ...config, oidcEnabled: false, localLoginEnabled: true };
const button = (text: string) => [...host.querySelectorAll('button')].find(item => item.textContent === text)!;
async function fill(name: string, value: string) {
  const input = host.querySelector<HTMLInputElement>(`input[name="${name}"]`)!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
}
function SignedIn({ user, logout }: WorkspaceSessionProps) {
  return createElement('div', null, createElement('p', null, user.id), createElement('button', { onClick: logout }, '退出'));
}
it.each([false, true])('offers the configured local form and explicit OIDC choice: OIDC=%s', async oidcEnabled => {
  vi.stubGlobal('fetch', vi.fn((path: string) => Promise.resolve(path.endsWith('/auth/config') ? json({ ...localConfig, oidcEnabled }) : json({}, 401))));
  await act(async () => root.render(createElement(App)));
  expect(host.querySelector('input[name="username"]')).not.toBeNull();
  expect(host.querySelector('input[name="password"]')?.getAttribute('type')).toBe('password');
  expect(button('使用企业账号登录') !== undefined).toBe(oidcEnabled);
  expect(button('登录').disabled).toBe(false);
});
it('submits a Unicode password unchanged, clears it, then uses the server session and logout', async () => {
  let authenticated = false;
  let finish!: (response: Response) => void;
  const fetch = vi.fn((path: string) => {
    if (path.endsWith('/auth/config')) return Promise.resolve(json(localConfig));
    if (path.endsWith('/auth/local-login')) return new Promise<Response>(resolve => { finish = resolve; });
    if (path.endsWith('/auth/session')) return Promise.resolve(json({ authenticated: true, csrfToken: 'a'.repeat(43) }));
    if (path.endsWith('/logout')) { authenticated = false; return Promise.resolve(new Response(null, { status: 204 })); }
    return Promise.resolve(authenticated ? json({ id: 'configured-member', name: 'Configured member', role: 'user' }) : json({}, 401));
  });
  vi.stubGlobal('fetch', fetch);
  const localWrite = vi.spyOn(window.localStorage, 'setItem');
  const sessionWrite = vi.spyOn(window.sessionStorage, 'setItem');
  await act(async () => root.render(createElement(App, { workspace: SignedIn })));
  const password = ' ' + '🔬'.repeat(65) + ' ';
  await fill('username', 'configured-member'); await fill('password', password);
  expect(host.querySelector<HTMLInputElement>('input[name="password"]')!.checkValidity()).toBe(true);
  await act(async () => button('登录').click());
  expect(host.querySelector<HTMLInputElement>('input[name="password"]')!.value).toBe('');
  expect(button('正在登录…').closest('fieldset')?.disabled).toBe(true);
  expect(fetch).toHaveBeenCalledWith('/api/factory/auth/local-login', expect.objectContaining({ body: JSON.stringify({ username: 'configured-member', password }) }));
  await act(async () => { authenticated = true; finish(json({ authenticated: true })); });
  expect(host.textContent).toContain('configured-member');
  expect(window.location.search + window.location.hash).toBe('?tab=research&project=original#evidence');
  expect(fetch.mock.calls.at(-1)?.[0]).toBe('/api/factory/session');
  await act(async () => button('退出').click());
  expect(button('登录')).toBeDefined();
  expect(fetch.mock.calls.slice(-2).map(([path]) => path)).toEqual(['/api/factory/auth/session', '/api/factory/logout']);
  expect(localWrite).not.toHaveBeenCalled(); expect(sessionWrite).not.toHaveBeenCalled();
  localWrite.mockRestore(); sessionWrite.mockRestore();
});
it('clears failed credentials and does not fall back to OIDC or request a user session', async () => {
  const fetch = vi.fn((path: string) => Promise.resolve(path.endsWith('/auth/config') ? json({ ...localConfig, oidcEnabled: true }) : json({ detail: 'private-password-debug' }, 401)));
  vi.stubGlobal('fetch', fetch);
  await act(async () => root.render(createElement(App)));
  await fill('username', 'unknown-member'); await fill('password', 'wrong-password');
  fetch.mockClear();
  await act(async () => button('登录').click());
  expect(host.querySelector<HTMLInputElement>('input[name="password"]')!.value).toBe('');
  expect(host.querySelector('[role="alert"]')?.textContent).toContain('登录失败');
  expect(host.textContent).not.toContain('private-password-debug');
  expect(button('使用企业账号登录').disabled).toBe(false);
  expect(fetch.mock.calls.map(([path]) => path)).toEqual(['/api/factory/auth/local-login']);
});
