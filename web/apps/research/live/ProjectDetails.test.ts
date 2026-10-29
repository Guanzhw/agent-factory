// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '../../../api.js';
import { researchApi } from '../client.js';
import { clearSessionDrafts } from '../researchSessionStorage.js';
import type { ResearchProject } from '../types.js';
import type { FactoryApplication } from '../../../models.js';
import { ProjectDetails } from './ProjectDetails.js';
import { setupApi, type ResearchSetup, type SetupCandidates } from './setupClient.js';

let host: HTMLDivElement; let root: Root;
const onResources = vi.fn(); const onSetup = vi.fn(); const onUpdate = vi.fn();
const project: ResearchProject = { id: 'project-a', ownerId: 'alice', title: '未完成的配置', state: 'draft', assistantId: null, currentGoalVersion: 1, createdAt: '2026-10-25T12:00:00Z', ending: null, execution: { available: false, reason: 'RESEARCH_EXECUTION_CONFIGURATION_REQUIRED' }, goals: [{ version: 1, createdAt: '2026-10-25T12:00:00Z', confirmedAt: null, agreement: { objective: '核对结果', evaluation: '通过测试', stopConditions: '结果未知时核对原任务', resourceRefs: {}, budget: { rounds: 3, toolCalls: 8, tokenLimit: null, amountMicros: null, currency: null } } }] };
const candidates: SetupCandidates = { workflowPin: { kind: 'workflow', id: 'research-round', revision: '1', sha256: 'b'.repeat(64) }, models: [], connections: [], environments: [], experimentMaterials: [] };
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); sessionStorage.clear(); onResources.mockReset(); onSetup.mockReset(); onUpdate.mockReset();
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  vi.spyOn(api, 'applications').mockResolvedValue([]); vi.spyOn(api, 'userConnections').mockResolvedValue([]); vi.spyOn(setupApi, 'candidates').mockResolvedValue(candidates);
  vi.spyOn(setupApi, 'read'); vi.spyOn(setupApi, 'draft'); vi.spyOn(setupApi, 'publish'); vi.spyOn(researchApi, 'goal'); vi.spyOn(researchApi, 'start');
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function mount(value = project, setupId?: string) { await act(async () => root.render(createElement(ProjectDetails, { project: value, setupId, tab: 'overview', onTab: vi.fn(), onUpdate, onTask: vi.fn(), onApplications: vi.fn(), onResources, onSetup, onMaterials: vi.fn(), onDelivery: vi.fn() }))); }
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

