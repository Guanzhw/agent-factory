// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { Workspace, type WorkspaceContext } from '../web/App.js';
import { WorkspaceHome } from '../web/WorkspaceHome.js';
import { api } from '../web/api.js';
import { ownerModelApi, type OwnerModel } from '../web/ownerModelApi.js';
import { personalSSHApi, type PersonalSSHServer } from '../web/personalSSHApi.js';
import { personalRemoteApi } from '../web/personalRemoteApi.js';
import type { JobSummary } from '../web/models.js';

let host: HTMLDivElement; let root: Root; let context: WorkspaceContext;
const applications = [{ id: 'notes', name: '测试应用', description: '仅用于导航测试', entry: { tab: 'notes' } }];
const sharedModel: OwnerModel = { reference: 'shared', revision: 'r1', ownerId: 'other', isOwner: false,
  visibility: 'team', provider: 'openai-compatible', baseURL: 'http://localhost/v1', model: 'local-test',
  status: 'configured', available: true, isDefault: true, updatedAt: '2026-10-26T10:00:00Z' };
const server: PersonalSSHServer = { reference: `remote-${'a'.repeat(32)}`, name: '测试主机', address: 'test.invalid', port: 22, username: 'member', hostKey: 'ssh-test', hostFingerprint: 'test', allowedRoot: '/test', defaultDirectory: '/test', status: 'configured', enabled: false, executionEnabled: false, diagnostic: null, lastCheckRequestId: null, credentialRef: 'credential', credentialRevision: 'r1' };
function deferred<T>() { let resolve!: (value: T) => void; let reject!: (value: Error) => void; const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }
function job(id: string, ownerId = 'alice'): JobSummary { return { id, ownerId, planId: 'p', definitionId: 'd', definitionVersion: 1, status: 'running', createdAt: '2026-10-26T10:00:00Z', updatedAt: '2026-10-26T10:00:00Z', input: { topic: `任务 ${id}`, mode: 'test' } } as JobSummary; }
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new Error('Unexpected request'))));
  window.history.replaceState(null, '', '/?tab=catalog');
  vi.spyOn(api, 'status').mockResolvedValue({ mode: 'live', liveEnabled: true, activeWorkers: 8, queuedJobs: 4, maxWorkers: 12, integration: 'fixture' });
  vi.spyOn(api, 'materials').mockResolvedValue([]); vi.spyOn(api, 'executionTargets').mockResolvedValue([]);
  vi.spyOn(api, 'jobs').mockResolvedValue({ items: [], nextCursor: null });
  vi.spyOn(ownerModelApi, 'capabilities').mockResolvedValue({ enabled: true, credentialsEnabled: true, providers: ['openai-compatible'], liveCompatibilityVerified: false });
  vi.spyOn(ownerModelApi, 'list').mockResolvedValue([]);
  vi.spyOn(personalSSHApi, 'capabilities').mockResolvedValue({ enabled: true });
  vi.spyOn(personalSSHApi, 'list').mockResolvedValue([]);
  vi.spyOn(personalRemoteApi, 'credentials'); vi.spyOn(ownerModelApi, 'configure'); vi.spyOn(personalSSHApi, 'command');
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount()); host.remove();
  expect(personalRemoteApi.credentials).not.toHaveBeenCalled(); expect(ownerModelApi.configure).not.toHaveBeenCalled(); expect(personalSSHApi.command).not.toHaveBeenCalled(); expect(fetch).not.toHaveBeenCalled();
  vi.restoreAllMocks(); vi.unstubAllGlobals();
});
async function mount(owner = 'alice') {
  await act(async () => root.render(createElement(Workspace, {
    key: owner, user: { id: owner, name: owner, role: 'user' }, logout: vi.fn(), sessionBusy: false, sessionError: '',
    children: (value: WorkspaceContext) => { context = value; return createElement(WorkspaceHome, { context: value, applications }); },
  })));
}
async function refresh() { await act(async () => context.retry()); }

it('renders real empty summaries without converting platform capacity into personal metrics', async () => {
  await mount();
  expect(host.textContent).toContain('暂无任务'); expect(host.textContent).toContain('未设置'); expect(host.textContent).toContain('按需添加');
  expect(host.querySelector('.workspace-home')!.textContent).not.toMatch(/执行上限|成功率|节省/);
  expect(ownerModelApi.list).toHaveBeenCalledWith('alice', expect.any(AbortSignal));
  expect(personalSSHApi.list).toHaveBeenCalledWith('alice', expect.any(AbortSignal));
});

it('keeps each region loading independently and never flashes empty data before completion', async () => {
  const pending = deferred<OwnerModel[]>(); vi.mocked(ownerModelApi.list).mockReturnValue(pending.promise);
  await mount();
  expect(host.querySelectorAll('.home-resource-status')[0].textContent).toContain('正在读取');
  expect(host.querySelectorAll('.home-resource-status')[0].textContent).not.toContain('未设置');
  expect(host.querySelectorAll('.home-resource-status')[1].textContent).toContain('按需添加');
  expect(host.textContent).toContain('暂无任务');
  await act(async () => pending.resolve([sharedModel]));
  expect(host.textContent).toContain('默认：local-test'); expect(host.textContent).toContain('团队共享模型');
});

