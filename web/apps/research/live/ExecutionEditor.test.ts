// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '../../../api.js';
import type { ApplicationMode, FactoryApplication } from '../../../models.js';
import type { ResearchAgreement } from '../types.js';
import { ExecutionEditor } from './ExecutionEditor.js';
import { setupApi, type SetupCandidates } from './setupClient.js';
let host: HTMLDivElement; let root: Root;
const save = vi.fn(); const applications = vi.fn(); const resources = vi.fn();
const agreement: ResearchAgreement = { objective: '研究目标', evaluation: '评价', stopConditions: '停止条件', resourceRefs: {}, budget: { rounds: 3, toolCalls: 8, tokenLimit: null, amountMicros: null, currency: null } };
const workflowPin = { kind: 'workflow' as const, id: 'research-round', revision: '1', sha256: 'b'.repeat(64) };
const candidates: SetupCandidates = { workflowPin, models: [], connections: [], environments: [], experimentMaterials: [] };
const mode = { nativeComponent: workflowPin, materialRefs: [], materialChoices: {}, capabilities: [], budget: { toolCalls: 4, maxDepth: 1, maxChildren: 1, outputBytes: 4096 }, config: {}, toolOrder: [], connectionRequirements: [] };
const published: FactoryApplication = { id: 'research-published', version: 2, sha256: 'a'.repeat(64), name: '已发布研究执行', description: '', discoveryKeywords: [], defaultForDiscovery: false, defaultMode: 'research', modes: { research: mode } };
const execution = { applicationRef: { id: published.id, version: published.version, sha256: published.sha256 }, mode: 'research', materialChoices: {}, connectionRefs: {}, deadline: 1_800_000_000, perRoundCaps: { rounds: 1 as const, toolCalls: 4, tokenLimit: null, amountMicros: null, currency: null } };
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); host = document.createElement('div'); document.body.append(host); root = createRoot(host); save.mockReset(); applications.mockReset(); resources.mockReset();
  vi.spyOn(api, 'applications').mockResolvedValue([]); vi.spyOn(api, 'userConnections').mockResolvedValue([]);
  vi.spyOn(setupApi, 'candidates').mockResolvedValue(candidates);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function mount(value = agreement) { await act(async () => root.render(createElement(ExecutionEditor, { ownerId: 'alice', agreement: value, disabled: false, onSave: save, onApplications: applications, onResources: resources }))); }
