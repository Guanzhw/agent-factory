// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { assistantApi } from './assistantClient.js';
import { researchApi } from '../client.js';
import type { ResearchProject, VisibleResearchGoal } from '../types.js';
import { ResearchWorkbench } from '../ResearchWorkspace.js';
import type { WorkspaceRoute } from '../../../workspaceNavigation.js';
vi.mock('../ResearchSessions.js', () => ({ ResearchSessions: ({ onSelect, navigation, sessionError, workspaceContent }: { onSelect: (id: string) => void; navigation: import('react').ReactNode; sessionError: string; workspaceContent?: import('react').ReactNode }) => createElement('div', null, navigation, sessionError && createElement('p', { role: 'alert' }, sessionError), workspaceContent ?? createElement('button', { onClick: () => onSelect('session-a') }, 'autonomous-work')) }));
let host: HTMLDivElement; let root: Root;
const navigate = vi.fn(); const logout = vi.fn();
const project: Omit<ResearchProject, 'goals'> & { goals: VisibleResearchGoal[] } = { id: 'p1', ownerId: 'alice', title: '真实接口研究', state: 'ready', assistantId: 'assistant-a', currentGoalVersion: 1, createdAt: '2026-10-25T12:00:00Z', ending: null, execution: { available: true, reason: null }, goals: [{ version: 1, createdAt: '2026-10-25T12:00:00Z', confirmedAt: '2026-10-25T12:01:00Z', agreement: { objective: '降低误差', evaluation: '固定评估数据', stopConditions: '预算用尽停止', resourceRefs: {}, budget: { rounds: 3, toolCalls: 8, tokenLimit: null, amountMicros: null, currency: null }, execution: { applicationRef: { id: 'published', version: 2, sha256: 'a'.repeat(64) }, mode: 'test', materialChoices: {}, connectionRefs: {}, deadline: 1793000000, perRoundCaps: { rounds: 1, toolCalls: 4, tokenLimit: null, amountMicros: null, currency: null } } } }] };

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.spyOn(window, 'matchMedia').mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() } as unknown as MediaQueryList);
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  navigate.mockReset(); logout.mockReset();
  vi.spyOn(researchApi, 'projects').mockResolvedValue({ items: [project], nextCursor: null });
  vi.spyOn(researchApi, 'project').mockResolvedValue(project);
  vi.spyOn(assistantApi, 'me').mockResolvedValue({ assistant: null });
  vi.spyOn(researchApi, 'create'); vi.spyOn(researchApi, 'goal'); vi.spyOn(researchApi, 'start');
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const button = (label: string) => [...host.querySelectorAll('button')].find(item => item.textContent === label)!;
async function mount(route: Partial<WorkspaceRoute> = {}, busy = false, error = '') { await act(async () => root.render(createElement(ResearchWorkbench, { user: { id: 'alice', name: 'alice', role: 'user' }, route: { tab: 'research', task: '', ...route }, navigate, onLogout: logout, sessionBusy: busy, sessionError: error }))); }
it('has one autonomous work entry by default and resolves old session links to it', async () => {
  await mount(); expect(button('autonomous-work')).toBeDefined();
  expect(researchApi.projects).not.toHaveBeenCalled(); expect(button('新建项目')).toBeUndefined(); expect(button('返回平台')).toBeUndefined();
  await act(async () => button('autonomous-work').click()); expect(navigate).toHaveBeenLastCalledWith(expect.objectContaining({ researchSession: 'session-a', researchView: '', project: '' }));
  await mount({ researchView: 'sessions', researchSession: 'session-a' }); expect(button('autonomous-work')).toBeDefined();
});
it('retains project history and exact project resource context without starting or editing a workflow', async () => {
  await mount({ project: 'p1', researchSetup: 'old-setup' }); expect(host.textContent).toContain(project.title);
  expect(button('修改目标')).toBeUndefined(); expect(button('配置研究执行')).toBeUndefined(); expect(host.querySelector('form')).toBeNull();
  await act(async () => button('设置').click()); expect(navigate).toHaveBeenLastCalledWith({ tab: 'resources', modelReturn: 'research', project: 'p1' });
  expect(researchApi.create).not.toHaveBeenCalled(); expect(researchApi.goal).not.toHaveBeenCalled(); expect(researchApi.start).not.toHaveBeenCalled();
});
it('loads actual history only when requested and displays read failures honestly', async () => {
  await mount({ researchView: 'history' }); expect(host.textContent).toContain(project.title); expect(button('autonomous-work')).toBeUndefined();
  vi.mocked(researchApi.projects).mockRejectedValue(new Error('history unavailable'));
  await act(async () => button('刷新项目').click()); expect(host.textContent).toContain('history unavailable');
});
it('preserves logout failure and pending status', async () => {
  await mount({}, true, 'logout failed'); await act(async () => (host.querySelector('.rw-identity > button') as HTMLButtonElement).click());
  expect(host.querySelector('[role="alert"]')?.textContent).toBe('logout failed'); expect(button('正在退出…').disabled).toBe(true); expect(logout).not.toHaveBeenCalled();
});
it('does not reveal withdrawn project bodies', async () => {
  vi.mocked(researchApi.project).mockResolvedValue({ ...project, sourceUnavailable: true, goals: [{ version: 1, confirmedAt: null, sourceUnavailable: true }] });
  await mount({ project: 'p1' }); expect(host.textContent).toContain('来源不可用'); expect(host.textContent).not.toContain(project.goals[0].agreement.objective);
});
