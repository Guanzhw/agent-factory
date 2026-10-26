// @vitest-environment happy-dom
import { act, createElement, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { Workspace } from '../web/App.js';
import { ResearchSession } from '../web/research-composition.js';
import { api } from '../web/api.js';
import { ownerModelApi } from '../web/ownerModelApi.js';
import { personalSSHApi } from '../web/personalSSHApi.js';
import type { WorkspaceRoute } from '../web/workspaceNavigation.js';

vi.mock('../web/ControlRecovery.js', () => ({ ControlRecovery: () => null }));
// Test the composition boundary without executing research business workflows.
vi.mock('../web/apps/research/ResearchWorkspace.js', () => ({ ResearchWorkbench: ({ route, navigate }: { route: WorkspaceRoute; navigate: (patch: Partial<WorkspaceRoute>) => void }) => createElement('section', null,
  createElement('h1', null, '研究导航测试'), createElement('p', { 'data-project': route.project }, route.project),
  createElement('button', { onClick: () => navigate({ tab: 'resources', modelReturn: 'research' }) }, '配置资源'),
  createElement('button', { onClick: () => navigate({ tab: 'tasks', task: 'original-task' }) }, '进入原任务'),
  createElement('button', { onClick: () => navigate({ tab: 'catalog' }) }, '返回平台')) }));
type ResourceProps = { navigation?: ReactNode; backLabel?: string; onBack: () => void; onCredentials?: () => void; section?: string };
vi.mock('../web/ModelSettings.js', () => ({ ModelSettings: ({ navigation, backLabel, onBack, onCredentials }: ResourceProps) => createElement('section', null,
  createElement('h1', null, '模型接线测试'), navigation, createElement('button', { onClick: onBack }, backLabel), createElement('button', { onClick: onCredentials }, '打开凭据')) }));
vi.mock('../web/ConnectionsPanel.js', () => ({ ConnectionsPanel: ({ navigation, backLabel, onBack, section }: ResourceProps) => createElement('section', null,
  createElement('h1', null, '连接接线测试'), navigation, createElement('p', { 'data-resource': section }, section), createElement('button', { onClick: onBack }, backLabel)) }));

let host: HTMLDivElement; let root: Root;
const user = { id: 'alice', name: 'Alice', role: 'user' as const };
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new Error('Unexpected network request'))));
  vi.spyOn(api, 'status').mockResolvedValue({ mode: 'live', liveEnabled: true, activeWorkers: 0, queuedJobs: 0, maxWorkers: 1, integration: 'fixture' });
  vi.spyOn(api, 'materials').mockResolvedValue([]); vi.spyOn(api, 'executionTargets').mockResolvedValue([]);
  vi.spyOn(api, 'jobs').mockResolvedValue({ items: [], nextCursor: null });
  vi.spyOn(api, 'detail').mockRejectedValue(new Error('This fixture only validates navigation'));
  vi.spyOn(ownerModelApi, 'capabilities').mockResolvedValue({ enabled: false, providers: [], liveCompatibilityVerified: false });
  vi.spyOn(personalSSHApi, 'capabilities').mockResolvedValue({ enabled: false });
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); expect(fetch).not.toHaveBeenCalled(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function click(label: string) {
  const button = [...host.querySelectorAll('button')].find(item => item.textContent === label);
  expect(button, label).toBeDefined(); await act(async () => button!.click());
}
async function mount(url = '/?tab=research&project=project-one&researchTab=evidence&researchQuestion=question-one') {
  window.history.replaceState(null, '', url);
  await act(async () => root.render(createElement(ResearchSession, { user, logout: vi.fn(), sessionBusy: false, sessionError: '' })));
}
const query = () => Object.fromEntries(new URL(window.location.href).searchParams);

it('returns from the original task to its original research project without replacing the task', async () => {
  await mount(); await click('进入原任务');
  expect(query()).toMatchObject({ tab: 'tasks', task: 'original-task', project: 'project-one', researchTab: 'evidence', modelReturn: 'research' });
  expect(host.querySelector('h1')?.textContent).toBe('我的任务');
  await click('返回 AutoResearch');
  expect(query()).toMatchObject({ tab: 'research', task: 'original-task', project: 'project-one', researchTab: 'evidence', researchQuestion: 'question-one' });
  expect(query().modelReturn).toBeUndefined();
});

it('keeps the application source through sidebar visits and every resource category', async () => {
  await mount(); await click('进入原任务'); await click('我的资源');
  expect(query().modelReturn).toBe('research');
  await click('设置模型'); await click('打开凭据');
  expect(query()).toMatchObject({ tab: 'connections', resource: 'credentials', modelReturn: 'research' });
  for (const [label, resource] of [['服务器', 'servers'], ['工具', 'tools'], ['远程服务', 'remotes'], ['高级记录', 'advanced']] as const) {
    await click(label); expect(query()).toMatchObject({ resource, modelReturn: 'research', project: 'project-one' });
  }
  await click('模型'); expect(query().tab).toBe('models');
  await click('返回 AutoResearch'); expect(query()).toMatchObject({ tab: 'research', project: 'project-one', task: 'original-task' });
});

it('restores resource deep links and browser history without duplicating the current page', async () => {
  await mount('/?tab=connections&resource=wrong&modelReturn=research&project=project-one&researchTab=evidence');
  expect(query().resource).toBe('servers'); expect(host.querySelector('[data-resource]')?.getAttribute('data-resource')).toBe('servers');
  await click('凭据'); const saved = window.location.href; const length = window.history.length;
  await click('凭据'); expect(window.history.length).toBe(length);
  await act(async () => { window.history.back(); await new Promise(resolve => setTimeout(resolve, 20)); });
  expect(query()).toMatchObject({ resource: 'servers', modelReturn: 'research', project: 'project-one' });
  await act(async () => { window.history.forward(); await new Promise(resolve => setTimeout(resolve, 20)); });
  expect(window.location.href).toBe(saved);
  await act(async () => root.unmount()); root = createRoot(host); await mount(new URL(saved).pathname + new URL(saved).search);
  expect(query().resource).toBe('credentials'); await click('返回 AutoResearch');
  expect(query()).toMatchObject({ tab: 'research', project: 'project-one', researchTab: 'evidence' });
});

it('ends the source chain only on an explicit platform return or application selection', async () => {
  await mount(); await click('配置资源'); await click('应用');
  expect(query().tab).toBe('catalog');
  for (const key of ['modelReturn', 'project', 'researchTab', 'researchQuestion']) expect(query()[key]).toBeUndefined();
  const length = window.history.length; await click('应用'); expect(window.history.length).toBe(length);
  await click('进入 AutoResearch'); expect(query().tab).toBe('research'); expect(query().project).toBeUndefined();
  await click('返回平台'); expect(query().tab).toBe('catalog');
});

it('preserves a local resource return without turning it into an application source', async () => {
  await mount('/?tab=connections&resource=tools'); await click('模型');
  expect(query()).toMatchObject({ tab: 'models', modelReturn: 'connections', resource: 'tools' });
  await click('返回连接设置'); expect(query()).toMatchObject({ tab: 'connections', resource: 'tools' });
  expect(query().modelReturn).toBeUndefined();
});

it('does not invent a return source or history entry when reselecting a directly opened model page', async () => {
  await mount('/?tab=models');
  const url = window.location.href; const length = window.history.length;
  await click('模型'); await click('模型');
  expect(window.location.href).toBe(url); expect(window.history.length).toBe(length);
  expect(query().modelReturn).toBeUndefined();
});

it('keeps low-frequency tools collapsed, preserves account boundaries and uses real expand controls', async () => {
  window.history.replaceState(null, '', '/?tab=accounts');
  const props = { user, logout: vi.fn(), sessionBusy: false, sessionError: '', children: () => createElement('h1', null, '测试工作区') };
  await act(async () => root.render(createElement(Workspace, props)));
  expect(query().tab).toBe('catalog'); expect(host.textContent).not.toContain('账号管理');
  expect(host.querySelector('#secondary-navigation')?.hasAttribute('hidden')).toBe(true);
  await click('更多'); expect(host.querySelector('#secondary-navigation')?.hasAttribute('hidden')).toBe(false);
  for (const name of ['计划任务', '存储与回收', '开发者装配', '应用管理', '共享材料管理', '历史方案审查']) expect(host.querySelector('#secondary-navigation')!.textContent).toContain(name);
  await act(async () => host.querySelector<HTMLButtonElement>('.mobile-menu-toggle')!.click());
  expect(host.querySelector('.mobile-menu-toggle')?.getAttribute('aria-expanded')).toBe('true');
  await click('我的任务'); expect(host.querySelector('.mobile-menu-toggle')?.getAttribute('aria-expanded')).toBe('false');
  await act(async () => root.render(createElement(Workspace, { ...props, key: 'manager', user: { ...user, role: 'manager' } })));
  expect(host.querySelector('#secondary-navigation')!.textContent).toContain('账号管理');
});
