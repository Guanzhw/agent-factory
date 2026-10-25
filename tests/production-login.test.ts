// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import App from '../web/App.js';
import { clearBrowserSession, configureBrowserAuth } from '../web/browserAuth.js';

const config = { enabled: true, loginPath: '/api/factory/auth/login', logoutPath: '/api/factory/auth/logout' };
let root: Root; let host: HTMLDivElement;
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  window.history.replaceState(null, '', '/?tab=research&project=original#evidence');
  clearBrowserSession(); configureBrowserAuth({ ...config, enabled: false });
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals(); });
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
it('keeps the original URL and offers only configured OIDC login', async () => {
  const fetch = vi.fn((path: string) => Promise.resolve(path.endsWith('/auth/config') ? json(config) : json({}, 401)));
  vi.stubGlobal('fetch', fetch);
  await act(async () => root.render(createElement(App)));
  expect(host.textContent).toContain('使用企业账号登录');
  expect(host.textContent).not.toMatch(/Alice|Bob|开发测试身份|演示/);
  expect(window.location.search + window.location.hash).toBe('?tab=research&project=original#evidence');
  expect(fetch.mock.calls.map(([path]) => path)).toEqual(['/api/factory/auth/config', '/api/factory/session']);
});
it.each([{ ...config, enabled: false }, { ...config, developmentOnly: true }])('does not fall back to a persona or existing session for unavailable identity %#', async value => {
  const fetch = vi.fn(() => Promise.resolve(json(value))); vi.stubGlobal('fetch', fetch);
  await act(async () => root.render(createElement(App)));
  expect(host.textContent).toContain('身份认证未就绪');
  expect(host.textContent).not.toMatch(/使用企业账号登录|Alice|Bob|开发测试身份/);
  expect(fetch).toHaveBeenCalledOnce();
  expect(host.querySelector('[role="alert"]')).not.toBeNull();
});
