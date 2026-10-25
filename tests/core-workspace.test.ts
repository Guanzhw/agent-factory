// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { Workspace } from '../web/composition.js';
import { api } from '../web/api.js';
import { readWorkspaceRoute, workspaceUrl } from '../web/workspaceNavigation.js';

vi.mock('../web/ControlRecovery.js', () => ({ ControlRecovery: () => null }));
let host: HTMLDivElement; let root: Root;
const logout = vi.fn();
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new Error('Unexpected network request'))));
  vi.spyOn(api, 'status').mockResolvedValue({ mode: 'demo', activeWorkers: 0, queuedJobs: 0, maxWorkers: 2, integration: 'Synthetic', liveEnabled: false });
  vi.spyOn(api, 'materials').mockResolvedValue([]);
  vi.spyOn(api, 'jobs').mockResolvedValue({ items: [], nextCursor: null });
  vi.spyOn(api, 'executionTargets').mockResolvedValue([]);
  logout.mockReset(); host = document.createElement('div'); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function mount(url: string) {
  window.history.replaceState(null, '', url);
  await act(async () => root.render(createElement(Workspace, { user: { id: 'fixture', name: 'Fixture', role: 'user' }, logout, sessionBusy: false, sessionError: '' })));
}
async function click(label: string) {
  const button = [...host.querySelectorAll('button')].find(value => value.textContent === label);
  expect(button).toBeDefined(); await act(async () => button!.click());
}
it('renders the actual empty composition and retains resources, tasks and logout', async () => {
  await mount('/');
  expect(host.querySelector('h1')?.textContent).toBe('应用目录');
  expect(host.querySelector('.brand-symbol')?.textContent).toBe('F');
  expect(host.textContent).toContain('暂无已接入的应用。');
  expect(host.textContent).not.toMatch(/OpenResearch|Auto-Research/);
  await click('资源'); expect(host.querySelector('h1')?.textContent).toBe('我的资源');
  expect(host.textContent).toContain('设置我的模型/API'); expect(host.textContent).toContain('管理服务器与连接');
  await click('任务'); expect(host.querySelector('h1')?.textContent).toBe('任务与证据');
  expect(host.textContent).toContain('尚无任务。');
  expect(new URL(window.location.href).searchParams.get('tab')).toBe('tasks');
  await click('退出'); expect(logout).toHaveBeenCalledOnce();
  expect(fetch).not.toHaveBeenCalled();
});
it.each(['catalog', 'resources', 'tasks'])('restores the generic %s view directly', async tab => {
  await mount(`/?tab=${tab}`);
  const headings = { catalog: '应用目录', resources: '我的资源', tasks: '任务与证据' };
  expect(host.querySelector('h1')?.textContent).toBe(headings[tab as keyof typeof headings]);
  expect(new URL(window.location.href).searchParams.get('tab')).toBe(tab);
  expect(fetch).not.toHaveBeenCalled();
});
it.each(['research', 'openresearch', 'autoresearch', 'comparison'])('normalizes retired %s entry to the empty catalog', async tab => {
  await mount(`/?tab=${tab}`);
  expect(host.querySelector('h1')?.textContent).toBe('应用目录');
  expect(host.textContent).toContain('暂无已接入的应用。');
  expect(new URL(window.location.href).searchParams.get('tab')).toBe('catalog');
  expect(fetch).not.toHaveBeenCalled();
});
it('preserves valid task and model return pointers across URL serialization and rejects unauthorized account views', () => {
  for (const query of ['tab=tasks&task=fixture-task', 'tab=models&modelReturn=connections']) {
    const url = new URL(`https://fixture.example/?${query}`);
    const route = readWorkspaceRoute(url, false);
    expect(readWorkspaceRoute(new URL(workspaceUrl(url, route), url), false)).toEqual(route);
  }
  expect(readWorkspaceRoute(new URL('https://fixture.example/?tab=accounts'), false).tab).toBe('catalog');
});
