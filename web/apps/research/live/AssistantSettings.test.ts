// @vitest-environment happy-dom
import { act, createElement, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ApiError } from '../../../api.js';
import { AssistantSettings } from './AssistantSettings.js';
import { assistantApi, type QASetup, type ResearchAssistant } from './assistantClient.js';
import { setupApi } from './setupClient.js';
let host: HTMLDivElement; let root: Root;
const original: ResearchAssistant = { id: 'stable-a', ownerId: 'alice', configurationRevision: 0, qa: { state: 'unconfigured' } };
const draft: QASetup = { id: 'setup-a', state: 'draft', applicationRef: null, connectionRefs: { model: 'connection-actual' }, preview: { mode: 'qa', name: '个人问答', modelConnectionRef: 'connection-actual', budget: { toolCalls: 8, maxDepth: 1, maxChildren: 1, operationSeconds: 30, outputBytes: 65536 } } };
const published: QASetup = { ...draft, state: 'published', applicationRef: { id: 'qa-published', version: 1, sha256: 'a'.repeat(64) } };
const resources = vi.fn();
function Harness({ initial = original }: { initial?: ResearchAssistant | null }) {
  const [assistant, setAssistant] = useState(initial); const [setup, setSetup] = useState('');
  return createElement(AssistantSettings, { ownerId: 'alice', assistant, setupId: setup, onSetup: setSetup, onSaved: setAssistant, onReload: () => setAssistant({ ...original, configurationRevision: 2 }), onResources: resources });
}
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); host = document.createElement('div'); document.body.append(host); root = createRoot(host); window.sessionStorage.clear(); resources.mockReset();
  vi.spyOn(setupApi, 'candidates').mockResolvedValue({ workflowPin: { kind: 'workflow', id: 'qa', revision: '1', sha256: 'a'.repeat(64) }, models: [{ reference: 'registration', model: 'my-model', provider: 'openai-compatible', available: true }], connections: [{ ref: 'connection-actual', registrationRef: 'registration', kind: 'model', capabilities: ['model:invoke'], available: true }], environments: [], experimentMaterials: [] });
  vi.spyOn(assistantApi, 'create').mockResolvedValue(original); vi.spyOn(assistantApi, 'draft').mockResolvedValue(draft); vi.spyOn(assistantApi, 'setup').mockResolvedValue(draft); vi.spyOn(assistantApi, 'publish').mockResolvedValue(published); vi.spyOn(assistantApi, 'ask').mockRejectedValue(new Error('must not call model here'));
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const button = (text: string) => [...host.querySelectorAll('button')].find(item => item.textContent === text)!;
async function field(label: string, value: string) {
  const input = [...host.querySelectorAll('label')].find(item => item.firstChild?.textContent === label)!.querySelector('input,select')!;
  const prototype = input.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
  await act(async () => { Object.getOwnPropertyDescriptor(prototype, 'value')!.set!.call(input, value); input.dispatchEvent(new Event(input.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true })); });
}
async function mount(initial: ResearchAssistant | null = original) { await act(async () => root.render(createElement(Harness, { initial }))); }
async function prepare() {
  await act(async () => button('准备新的QA配置').click()); await field('QA配置名称', '个人问答'); await field('个人模型连接', 'connection-actual');
  await act(async () => host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
}
async function allowance() {
  await act(async () => button('明确发布QA配置').click()); await act(async () => button('使用此版本设置操作额度').click());
  await field('最多回答问题数', '3'); await field('总工具操作额度', '12'); await field('每问工具操作上限', '4'); await field('问答授权截止时间', '2026-10-26T10:00');
}
it('creates only on explicit action and never sends a model question during setup', async () => {
  await mount(null); expect(assistantApi.create).not.toHaveBeenCalled(); expect(assistantApi.draft).not.toHaveBeenCalled();
  await act(async () => button('创建我的研究助手').click()); expect(assistantApi.create).toHaveBeenCalledOnce(); expect(host.textContent).toContain('stable-a'); expect(assistantApi.ask).not.toHaveBeenCalled();
});
it('uses actual model binding, separates draft/publication, and submits only operational caps', async () => {
  const configure = vi.spyOn(assistantApi, 'configure').mockResolvedValue({ ...original, configurationRevision: 1 });
  await mount(); await prepare();
  expect(assistantApi.draft).toHaveBeenCalledWith('alice', expect.objectContaining({ modelConnectionRef: 'connection-actual' })); expect(assistantApi.publish).not.toHaveBeenCalled(); expect(configure).not.toHaveBeenCalled(); expect(host.textContent).toContain('私人QA草稿');
  await allowance(); await act(async () => host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
  expect(configure).toHaveBeenCalledWith('alice', expect.objectContaining({ expectedRevision: 0, applicationRef: published.applicationRef, connectionRefs: { model: 'connection-actual' }, budget: { caps: { rounds: 3, toolCalls: 12, tokenLimit: null, amountMicros: null, currency: null }, perQuestionCaps: { rounds: 1, toolCalls: 4, tokenLimit: null, amountMicros: null, currency: null }, deadline: expect.any(Number) } }));
  expect(host.textContent).toContain('操作额度受限，token/费用未计量'); expect(assistantApi.ask).not.toHaveBeenCalled();
});
it('retains allowance inputs across CAS conflict and requires explicit confirmation of the new revision', async () => {
  const configure = vi.spyOn(assistantApi, 'configure').mockRejectedValueOnce(new ApiError('配置修订冲突', 409, 'RESEARCH_ASSISTANT_REVISION_CONFLICT')).mockResolvedValue({ ...original, configurationRevision: 3 });
  await mount(); await prepare(); await allowance();
  await act(async () => host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
  const first = configure.mock.calls[0][1]; expect(host.textContent).toContain('配置修订冲突');
  await act(async () => button('读取最新助手配置').click()); expect(configure).toHaveBeenCalledOnce(); expect((host.querySelector('input[type=number]') as HTMLInputElement).value).toBe('3'); expect(button('按修订 2 确认问答配置')).toBeDefined();
  await act(async () => host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
  expect(configure.mock.calls[1][1].expectedRevision).toBe(2); expect(configure.mock.calls[1][1].budget).toEqual(first.budget); expect(configure.mock.calls[1][1].requestId).not.toBe(first.requestId);
});
it('shows missing real model connections and links to the existing resource entry', async () => {
  vi.mocked(setupApi.candidates).mockResolvedValue({ workflowPin: { kind: 'workflow', id: 'qa', revision: '1', sha256: 'a'.repeat(64) }, models: [], connections: [], environments: [], experimentMaterials: [] });
  await mount(); await act(async () => button('准备新的QA配置').click()); expect(button('保存私人QA草稿').disabled).toBe(true); expect(host.textContent).toContain('缺少可用模型连接');
  await act(async () => button('配置我的模型与资源').click()); expect(resources).toHaveBeenCalledOnce(); expect(assistantApi.draft).not.toHaveBeenCalled();
});
