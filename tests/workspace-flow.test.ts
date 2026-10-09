// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Workspace } from '../web/App.js';
import { api } from '../web/api.js';
import { personalAgentApi } from '../web/personalAgentApi.js';
import { personalRemoteApi } from '../web/personalRemoteApi.js';
import { openresearchApi } from '../web/openresearchApi.js';
import type { User } from '../web/models.js';
vi.mock('../web/openresearchApi.js', () => ({ openresearchApi: { capabilities: vi.fn(), projects: vi.fn() } }));
vi.mock('../web/personalAgentApi.js', async importOriginal => { const original = await importOriginal<typeof import('../web/personalAgentApi.js')>(); return { ...original, personalAgentApi: { ...original.personalAgentApi, capabilities: vi.fn(), sessions: vi.fn() } }; });
vi.mock('../web/personalRemoteApi.js', async importOriginal => { const original = await importOriginal<typeof import('../web/personalRemoteApi.js')>(); return { ...original, personalRemoteApi: { ...original.personalRemoteApi, list: vi.fn() } }; });
vi.mock('../web/ControlRecovery.js', () => ({ ControlRecovery: () => null, commandNotice: () => '' }));
vi.mock('../web/CompositionInbox.js', () => ({ CompositionInbox: () => createElement('p', null, '历史提案内容') }));
vi.mock('../web/ApplicationGovernance.js', () => ({ ApplicationGovernance: () => createElement('p', null, '应用管理内容') }));
vi.mock('../web/api.js', async importOriginal => {
  const original = await importOriginal<typeof import('../web/api.js')>();
  return { ...original, api: { ...original.api,
    status: vi.fn(), materials: vi.fn(), jobs: vi.fn(), executionTargets: vi.fn(), session: vi.fn(), applications: vi.fn(), userConnections: vi.fn(), detail: vi.fn(),
    autoresearch: { presets: vi.fn(), get: vi.fn(), recover: vi.fn(), start: vi.fn(), cancel: vi.fn() },
  } };
});
const alice: User = { id: 'alice', name: 'Alice', role: 'user' };
let host: HTMLDivElement; let root: Root;
const text = () => host.textContent ?? '';
async function render(user = alice) { await act(async () => { root.render(createElement(Workspace, { user, logout: () => {}, sessionBusy: false, sessionError: '' })); }); }
async function click(label: string) {
  const button = Array.from(host.querySelectorAll('button')).find(button => button.textContent === label);
  expect(button, `button ${label}`).toBeTruthy();
  await act(async () => { button!.click(); });
}
beforeEach(() => {
  vi.clearAllMocks(); window.history.replaceState(null, '', '/'); window.sessionStorage.clear();
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  vi.mocked(api.status).mockResolvedValue({ mode: 'demo', activeWorkers: 0, queuedJobs: 0, maxWorkers: 2 } as Awaited<ReturnType<typeof api.status>>);
  vi.mocked(api.materials).mockResolvedValue([]); vi.mocked(api.jobs).mockResolvedValue([]); vi.mocked(api.executionTargets).mockResolvedValue([]);
  vi.mocked(api.session).mockResolvedValue(alice); vi.mocked(api.applications).mockResolvedValue([]); vi.mocked(api.userConnections).mockResolvedValue([]);
  vi.mocked(personalAgentApi.sessions).mockResolvedValue([]); vi.mocked(personalAgentApi.capabilities).mockResolvedValue({ executionContract: 'personal-external-v1', nativeQueue: true }); vi.mocked(personalRemoteApi.list).mockResolvedValue([]);
  vi.mocked(openresearchApi.capabilities).mockResolvedValue({ contractVersion: 1, nativeProjectAttachment: true, upstreamProjectCreation: false, liveEndToEndVerified: false, workloads: [] }); vi.mocked(openresearchApi.projects).mockResolvedValue([]);
  vi.mocked(api.autoresearch.presets).mockResolvedValue([]); vi.mocked(api.detail).mockRejectedValue(new Error('任务不存在或无权访问'));
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); });
describe('workspace mounted application boundaries', () => {
  it('opens the catalog and places composition only in the developer entry', async () => {
    await render();
    expect(host.querySelector('h1')?.textContent).toBe('选择你的工作区');
    expect(host.querySelector('#application-selector')).toBeNull();
    expect(text()).toContain('进入 OpenResearch');
    expect(text()).not.toContain('Checksum 是开发示例'); expect(host.querySelector('.or-development-card')).toBeNull();
    await click('工具、资源与管理入口');
    await click('开发者装配');
    expect(host.querySelector('#application-selector')).not.toBeNull();
    expect(host.querySelector('nav')?.textContent).not.toContain('应用管理');
    expect(api.autoresearch.start).not.toHaveBeenCalled();
  });
  it('enters OpenResearch from the catalog without a second application selector or controlled runner', async () => {
    await render(); await click('进入 OpenResearch');
    expect(window.location.search).toContain('tab=openresearch');
    expect(host.querySelector('h1')?.textContent).toBe('OpenResearch');
    expect(host.querySelector('#application-selector')).toBeNull();
    expect(host.querySelector('#autoresearch-title')).toBeNull();
    expect(openresearchApi.projects).not.toHaveBeenCalled();
    expect(api.applications).not.toHaveBeenCalled();
    await click('Factory 应用目录');
    expect(host.querySelector('h1')?.textContent).toBe('选择你的工作区');
  });
  it('navigates to empty experimental runner and back via its actionable alternative', async () => {
    await render(); await click('开发者装配'); await click('打开受控 Auto-Research 实验');
    expect(window.location.search).toContain('tab=autoresearch');
    expect(text()).toContain('选择其他应用');
    await click('选择其他应用');
    expect(host.querySelector('#application-selector')).toBeNull();
    expect(window.location.search).toContain('tab=catalog');
    expect(api.autoresearch.start).not.toHaveBeenCalled();
  });
  it('restores a task deep link after remount and responds to Back/Forward history events without creating work', async () => {
    window.history.replaceState(null, '', '/?tab=research&task=task-one'); await render();
    expect(api.detail).toHaveBeenCalledWith('task-one', expect.any(AbortSignal));
    expect(text()).toContain('任务不存在或无权访问');
    await click('应用目录');
    await act(async () => { window.history.back(); await new Promise(resolve => setTimeout(resolve, 20)); });
    expect(host.querySelector('h1')?.textContent).toBe('任务与证据');
    await act(async () => { window.history.forward(); await new Promise(resolve => setTimeout(resolve, 20)); });
    expect(host.querySelector('h1')?.textContent).toBe('选择你的工作区');
    const href = window.location.href;
    await act(async () => root.unmount()); root = createRoot(host); await render();
    expect(window.location.href).toBe(href); expect(host.querySelector('h1')?.textContent).toBe('选择你的工作区');
    expect(api.autoresearch.start).not.toHaveBeenCalled();
  });
  it('keeps Back and Forward usable after a created research run and passive recovery', async () => {
    const preset = { id: 'preset-one', name: '受管研究', defaultGoal: '合成目标', ready: true, blockers: [], limits: { maxExperiments: 1 } };
    const record = { id: 'run-one', ownerId: 'alice', requestId: 'request-one', presetId: preset.id, goal: preset.defaultGoal, status: 'completed', steps: [], evidence: [], allowedActions: [], acceptance: { modelExecuted: false, instructionsRead: false, agentDecision: false, managedExperiment: false, independentResult: false, nextDecision: false, scientificConclusionVerified: false } };
    vi.mocked(api.autoresearch.presets).mockResolvedValue([preset]);
    vi.mocked(api.autoresearch.start).mockImplementation(async body => ({ ...record, requestId: body.requestId }));
    vi.mocked(api.autoresearch.get).mockImplementation(async () => ({ ...record, requestId: vi.mocked(api.autoresearch.start).mock.calls[0]?.[0].requestId ?? record.requestId }));
    vi.mocked(api.autoresearch.recover).mockImplementation(async requestId => ({ ...record, requestId }));
    await render(); await click('开发者装配'); await click('打开受控 Auto-Research 实验'); await click('检查默认目标'); await click('确认并开始研究');
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
    expect(window.location.search).toContain('run=run-one');
    const length = window.history.length;
    await act(async () => { window.history.back(); await new Promise(resolve => setTimeout(resolve, 20)); });
    expect(window.history.length).toBe(length);
    await act(async () => { window.history.back(); await new Promise(resolve => setTimeout(resolve, 20)); });
    expect(host.querySelector('h1')?.textContent).toBe('开发者装配');
    await act(async () => { window.history.forward(); await new Promise(resolve => setTimeout(resolve, 20)); });
    expect(host.querySelector('#autoresearch-title')).not.toBeNull();
    expect(api.autoresearch.start).toHaveBeenCalledTimes(1);
  });
  it('normalizes unauthorized admin links while preserving a manager route', async () => {
    window.history.replaceState(null, '', '/?tab=applications'); await render();
    expect(window.location.search).toContain('tab=catalog');
    await act(async () => root.unmount()); root = createRoot(host);
    window.history.replaceState(null, '', '/?tab=applications');
    const manager: User = { id: 'manager', name: 'Manager', role: 'manager' }; vi.mocked(api.session).mockResolvedValue(manager);
    await render(manager); expect(text()).toContain('应用管理内容');
    expect(host.querySelector('nav')?.textContent).toContain('管理员');
  });
});
