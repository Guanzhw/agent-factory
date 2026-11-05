// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import ResearchApp from '../web/research-composition.js';
import { api, ApiError } from '../web/api.js';
import * as auth from '../web/browserAuth.js';
import { researchApi } from '../web/apps/research/client.js';
import { assistantApi } from '../web/apps/research/live/assistantClient.js';
import { researchSessionsApi, type ResearchSession } from '../web/apps/research/researchSessionsClient.js';
import * as runs from '../web/apps/research/live/runs.js';

const date = '2026-10-29T01:00:00Z';
const session: ResearchSession = {
  id: 'session-a', assistantId: 'assistant-a', title: '合成来源会话', goal: '读取原任务', boundaries: '不执行',
  createdAt: date, updatedAt: date, state: 'idle', model: { connectionRef: 'model-a', provider: 'configured', model: 'fixture' },
  limits: { maxTurns: 8, toolCallsPerTurn: 8, operationSeconds: 8 }, context: { characters: 0, maximumCharacters: 12000 },
  allowedActions: ['start'], blockReason: null, sharedSourceIds: [], turns: [{
    id: 'turn-a', sequence: 1, requestId: 'original-request', taskId: 'task-a', runId: 'run-a', status: 'completed',
    createdAt: date, completedAt: date, result: '合成原回复', failure: null, messages: [], events: [], toolResults: [],
    children: [{ childTaskId: 'child-a', runId: 'child-run-a', goal: '原子目标', status: 'completed', result: '原子结果' }],
  }],
};
let host: HTMLDivElement; let root: Root;
const button = (label: string) => [...host.querySelectorAll('button')].find(item => item.textContent === label);
async function click(label: string) { expect(button(label)).toBeDefined(); await act(async () => button(label)!.click()); }
async function mount(url?: string) {
  if (url) window.history.replaceState(null, '', url);
  await act(async () => root.render(createElement(ResearchApp)));
}
async function restore(url: string) {
  await act(async () => { window.history.replaceState(null, '', url); window.dispatchEvent(new PopStateEvent('popstate')); });
}
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); sessionStorage.clear(); localStorage.clear();
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Unexpected request')));
  const config = auth.configureBrowserAuth({ enabled: true, oidcEnabled: false, localLoginEnabled: true, loginPath: '/api/factory/auth/login', logoutPath: '/api/factory/auth/logout' });
  vi.spyOn(auth, 'browserAuthConfig').mockResolvedValue(config);
  vi.spyOn(window, 'matchMedia').mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() } as unknown as MediaQueryList);
  vi.spyOn(api, 'session').mockResolvedValue({ id: 'alice', name: 'Alice', role: 'user' });
  vi.spyOn(api, 'status').mockRejectedValue(new Error('Synthetic status disconnected'));
  vi.spyOn(api, 'materials').mockResolvedValue([]); vi.spyOn(api, 'executionTargets').mockResolvedValue([]);
  vi.spyOn(api, 'jobs').mockResolvedValue({ items: [], nextCursor: null });
  vi.spyOn(api, 'detail').mockRejectedValue(new ApiError('合成任务读取拒绝', 403));
  vi.spyOn(api, 'controlCommands').mockResolvedValue({ items: [], nextCursor: null });
  vi.spyOn(api, 'instantiate').mockRejectedValue(new Error('Navigation must not create tasks'));
  vi.spyOn(researchApi, 'projects').mockResolvedValue({ items: [], nextCursor: null });
  vi.spyOn(assistantApi, 'me').mockResolvedValue({ assistant: null });
  vi.spyOn(researchSessionsApi, 'options').mockResolvedValue({ available: false, unavailableCode: 'RESEARCH_MODEL_REQUIRED', models: [], limits: { maxTurns: { min: 1, max: 20, default: 8 }, toolCallsPerTurn: { min: 1, max: 8, default: 8 }, operationSeconds: { min: 1, max: 30, default: 8 }, contextCharacters: 12000 }, workspace: { configured: true, hostCommands: true, isolation: 'host-user-not-os-sandbox' }, accounting: { tokenMetered: false, costMetered: false } });
  vi.spyOn(researchSessionsApi, 'list').mockResolvedValue({ items: [], nextCursor: null });
  vi.spyOn(researchSessionsApi, 'questions').mockResolvedValue({ items: [], nextCursor: null });
  vi.spyOn(researchSessionsApi, 'get').mockResolvedValue(session);
  vi.spyOn(researchSessionsApi, 'create').mockRejectedValue(new Error('Navigation must not create sessions'));
  vi.spyOn(researchSessionsApi, 'turn').mockRejectedValue(new Error('Navigation must not start turns'));
  vi.spyOn(researchSessionsApi, 'stop').mockRejectedValue(new Error('Navigation must not stop tasks'));
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it.each([['查看原任务记录', 'task-a'], ['查看原子任务记录', 'child-a']])('returns from %s to the exact session after reload and history restoration', async (label, task) => {
  const source = '/?tab=research&researchView=sessions&researchSession=session-a';
  await mount(source); await click(label);
  const taskURL = window.location.pathname + window.location.search;
  expect(new URL(window.location.href).searchParams.get('taskReturnTask')).toBe(task);
  expect(host.textContent).toContain('合成任务读取拒绝');
  expect(button('返回原研究')).toBeDefined();
  expect(host.querySelector('.runtime-strip')).toBeNull();
  expect(host.textContent).toContain('运行状态更新失败');
  await act(async () => root.unmount()); root = createRoot(host); await mount();
  await click('返回原研究');
  expect(window.location.search).toContain('researchSession=session-a');
  expect(new URL(window.location.href).searchParams.get('taskReturn')).toBeNull();
  expect(host.textContent).toContain(session.title);
  await restore(taskURL); expect(button('返回原研究')).toBeDefined();
  await restore(source); expect(host.textContent).toContain(session.title);
  expect(researchSessionsApi.create).not.toHaveBeenCalled(); expect(researchSessionsApi.turn).not.toHaveBeenCalled(); expect(researchSessionsApi.stop).not.toHaveBeenCalled();
  expect(api.instantiate).not.toHaveBeenCalled(); expect(fetch).not.toHaveBeenCalled();
});

