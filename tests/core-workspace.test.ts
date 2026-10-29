// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { Workspace } from '../web/composition.js';
import { api } from '../web/api.js';
import { ownerModelApi } from '../web/ownerModelApi.js';
import { clearBrowserSession } from '../web/browserAuth.js';
import { readWorkspaceRoute, workspaceUrl } from '../web/workspaceNavigation.js';

vi.mock('../web/ControlRecovery.js', () => ({ ControlRecovery: () => null }));
let host: HTMLDivElement; let root: Root;
const logout = vi.fn();
beforeEach(() => {
  sessionStorage.clear();
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new Error('Unexpected network request'))));
  vi.spyOn(api, 'status').mockResolvedValue({ mode: 'demo', activeWorkers: 0, queuedJobs: 0, maxWorkers: 2, integration: 'Synthetic', liveEnabled: false });
  vi.spyOn(api, 'materials').mockResolvedValue([]);
  vi.spyOn(api, 'jobs').mockResolvedValue({ items: [], nextCursor: null });
  vi.spyOn(api, 'executionTargets').mockResolvedValue([]);
  logout.mockReset(); host = document.createElement('div'); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function mount(url: string, ownerId = 'fixture') {
  window.history.replaceState(null, '', url);
  await act(async () => root.render(createElement(Workspace, { user: { id: ownerId, name: 'Fixture', role: 'user' }, logout, sessionBusy: false, sessionError: '' })));
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
  await click('我的资源'); expect(host.querySelector('h1')?.textContent).toBe('我的资源');
  expect(host.textContent).toContain('设置我的模型/API'); expect(host.textContent).toContain('管理服务器');
  await click('我的任务'); expect(host.querySelector('h1')?.textContent).toBe('我的任务');
  expect(host.textContent).toContain('尚无任务。');
  expect(new URL(window.location.href).searchParams.get('tab')).toBe('tasks');
  await click('退出'); expect(logout).toHaveBeenCalledOnce();
  expect(fetch).not.toHaveBeenCalled();
});
it.each(['catalog', 'resources', 'tasks'])('restores the generic %s view directly', async tab => {
  await mount(`/?tab=${tab}`);
  const headings = { catalog: '应用目录', resources: '我的资源', tasks: '我的任务' };
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
it.each([
  ['connections', '返回连接配置'], ['catalog', '返回应用'], ['resources', '返回我的资源'],
])('returns from model settings to its actual generic %s origin', async (origin, label) => {
  vi.spyOn(ownerModelApi, 'capabilities').mockResolvedValue({ enabled: false, providers: [], liveCompatibilityVerified: false });
  vi.spyOn(ownerModelApi, 'list').mockResolvedValue([]);
  await mount(`/?tab=models&modelReturn=${origin}&resource=credentials`);
  await click(label);
  expect(new URL(window.location.href).searchParams.get('tab')).toBe(origin);
  if (origin === 'connections') expect(new URL(window.location.href).searchParams.get('resource')).toBe('credentials');
  expect(host.textContent).not.toContain('返回原研究');
});

it('uses three daily entries and keeps author and maintenance destinations reachable', async () => {
  await mount('/?tab=applications');
  const nav = host.querySelector('nav[aria-label="工作区"]')!;
  expect([...nav.querySelectorAll(':scope > button')].map(button => button.textContent)).toEqual(['应用', '我的任务', '我的资源', '收起创作与维护']);
  expect(nav.querySelector('#secondary-navigation')?.classList.contains('expanded')).toBe(true);
  expect(nav.querySelector('[aria-current="page"]')?.textContent).toBe('应用模板');
  expect(nav.textContent).not.toContain('账号管理');
  await click('我的资源');
  expect(nav.querySelector('#secondary-navigation')?.classList.contains('expanded')).toBe(false);
  await click('创作与维护');
  expect(nav.querySelector('#secondary-navigation')?.classList.contains('expanded')).toBe(true);
  await click('高级装配');
  expect(new URL(window.location.href).searchParams.get('tab')).toBe('developer');
});

it('round-trips actual resource categories and rejects arbitrary resource selectors', () => {
  for (const resource of ['servers', 'tools', 'remotes', 'credentials', 'records']) {
    const url = new URL(`https://fixture.example/?tab=connections&resource=${resource}`);
    const route = readWorkspaceRoute(url, false);
    expect(route.resource).toBe(resource);
    expect(readWorkspaceRoute(new URL(workspaceUrl(url, route), url), false)).toEqual(route);
  }
  const invalid = new URL('https://fixture.example/?tab=connections&resource=unregistered');
  expect(readWorkspaceRoute(invalid, false).resource).toBeUndefined();
  expect(workspaceUrl(invalid, readWorkspaceRoute(invalid, false))).toBe('/?tab=connections');
});

it('keeps owner model drafts during navigation and clears them after auth invalidation only', async () => {
  sessionStorage.setItem('factory-model-draft:alice', 'synthetic Alice draft');
  sessionStorage.setItem('factory-model-draft:bob', 'synthetic Bob draft');
  await mount('/', 'alice');
  await click('我的资源');
  expect(sessionStorage.getItem('factory-model-draft:alice')).toBe('synthetic Alice draft');
  await act(async () => root.render(null));
  expect(sessionStorage.getItem('factory-model-draft:alice')).toBe('synthetic Alice draft');
  await mount('/?tab=resources', 'alice');
  clearBrowserSession();
  await act(async () => root.render(null));
  expect(sessionStorage.getItem('factory-model-draft:alice')).toBeNull();
  expect(sessionStorage.getItem('factory-model-draft:bob')).toBe('synthetic Bob draft');
});