const toolPin = { id: 'experiment-tool', version: 1, sha256: 'a'.repeat(64) };
const applicationPin = { id: 'published-research', version: 1, sha256: 'c'.repeat(64) };
const savedSetup: ResearchSetup = { id: 'explicit-setup-b', state: 'draft', applicationRef: null, connectionRefs: { model: 'actual-model' }, materialRefs: [], preview: { name: '明确指定的配置B', modelConnectionRef: 'actual-model', environment: { adapterId: 'local-environment', revision: '1' }, experimentMaterialRefs: [toolPin], connectionRefs: {}, workflowPin: candidates.workflowPin, budget: { toolCalls: 8, maxDepth: 2, maxChildren: 4, operationSeconds: 8, outputBytes: 65536 } } };
async function field(label: string, value: string) {
  const element = [...host.querySelectorAll('label')].find(item => item.firstChild?.textContent === label)!.querySelector('input,select')!;
  const prototype = element.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
  await act(async () => { Object.getOwnPropertyDescriptor(prototype, 'value')!.set!.call(element, value); element.dispatchEvent(new Event(element.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true })); });
}
it('opens an explicit setup target instead of the previous generic execution view after navigation and refresh', async () => {
  vi.mocked(setupApi.read).mockImplementation(async (_owner, id) => ({ ...savedSetup, id, preview: { ...savedSetup.preview, name: `指定配置 ${id}` } }));
  await mount(); await act(async () => button('配置研究执行').click());
  expect(host.querySelector('form[aria-label="执行配置"]')).not.toBeNull();
  await act(async () => root.render(null)); await mount(project, 'explicit-setup-b');
  expect(setupApi.read).toHaveBeenCalledWith('alice', 'explicit-setup-b', expect.any(AbortSignal));
  expect(host.textContent).toContain('指定配置 explicit-setup-b'); expect(host.querySelector('form[aria-label="执行配置"]')).toBeNull();
  await mount(project, 'explicit-setup-c');
  expect(setupApi.read).toHaveBeenCalledWith('alice', 'explicit-setup-c', expect.any(AbortSignal)); expect(host.textContent).toContain('指定配置 explicit-setup-c');
  await act(async () => root.render(null)); await mount(project, 'explicit-setup-c');
  expect(host.textContent).toContain('指定配置 explicit-setup-c'); expect(setupApi.draft).not.toHaveBeenCalled(); expect(setupApi.publish).not.toHaveBeenCalled(); expect(researchApi.start).not.toHaveBeenCalled();
});
it('keeps the draft to publication to selected execution journey across setup route changes and resource return', async () => {
  const publishedSetup: ResearchSetup = { ...savedSetup, state: 'published', applicationRef: applicationPin, materialRefs: [toolPin] };
  const available: SetupCandidates = { ...candidates, models: [{ reference: 'model-registration', provider: 'provider', model: 'test-model', available: true }], connections: [{ ref: 'actual-model', registrationRef: 'model-registration', kind: 'model-provider', capabilities: [], available: true }], environments: [{ adapterId: 'local-environment', revision: '1', connectionKind: null, requiredCapabilities: [] }], experimentMaterials: [{ ...toolPin, name: '实验工具', available: true, connectionRequirements: [] }] };
  const application: FactoryApplication = { ...applicationPin, name: '已发布研究配置', description: '', discoveryKeywords: [], defaultForDiscovery: false, defaultMode: 'research', modes: { research: { nativeComponent: candidates.workflowPin, materialRefs: [], materialChoices: {}, capabilities: [], budget: { toolCalls: 8, maxDepth: 2, maxChildren: 4, outputBytes: 65536 }, config: {}, toolOrder: [], connectionRequirements: [] } } };
  vi.mocked(setupApi.candidates).mockResolvedValue(available); vi.mocked(setupApi.draft).mockResolvedValue(savedSetup); vi.mocked(setupApi.publish).mockResolvedValue(publishedSetup);
  vi.mocked(setupApi.read).mockResolvedValue(savedSetup); vi.mocked(api.applications).mockResolvedValue([application]);
  vi.mocked(researchApi.goal).mockImplementation(async (_owner, _id, command) => ({ ...project, currentGoalVersion: 2, goals: [...project.goals, { version: 2, agreement: command.agreement, createdAt: '2026-10-29T00:00:00Z', confirmedAt: null }] }));
  const route: { project: ResearchProject; setupId?: string } = { project };
  function renderRoute() { root.render(createElement(ProjectDetails, { project: route.project, setupId: route.setupId, tab: 'overview', onTab: vi.fn(), onUpdate: value => { onUpdate(value); route.project = value; renderRoute(); }, onSetup: id => { onSetup(id); route.setupId = id; renderRoute(); }, onTask: vi.fn(), onApplications: vi.fn(), onResources, onMaterials: vi.fn(), onDelivery: vi.fn() })); }
  await act(async () => renderRoute()); await prepare(); await field('已保存模型连接', 'actual-model'); await field('运行环境', 'local-environment:1');
  await act(async () => (host.querySelector('input[type=checkbox]') as HTMLInputElement).click());
  await act(async () => button('保存私人配置草稿').click());
  expect(route.setupId).toBe('explicit-setup-b'); expect(host.textContent).toContain('私人草稿 · 尚未发布'); expect(setupApi.draft).toHaveBeenCalledOnce(); expect(setupApi.publish).not.toHaveBeenCalled();
  await act(async () => button('发布研究执行配置').click()); expect(setupApi.publish).toHaveBeenCalledOnce(); expect(researchApi.goal).not.toHaveBeenCalled();
  await act(async () => button('用于当前研究约定').click());
  expect(host.querySelector('form[aria-label="执行配置"]')).not.toBeNull();
  await field('研究截止时间（本地时间）', '2027-01-01T10:00'); await field('每轮工具调用上限', '5');
  await act(async () => button('配置模型与资源').click()); await act(async () => root.render(null)); await act(async () => renderRoute());
  expect(host.querySelector('form[aria-label="执行配置"]')).not.toBeNull();
  expect([...host.querySelectorAll('input')].map(input => input.value)).toContain('2027-01-01T10:00'); expect([...host.querySelectorAll('input')].map(input => input.value)).toContain('5');
  expect(setupApi.draft).toHaveBeenCalledOnce(); expect(setupApi.publish).toHaveBeenCalledOnce(); expect(researchApi.goal).not.toHaveBeenCalled();
  await act(async () => button('保存配置并生成待确认版本').click());
  expect(researchApi.goal).toHaveBeenCalledWith('alice', 'project-a', expect.objectContaining({ expectedVersion: 1, agreement: expect.objectContaining({ execution: expect.objectContaining({ applicationRef: applicationPin, connectionRefs: { model: 'actual-model' }, perRoundCaps: expect.objectContaining({ toolCalls: 5 }) }) }) }));
  expect(route.project.currentGoalVersion).toBe(2); expect(route.setupId).toBe(''); expect(host.querySelector('form[aria-label="执行配置"]')).toBeNull();
  expect(button('确认当前约定')).toBeDefined(); expect(researchApi.start).not.toHaveBeenCalled();
});