it('shows a shared current default and distinguishes saved SSH configuration from connection enablement', async () => {
  vi.mocked(ownerModelApi.list).mockResolvedValue([sharedModel]); vi.mocked(personalSSHApi.list).mockResolvedValue([server]);
  await mount(); expect(host.textContent).toContain('默认：local-test'); expect(host.textContent).toContain('已登记，需检查或启用');
  vi.mocked(personalSSHApi.list).mockResolvedValue([{ ...server, enabled: true }]); await refresh();
  expect(host.textContent).toContain('已有启用的连接'); expect(host.querySelector('.workspace-home')!.textContent).not.toMatch(/在线|运行正常|验证成功/);
});

it('distinguishes disabled deployment, missing default and a vault-disabled unauthenticated model', async () => {
  vi.mocked(ownerModelApi.capabilities).mockResolvedValue({ enabled: true, credentialsEnabled: false, providers: [], liveCompatibilityVerified: false });
  vi.mocked(ownerModelApi.list).mockResolvedValue([{ ...sharedModel, isDefault: false }]);
  vi.mocked(personalSSHApi.capabilities).mockResolvedValue({ enabled: false });
  await mount(); expect(host.textContent).toContain('尚未选择默认模型'); expect(host.textContent).toContain('仍可配置无需认证');
  expect(host.textContent).toContain('此部署未启用服务器接入'); expect(personalSSHApi.list).not.toHaveBeenCalled();
  vi.mocked(ownerModelApi.list).mockResolvedValue([sharedModel]); await refresh(); expect(host.textContent).toContain('默认：local-test');
  vi.mocked(ownerModelApi.capabilities).mockResolvedValue({ enabled: false, providers: [], liveCompatibilityVerified: false });
  vi.mocked(ownerModelApi.list).mockClear(); await refresh(); expect(host.textContent).toContain('此部署未启用模型设置'); expect(ownerModelApi.list).not.toHaveBeenCalled();
});

it('keeps read errors separate from empty states and marks old successful results stale', async () => {
  vi.mocked(ownerModelApi.list).mockRejectedValue(new Error('private detail')); await mount();
  const modelRow = () => host.querySelectorAll('.home-resource-status')[0];
  expect(modelRow().textContent).toContain('暂时无法读取'); expect(modelRow().textContent).not.toMatch(/未设置|private detail/);
  vi.mocked(ownerModelApi.list).mockResolvedValue([sharedModel]); await refresh();
  vi.mocked(ownerModelApi.list).mockRejectedValue(new Error('offline')); await refresh();
  expect(modelRow().textContent).toContain('默认：local-test'); expect(modelRow().textContent).toContain('更新失败，保留上次记录');
  expect(host.querySelectorAll('.home-resource-status')[1].textContent).toContain('按需添加');
});

it('reports controller problems and rejects malformed SSH records instead of claiming an empty resource', async () => {
  vi.mocked(personalSSHApi.capabilities).mockResolvedValue({ enabled: true, controllerDiagnostic: 'SSH_SYSTEM_CLIENT_UNAVAILABLE' }); await mount();
  expect(host.textContent).toContain('控制端需要处理');
  vi.mocked(personalSSHApi.capabilities).mockResolvedValue({ enabled: true });
  vi.mocked(personalSSHApi.list).mockResolvedValue([{ name: 'invalid' } as PersonalSSHServer]); await refresh();
  expect(host.querySelectorAll('.home-resource-status')[1].textContent).toContain('更新失败');
  expect(host.querySelectorAll('.home-resource-status')[1].textContent).not.toContain('按需添加');
});

it('uses the existing recent task records and preserves their identity on selection', async () => {
  vi.mocked(api.jobs).mockResolvedValue({ items: [job('d'), job('c'), job('b'), job('a')], nextCursor: 'next' });
  vi.spyOn(api, 'detail').mockRejectedValue(new Error('No task execution in this fixture'));
  await mount(); expect(host.querySelectorAll('.home-task-list li')).toHaveLength(3); expect(api.jobs).toHaveBeenCalledTimes(1);
  await act(async () => host.querySelector<HTMLButtonElement>('.home-task-list button')!.click());
  expect(context.route).toMatchObject({ tab: 'tasks', task: 'd' });
});

it('retains task records on refresh failure without claiming a successful empty result', async () => {
  vi.mocked(api.jobs).mockResolvedValue({ items: [job('a')], nextCursor: null }); await mount();
  vi.mocked(api.jobs).mockRejectedValue(new Error('offline')); await refresh();
  expect(host.textContent).toContain('任务更新失败，保留上次记录'); expect(host.textContent).toContain('任务 a'); expect(host.textContent).not.toContain('暂无任务');
});

it('discards late responses after refresh and owner changes', async () => {
  const late = deferred<OwnerModel[]>(); vi.mocked(ownerModelApi.list).mockReturnValueOnce(late.promise);
  await mount(); vi.mocked(ownerModelApi.list).mockResolvedValue([{ ...sharedModel, model: 'current' }]); await refresh();
  await act(async () => late.resolve([{ ...sharedModel, model: 'obsolete' }]));
  expect(host.textContent).toContain('默认：current'); expect(host.textContent).not.toContain('obsolete');
  const previousOwner = deferred<OwnerModel[]>(); vi.mocked(ownerModelApi.list).mockReturnValueOnce(previousOwner.promise); await refresh();
  vi.mocked(ownerModelApi.list).mockResolvedValue([]); await mount('bob');
  await act(async () => previousOwner.resolve([sharedModel]));
  expect(host.textContent).not.toContain('local-test'); expect(host.textContent).toContain('未设置');
});