it('records the actually selected project and evidence view at the project task entry', async () => {
  vi.spyOn(researchApi, 'project').mockResolvedValue({ id: 'project-a', ownerId: 'alice', title: '合成原项目', state: 'draft', assistantId: null, currentGoalVersion: 0, createdAt: date, ending: null, execution: { available: false, reason: 'RESEARCH_CONFIRMED_GOAL_REQUIRED' }, goals: [] });
  vi.spyOn(runs, 'readResearchRuns').mockResolvedValue({ items: [], rounds: [{ id: 'round-a', goalVersion: 1, taskId: 'project-task', terminalRecordId: null, terminal: null, decision: null }] });
  await mount('/?tab=research&project=project-a&researchTab=evidence');
  await click('查看原任务与产物');
  expect(new URL(window.location.href).searchParams.get('taskReturnTask')).toBe('project-task');
  await click('返回原研究');
  expect(window.location.search).toContain('project=project-a'); expect(window.location.search).toContain('researchTab=evidence');
  expect(host.querySelector('[aria-label="研究证据"]')).not.toBeNull(); expect(api.instantiate).not.toHaveBeenCalled();
});

it('clears the source on ordinary sidebar and task-list navigation instead of guessing from old research pointers', async () => {
  vi.mocked(api.jobs).mockResolvedValue({ items: [{ id: 'other-task', ownerId: 'alice', definitionId: 'fixture', definitionVersion: 1, input: { topic: '另一普通任务', mode: 'fixture', scenario: 'normal' }, status: 'running', createdAt: date, updatedAt: date, observedAt: date }], nextCursor: null });
  await mount('/?tab=tasks&task=task-a&taskReturn=research&taskReturnTask=task-a&researchView=sessions&researchSession=session-a&templateId=old-template&templateVersion=1&templateStart=1&scheduleId=old-schedule');
  await click('我的任务');
  expect(button('返回原研究')).toBeUndefined(); expect(button('返回我的任务')).toBeDefined();
  expect(new URL(window.location.href).searchParams.get('taskReturn')).toBeNull();
  for (const key of ['templateId', 'templateVersion', 'templateStart', 'templateReturn', 'taskReturnTask', 'scheduleId']) expect(new URL(window.location.href).searchParams.has(key)).toBe(false);
  await restore('/?tab=tasks&task=task-a&taskReturn=research&taskReturnTask=task-a&researchView=sessions&researchSession=session-a&templateId=old-template&templateVersion=1&templateStart=1');
  await act(async () => host.querySelector<HTMLButtonElement>('.task-row')!.click());
  expect(new URL(window.location.href).searchParams.get('task')).toBe('other-task');
  for (const key of ['templateId', 'templateVersion', 'templateStart', 'templateReturn', 'taskReturn', 'taskReturnTask']) expect(new URL(window.location.href).searchParams.has(key)).toBe(false);
  expect(button('返回原研究')).toBeUndefined();
  await restore('/?tab=tasks&task=task-a&taskReturn=research&taskReturnTask=task-a&researchView=sessions&researchSession=session-a');
  await click('查看全部待核对操作');
  expect(new URL(window.location.href).searchParams.get('task')).toBeNull();
  expect(new URL(window.location.href).searchParams.get('taskReturn')).toBeNull();
  await restore('/?tab=tasks&task=task-a&researchView=sessions&researchSession=session-a');
  expect(button('返回原研究')).toBeUndefined(); expect(button('返回我的任务')).toBeDefined();
});

it('does not reuse the previous member session body when a return is denied for the next member', async () => {
  await mount('/?tab=research&researchView=sessions&researchSession=session-a'); await click('查看原任务记录');
  await act(async () => root.unmount()); root = createRoot(host);
  vi.mocked(api.session).mockResolvedValue({ id: 'bob', name: 'Bob', role: 'user' });
  vi.mocked(researchSessionsApi.get).mockRejectedValue(new ApiError('原会话无权访问', 403));
  await mount(); await click('返回原研究');
  expect(host.textContent).toContain('原会话无权访问'); expect(host.textContent).not.toContain(session.title);
  expect(researchSessionsApi.get).toHaveBeenLastCalledWith('bob', 'session-a', expect.any(AbortSignal));
  expect(researchSessionsApi.turn).not.toHaveBeenCalled();
});
