// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ApiError } from '../../../api.js';
import { researchApi } from '../client.js';
import type { ResearchProject } from '../types.js';
import { ResearchWorkbench } from './ResearchWorkbench.js';

let host: HTMLDivElement; let root: Root;
const navigate = vi.fn(); const logout = vi.fn();
const project: ResearchProject = { id: 'p1', ownerId: 'alice', title: '真实接口研究', state: 'ready', assistantId: 'assistant-a', currentGoalVersion: 1, createdAt: '2026-10-25T12:00:00Z', ending: null, execution: { available: true, reason: null }, goals: [{ version: 1, createdAt: '2026-10-25T12:00:00Z', confirmedAt: '2026-10-25T12:01:00Z', agreement: { objective: '降低误差', evaluation: '固定评估数据', stopConditions: '预算用尽停止', resourceRefs: {}, budget: { rounds: 3, toolCalls: 8, tokenLimit: null, amountMicros: null, currency: null }, execution: { applicationRef: { id: 'published', version: 2, sha256: 'a'.repeat(64) }, mode: 'test', materialChoices: {}, connectionRefs: {}, deadline: 1793000000, perRoundCaps: { rounds: 1, toolCalls: 4, tokenLimit: null, amountMicros: null, currency: null } } } }] };
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); window.sessionStorage.clear();
  vi.spyOn(window, 'matchMedia').mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() } as unknown as MediaQueryList);
  vi.spyOn(HTMLDialogElement.prototype, 'showModal').mockImplementation(function (this: HTMLDialogElement) { this.open = true; });
  vi.spyOn(HTMLDialogElement.prototype, 'close').mockImplementation(function (this: HTMLDialogElement) { this.open = false; });
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  navigate.mockReset(); logout.mockReset();
  vi.spyOn(researchApi, 'projects').mockResolvedValue({ items: [], nextCursor: null });
  vi.spyOn(researchApi, 'project').mockResolvedValue(project);
  vi.spyOn(researchApi, 'assistants').mockResolvedValue({ items: [], nextCursor: null });
  vi.spyOn(researchApi, 'create').mockResolvedValue(project);
  vi.spyOn(researchApi, 'goal').mockResolvedValue(project);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const button = (label: string) => [...host.querySelectorAll('button')].find(item => item.textContent === label)!;
async function mount(id = '', owner = 'alice', sessionBusy = false, sessionError = '') { await act(async () => root.render(createElement(ResearchWorkbench, { key: owner, user: { id: owner, name: owner, role: 'user' }, route: { tab: 'research', task: '', project: id }, navigate, onLogout: logout, sessionBusy, sessionError }))); }
async function field(label: string, value: string) {
  const wrapper = [...host.querySelectorAll('label')].find(item => item.firstChild?.textContent === label)!;
  const input = wrapper.querySelector('input,textarea')!;
  const prototype = input.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  await act(async () => { Object.getOwnPropertyDescriptor(prototype, 'value')!.set!.call(input, value); input.dispatchEvent(new Event('input', { bubbles: true })); });
}
it('uses the real empty list and resource entry without importing demo projects or replies', async () => {
  await mount(); expect(host.textContent).toContain('还没有研究项目'); expect(host.textContent).not.toContain('小模型推理加速'); expect(host.querySelector('canvas')).toBeNull();
  await act(async () => button('配置模型与资源').click()); expect(navigate).toHaveBeenLastCalledWith({ tab: 'resources', modelReturn: 'research' });
  await act(async () => button('返回平台').click()); expect(navigate).toHaveBeenLastCalledWith(expect.objectContaining({ tab: 'catalog', project: '', modelReturn: '' }));
});
it('preserves a timed-out create through dialog remount and owner change using the exact original request', async () => {
  vi.mocked(researchApi.create).mockRejectedValueOnce(new ApiError('未确认', 408));
  await mount(); await act(async () => button('新建项目').click()); await field('项目名称', '请求保留'); await act(async () => button('创建项目').click());
  const first = vi.mocked(researchApi.create).mock.calls[0];
  await mount('', 'bob'); await act(async () => button('新建项目').click()); expect(button('重试原操作')).toBeUndefined();
  await mount(); await act(async () => button('新建项目').click()); await act(async () => button('重试原操作').click());
  expect(vi.mocked(researchApi.create).mock.calls[1]).toEqual(first);
});
it('keeps execution configuration when revising the visible agreement and sends its goal version', async () => {
  await mount('p1'); expect(host.textContent).toContain('来源：项目 p1 · 目标版本 1');
  await act(async () => button('修改目标').click()); await field('研究目标', '修改后的目标'); await act(async () => button('保存研究约定').click());
  expect(researchApi.goal).toHaveBeenCalledWith('alice', 'p1', expect.objectContaining({ expectedVersion: 1, agreement: expect.objectContaining({ objective: '修改后的目标', execution: project.goals[0].agreement.execution }) }));
});
it('shows read errors as errors rather than an empty research space', async () => {
  vi.mocked(researchApi.projects).mockRejectedValue(new ApiError('暂时不可读取', 503)); await mount();
  expect(host.querySelector('[role="alert"]')?.textContent).toContain('暂时不可读取'); expect(host.textContent).not.toContain('还没有研究项目');
});
it('keeps platform logout feedback and busy state in the application view', async () => {
  await mount('', 'alice', true, '退出失败'); await act(async () => (host.querySelector('.rw-identity > button') as HTMLButtonElement).click());
  expect(host.querySelector('[role="alert"]')?.textContent).toBe('退出失败'); expect(button('正在退出…').disabled).toBe(true); expect(logout).not.toHaveBeenCalled();
});
