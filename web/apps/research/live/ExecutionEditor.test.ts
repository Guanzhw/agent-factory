// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '../../../api.js';
import type { ResearchAgreement } from '../types.js';
import { ExecutionEditor } from './ExecutionEditor.js';
let host: HTMLDivElement; let root: Root;
const save = vi.fn(); const applications = vi.fn(); const resources = vi.fn();
const agreement: ResearchAgreement = { objective: '研究目标', evaluation: '评价', stopConditions: '停止条件', resourceRefs: {}, budget: { rounds: 3, toolCalls: 8, tokenLimit: null, amountMicros: null, currency: null } };
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); host = document.createElement('div'); document.body.append(host); root = createRoot(host); save.mockReset(); applications.mockReset(); resources.mockReset();
  vi.spyOn(api, 'applications').mockResolvedValue([]); vi.spyOn(api, 'userConnections').mockResolvedValue([]);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function mount() { await act(async () => root.render(createElement(ExecutionEditor, { agreement, disabled: false, onSave: save, onApplications: applications, onResources: resources }))); }
async function field(label: string, value: string) {
  const element = [...host.querySelectorAll('label')].find(item => item.firstChild?.textContent === label)!.querySelector('input,select')!;
  const prototype = element.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
  await act(async () => { Object.getOwnPropertyDescriptor(prototype, 'value')!.set!.call(element, value); element.dispatchEvent(new Event(element.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true })); });
}
it('guides an empty catalog to the existing application publishing and resource pages without an invented default', async () => {
  await mount(); expect(host.textContent).toContain('尚无可选的已发布应用'); expect((host.querySelector('.rw-primary') as HTMLButtonElement).disabled).toBe(true);
  await act(async () => [...host.querySelectorAll('button')].find(item => item.textContent === '管理与发布应用')!.click()); expect(applications).toHaveBeenCalledOnce(); expect(save).not.toHaveBeenCalled();
});
it('saves the explicitly selected published pin and user bounds without starting execution', async () => {
  vi.mocked(api.applications).mockResolvedValue([{ id: 'research-published', version: 2, sha256: 'a'.repeat(64), name: '已发布研究执行', description: '', discoveryKeywords: [], defaultForDiscovery: false, defaultMode: 'research', modes: { research: { materialRefs: [], materialChoices: {}, capabilities: [], budget: { toolCalls: 4, maxDepth: 1, maxChildren: 1, outputBytes: 4096 }, config: {}, toolOrder: [], connectionRequirements: [] } } }]);
  await mount(); await field('执行应用', 'research-published:2:' + 'a'.repeat(64)); await field('执行方式', 'research'); await field('研究截止时间（本地时间）', '2027-01-01T10:00'); await field('每轮工具调用上限', '4');
  await act(async () => (host.querySelector('.rw-primary') as HTMLButtonElement).click());
  expect(save).toHaveBeenCalledWith({ ...agreement, execution: { applicationRef: { id: 'research-published', version: 2, sha256: 'a'.repeat(64) }, mode: 'research', materialChoices: {}, connectionRefs: {}, deadline: new Date('2027-01-01T10:00').getTime() / 1000, perRoundCaps: { rounds: 1, toolCalls: 4, tokenLimit: null, amountMicros: null, currency: null } } });
});
