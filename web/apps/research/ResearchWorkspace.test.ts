// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ApiError } from '../../api.js';
import { ResearchWorkspace } from './ResearchWorkspace.js';
import { researchApi } from './client.js';
import type { ResearchAgreement, ResearchProject } from './types.js';

let host: HTMLDivElement; let root: Root;
const onProject = vi.fn(); const onResources = vi.fn();
const agreement: ResearchAgreement = { objective: '减少错误率', evaluation: '固定评估集误差小于 0.1', stopConditions: '预算耗尽停止', resourceRefs: { gpu: 'connection:saved' }, budget: { rounds: 3, toolCalls: 8, tokenLimit: null, amountMicros: null, currency: null } };
const empty: ResearchProject = { id: 'project-1', ownerId: 'alice', title: '误差研究', assistantId: null, state: 'draft', currentGoalVersion: 0, goals: [], ending: null, createdAt: '2026-10-25T12:00:00Z', execution: { available: false, reason: 'RESEARCH_EXECUTION_NOT_INSTALLED' } };
const drafted: ResearchProject = { ...empty, currentGoalVersion: 1, goals: [{ version: 1, agreement, createdAt: empty.createdAt, confirmedAt: null }] };
const confirmed: ResearchProject = { ...drafted, state: 'ready', goals: [{ ...drafted.goals[0], confirmedAt: empty.createdAt }] };
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  onProject.mockReset(); onResources.mockReset(); window.sessionStorage.clear();
  vi.spyOn(researchApi, 'projects').mockResolvedValue({ items: [], nextCursor: null });
  vi.spyOn(researchApi, 'assistants').mockResolvedValue({ items: [{ id: 'a', ownerId: 'alice', name: '我的助手', enabled: true }, { id: 'b', ownerId: 'bob', name: '同事助手', enabled: true }], nextCursor: null });
  vi.spyOn(researchApi, 'project').mockResolvedValue(empty);
  vi.spyOn(researchApi, 'create').mockResolvedValue(empty);
  vi.spyOn(researchApi, 'goal').mockResolvedValue(drafted);
  vi.spyOn(researchApi, 'confirm').mockResolvedValue(confirmed);
  vi.spyOn(researchApi, 'end').mockResolvedValue({ ...confirmed, state: 'ended', ending: { outcome: 'not_met', reason: '已有证据不支持继续', endedAt: empty.createdAt, goalVersion: 1, resourceCleanup: 'not_observed' } });
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const button = (text: string) => [...host.querySelectorAll('button')].find(item => item.textContent === text)!;
async function mount(projectId?: string, ownerId = 'alice') { await act(async () => root.render(createElement(ResearchWorkspace, { ownerId, projectId, onProject, onResources }))); }
async function field(label: string, value: string) {
  const wrapper = [...host.querySelectorAll('label')].find(item => item.firstChild?.textContent === label)!;
  const input = wrapper.querySelector('input,textarea,select')!;
  const prototype = input.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : input.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
  await act(async () => { Object.getOwnPropertyDescriptor(prototype, 'value')!.set!.call(input, value); input.dispatchEvent(new Event(input.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true })); });
}
it('offers personal project creation and real resource navigation without a fake execution action', async () => {
  await mount(); expect(host.textContent).toContain('还没有研究项目'); expect(host.textContent).not.toContain('同事助手');
  await act(async () => button('打开资源中心').click()); expect(onResources).toHaveBeenCalledOnce();
  await field('项目名称', '新研究'); await field('关联我的助手', 'a');
  await act(async () => button('创建项目').click());
  expect(researchApi.create).toHaveBeenCalledWith('alice', { requestId: expect.any(String), title: '新研究', assistantId: 'a' });
  expect(onProject).toHaveBeenCalledWith('project-1'); expect(button('启动研究')).toBeUndefined();
});
it('saves an agreement before separate confirmation and retains the old goal when revising', async () => {
  await mount('project-1'); await field('研究目标', agreement.objective); await field('评价与达标标准', agreement.evaluation); await field('停止与放弃条件', agreement.stopConditions); await field('最多实验轮数', '3'); await field('最多工具调用', '8');
  await act(async () => button('保存研究约定').click());
  expect(researchApi.goal).toHaveBeenLastCalledWith('alice', 'project-1', { requestId: expect.any(String), expectedVersion: 0, agreement: { ...agreement, resourceRefs: {} } });
  expect(researchApi.confirm).not.toHaveBeenCalled();
  await act(async () => button('确认当前约定').click()); expect(researchApi.confirm).toHaveBeenCalledWith('alice', 'project-1', { requestId: expect.any(String), expectedVersion: 1 });
  await act(async () => button('修改目标').click()); await field('研究目标', '改为评估延迟');
  vi.mocked(researchApi.goal).mockResolvedValueOnce({ ...drafted, currentGoalVersion: 2, goals: [...confirmed.goals, { ...drafted.goals[0], version: 2, agreement: { ...agreement, objective: '改为评估延迟' } }] });
  await act(async () => button('保存研究约定').click());
  expect(vi.mocked(researchApi.goal).mock.calls[1][2]).toMatchObject({ expectedVersion: 1, agreement: { objective: '改为评估延迟' } });
  expect(host.textContent).toContain('目标版本 1'); expect(host.textContent).toContain('目标版本 2'); expect(host.textContent).toContain('减少错误率');
});
it.each([0, 408])('preserves the exact request after ambiguous HTTP %s without automatic retries', async status => {
  vi.mocked(researchApi.create).mockRejectedValueOnce(new ApiError('响应未确认', status));
  await mount(); await field('项目名称', '新研究'); await act(async () => button('创建项目').click());
  expect(researchApi.create).toHaveBeenCalledTimes(1); expect(button('创建项目').closest('fieldset')?.disabled).toBe(true); expect(onProject).not.toHaveBeenCalled();
  await act(async () => button('重试原操作').click());
  const calls = vi.mocked(researchApi.create).mock.calls; expect(calls[1]).toEqual(calls[0]); expect(onProject).toHaveBeenCalledOnce();
});
it('does not optimistically overwrite a goal on version conflict and can reload the current version', async () => {
  vi.mocked(researchApi.project).mockResolvedValue(confirmed); vi.mocked(researchApi.goal).mockRejectedValueOnce(new ApiError('版本冲突', 409, 'RESEARCH_GOAL_CONFLICT'));
  await mount('project-1'); await act(async () => button('修改目标').click()); await field('研究目标', '冲突修改'); await act(async () => button('保存研究约定').click());
  expect(host.querySelector('[role="alert"]')?.textContent).toContain('版本冲突'); expect(host.textContent).toContain('当前目标 · 版本 1'); expect(button('重试原操作')).toBeUndefined();
  vi.mocked(researchApi.project).mockResolvedValue({ ...confirmed, currentGoalVersion: 2, goals: [...confirmed.goals, { ...confirmed.goals[0], version: 2 }] });
  await act(async () => button('刷新项目详情').click()); expect(host.textContent).toContain('当前目标 · 版本 2');
});
it('keeps domain ending distinct from resource cleanup', async () => {
  vi.mocked(researchApi.project).mockResolvedValue(confirmed); await mount('project-1');
  await act(async () => button('结束研究').click()); await field('结束依据与剩余问题', '已有证据不支持继续'); await act(async () => button('保存结束理由').click());
  expect(researchApi.end).toHaveBeenCalledWith('alice', 'project-1', { requestId: expect.any(String), expectedVersion: 1, outcome: 'not_met', reason: '已有证据不支持继续' });
  expect(host.textContent).toContain('未达标结束'); expect(host.textContent).toContain('资源清理状态：尚未核对'); expect(button('修改目标')).toBeUndefined();
});
it('ignores a late private read after switching owners', async () => {
  let resolve!: (project: ResearchProject) => void;
  vi.mocked(researchApi.project).mockReturnValueOnce(new Promise(done => { resolve = done; })).mockRejectedValueOnce(new ApiError('项目不存在', 404));
  await mount('project-1'); await mount('project-1', 'bob'); await act(async () => resolve(confirmed));
  expect(host.textContent).not.toContain('误差研究'); expect(host.textContent).toContain('项目不存在');
  const signal = vi.mocked(researchApi.project).mock.calls[0][2]; expect(signal?.aborted).toBe(true);
});