const select = (label: string) => [...host.querySelectorAll('label')].find(item => item.firstChild?.textContent === label)!.querySelector('select')!;
async function field(label: string, value: string) {
  const element = [...host.querySelectorAll('label')].find(item => item.firstChild?.textContent === label)!.querySelector('input,select')!;
  const prototype = element.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
  await act(async () => { Object.getOwnPropertyDescriptor(prototype, 'value')!.set!.call(element, value); element.dispatchEvent(new Event(element.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true })); });
}
it('guides an empty catalog to the existing application publishing and resource pages without an invented default', async () => {
  await mount(); expect(host.textContent).toContain('没有兼容当前研究组件的已发布应用'); expect((host.querySelector('.rw-primary') as HTMLButtonElement).disabled).toBe(true);
  await act(async () => [...host.querySelectorAll('button')].find(item => item.textContent === '管理与发布应用')!.click()); expect(applications).toHaveBeenCalledOnce(); expect(save).not.toHaveBeenCalled();
});
it('saves the explicitly selected published pin and user bounds without starting execution', async () => {
  vi.mocked(api.applications).mockResolvedValue([published]);
  await mount(); await field('执行应用', 'research-published:2:' + 'a'.repeat(64)); await field('执行方式', 'research'); await field('研究截止时间（本地时间）', '2027-01-01T10:00'); await field('每轮工具调用上限', '4');
  await act(async () => (host.querySelector('.rw-primary') as HTMLButtonElement).click());
  expect(save).toHaveBeenCalledWith({ ...agreement, execution: { applicationRef: { id: 'research-published', version: 2, sha256: 'a'.repeat(64) }, mode: 'research', materialChoices: {}, connectionRefs: {}, deadline: new Date('2027-01-01T10:00').getTime() / 1000, perRoundCaps: { rounds: 1, toolCalls: 4, tokenLimit: null, amountMicros: null, currency: null } } });
});
it('offers only modes with the exact installed workflow pin, including kind, ID, revision and digest', async () => {
  const modes = { research: mode, experiment: { ...mode, nativeComponent: undefined },
    // A malformed response must not be accepted based only on the other pin coordinates.
    wrongKind: { ...mode, nativeComponent: { ...workflowPin, kind: 'agent' } } as unknown as ApplicationMode,
    wrongId: { ...mode, nativeComponent: { ...workflowPin, id: 'another-workflow' } },
    wrongRevision: { ...mode, nativeComponent: { ...workflowPin, revision: '2' } },
    wrongDigest: { ...mode, nativeComponent: { ...workflowPin, sha256: 'c'.repeat(64) } } };
  vi.mocked(api.applications).mockResolvedValue([{ ...published, modes }, { ...published, id: 'ordinary-app', modes: { experiment: modes.experiment } }]);
  await mount();
  expect([...select('执行应用').options].map(option => option.value)).toEqual(['', 'research-published:2:' + 'a'.repeat(64)]);
  await field('执行应用', 'research-published:2:' + 'a'.repeat(64));
  expect([...select('执行方式').options].map(option => option.value)).toEqual(['', 'research']);
  expect(select('执行方式').value).toBe('');
  expect(setupApi.candidates).toHaveBeenCalledWith('alice', expect.any(AbortSignal));
  expect(save).not.toHaveBeenCalled();
});
it('preserves an incompatible saved mode visibly without replacing it with the compatible mode', async () => {
  vi.mocked(api.applications).mockResolvedValue([{ ...published, modes: { research: mode, experiment: { ...mode, nativeComponent: undefined } } }]);
  await mount({ ...agreement, execution: { ...execution, mode: 'experiment' } });
  expect(select('执行方式').value).toBe('experiment');
  expect(host.textContent).toContain('原执行配置不兼容当前研究组件');
  expect((host.querySelector('.rw-primary') as HTMLButtonElement).disabled).toBe(true);
  await act(async () => (host.querySelector('form') as HTMLFormElement).dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
  expect(save).not.toHaveBeenCalled();
  await field('执行方式', 'research');
  expect((host.querySelector('.rw-primary') as HTMLButtonElement).disabled).toBe(false);
});
it('keeps an unavailable original application as a disabled selection and explains the empty compatible catalog', async () => {
  vi.mocked(api.applications).mockResolvedValue([{ ...published, modes: { experiment: { ...mode, nativeComponent: undefined } } }]);
  await mount({ ...agreement, execution });
  expect(select('执行应用').value).toBe('research-published:2:' + 'a'.repeat(64));
  expect(select('执行应用').selectedOptions[0].disabled).toBe(true);
  expect(host.textContent).toContain('没有兼容当前研究组件的已发布应用');
  expect((host.querySelector('.rw-primary') as HTMLButtonElement).disabled).toBe(true);
  expect(save).not.toHaveBeenCalled();
});
it('requires the current workflow candidate response before saving any published configuration', async () => {
  vi.mocked(api.applications).mockResolvedValue([published]);
  vi.mocked(setupApi.candidates).mockRejectedValue(new Error('当前研究组件读取失败'));
  await mount({ ...agreement, execution });
  expect(host.querySelector('[role=alert]')?.textContent).toBe('当前研究组件读取失败');
  expect((host.querySelector('fieldset') as HTMLFieldSetElement).disabled).toBe(true);
  await act(async () => (host.querySelector('form') as HTMLFormElement).dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
  expect(save).not.toHaveBeenCalled();
});
