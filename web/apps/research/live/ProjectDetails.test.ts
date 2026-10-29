// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '../../../api.js';
import { researchApi } from '../client.js';
import { clearSessionDrafts } from '../researchSessionStorage.js';
import type { ResearchProject } from '../types.js';
import { ProjectDetails } from './ProjectDetails.js';
import { setupApi, type SetupCandidates } from './setupClient.js';

let host: HTMLDivElement; let root: Root;
const onResources = vi.fn(); const onSetup = vi.fn(); const onUpdate = vi.fn();
const project: ResearchProject = { id: 'project-a', ownerId: 'alice', title: '未完成的配置', state: 'draft', assistantId: null, currentGoalVersion: 1, createdAt: '2026-10-25T12:00:00Z', ending: null, execution: { available: false, reason: 'RESEARCH_EXECUTION_CONFIGURATION_REQUIRED' }, goals: [{ version: 1, createdAt: '2026-10-25T12:00:00Z', confirmedAt: null, agreement: { objective: '核对结果', evaluation: '通过测试', stopConditions: '结果未知时核对原任务', resourceRefs: {}, budget: { rounds: 3, toolCalls: 8, tokenLimit: null, amountMicros: null, currency: null } } }] };
const candidates: SetupCandidates = { workflowPin: { kind: 'workflow', id: 'research-round', revision: '1', sha256: 'b'.repeat(64) }, models: [], connections: [], environments: [], experimentMaterials: [] };
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); sessionStorage.clear(); onResources.mockReset(); onSetup.mockReset(); onUpdate.mockReset();
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  vi.spyOn(api, 'applications').mockResolvedValue([]); vi.spyOn(api, 'userConnections').mockResolvedValue([]); vi.spyOn(setupApi, 'candidates').mockResolvedValue(candidates);
  vi.spyOn(setupApi, 'draft'); vi.spyOn(setupApi, 'publish'); vi.spyOn(researchApi, 'goal'); vi.spyOn(researchApi, 'start');
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function mount(value = project) { await act(async () => root.render(createElement(ProjectDetails, { project: value, tab: 'overview', onTab: vi.fn(), onUpdate, onTask: vi.fn(), onApplications: vi.fn(), onResources, onSetup, onMaterials: vi.fn(), onDelivery: vi.fn() }))); }
const button = (text: string) => [...host.querySelectorAll('button')].find(item => item.textContent === text)!;
const name = () => host.querySelector<HTMLInputElement>('input[maxlength="120"]');
async function prepare() {
  await act(async () => button('配置研究执行').click());
  await act(async () => button('准备新的研究执行配置').click());
  await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(name()!, '等模型补齐后继续'); name()!.dispatchEvent(new Event('input', { bubbles: true })); });
}
it('returns to the unfinished preparation view and inputs without publishing or starting', async () => {
  await mount(); await prepare(); await act(async () => button('配置模型与资源').click());
  expect(onResources).toHaveBeenCalledOnce();
  await act(async () => root.render(null)); await mount();
  expect(button('选择已有发布版本')).toBeDefined(); expect(name()?.value).toBe('等模型补齐后继续');
  expect(setupApi.draft).not.toHaveBeenCalled(); expect(setupApi.publish).not.toHaveBeenCalled(); expect(researchApi.goal).not.toHaveBeenCalled(); expect(researchApi.start).not.toHaveBeenCalled();
});
it('does not open another project or goal version using a previous project preparation draft', async () => {
  await mount(); await prepare();
  await mount({ ...project, id: 'project-b' }); expect(name()).toBeNull();
  await mount({ ...project, currentGoalVersion: 2, goals: project.goals.map(goal => ({ ...goal, version: 2 })) }); expect(name()).toBeNull();
  await mount(); expect(name()?.value).toBe('等模型补齐后继续');
  clearSessionDrafts('alice'); await act(async () => root.render(null)); await mount(); expect(name()).toBeNull();
});

it('leaves the previous setup pointer after saving a new goal version without starting it', async () => {
  const revised = { ...project, currentGoalVersion: 2, goals: project.goals.map(goal => ({ ...goal, version: 2 })) };
  vi.mocked(researchApi.goal).mockResolvedValue(revised);
  await mount(); await act(async () => button('修改目标').click());
  await act(async () => button('保存研究约定').click());
  expect(onSetup).toHaveBeenCalledWith(''); expect(onUpdate).toHaveBeenCalledWith(revised); expect(researchApi.start).not.toHaveBeenCalled();
});