it('recovers the original create payload after a full remount and keeps it isolated across owners', async () => {
  vi.mocked(researchApi.create).mockRejectedValueOnce(new ApiError('响应超时', 408));
  await mount(); await field('项目名称', 'Alice 私有研究'); await field('关联我的助手', 'a');
  await act(async () => button('创建项目').click());
  const original = vi.mocked(researchApi.create).mock.calls[0];
  await act(async () => root.unmount()); root = createRoot(host);
  await mount(undefined, 'bob');
  expect(button('重试原操作')).toBeUndefined(); expect(host.textContent).not.toContain('Alice 私有研究');
  expect(button('创建项目').closest('fieldset')?.disabled).toBe(false);
  await mount(); expect(button('创建项目').closest('fieldset')?.disabled).toBe(true);
  expect(researchApi.create).toHaveBeenCalledTimes(1);
  await act(async () => button('重试原操作').click());
  expect(vi.mocked(researchApi.create).mock.calls[1]).toEqual(original);
  expect(window.sessionStorage.length).toBe(0);
});
it('records the create intent before dispatch so leaving during an in-flight request remains recoverable', async () => {
  let resolve!: (project: ResearchProject) => void;
  vi.mocked(researchApi.create).mockReturnValueOnce(new Promise(done => { resolve = done; }));
  await mount(); await field('项目名称', '在途研究'); await act(async () => button('创建项目').click());
  expect(window.sessionStorage.length).toBe(1);
  await act(async () => root.unmount()); root = createRoot(host); await mount();
  expect(button('重试原操作')).toBeDefined(); expect(researchApi.create).toHaveBeenCalledTimes(1);
  await act(async () => resolve(empty)); expect(onProject).not.toHaveBeenCalled();
  await act(async () => button('重试原操作').click());
  expect(vi.mocked(researchApi.create).mock.calls[1]).toEqual(vi.mocked(researchApi.create).mock.calls[0]);
});
it('does not dispatch when the original request cannot be retained', async () => {
  await mount(); await field('项目名称', '不能保存原请求');
  vi.spyOn(window, 'sessionStorage', 'get').mockImplementation(() => { throw new Error('storage unavailable'); });
  await act(async () => button('创建项目').click());
  expect(researchApi.create).not.toHaveBeenCalled(); expect(host.textContent).toContain('尚未提交');
});

it('keeps an uncertain original request when a later retry is rejected by authentication', async () => {
  vi.mocked(researchApi.create).mockRejectedValueOnce(new ApiError('超时', 408)).mockRejectedValueOnce(new ApiError('需要重新登录', 401));
  await mount(); await field('项目名称', '原请求'); await act(async () => button('创建项目').click());
  await act(async () => button('重试原操作').click());
  expect(window.sessionStorage.length).toBe(1); expect(button('创建项目').closest('fieldset')?.disabled).toBe(true);
  expect(vi.mocked(researchApi.create).mock.calls[1]).toEqual(vi.mocked(researchApi.create).mock.calls[0]);
});
