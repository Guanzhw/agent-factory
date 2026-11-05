// @vitest-environment happy-dom
import { act, createElement, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ApiError } from '../../../api.js';
import { AssistantSettings } from './AssistantSettings.js';
import { assistantApi, type QASetup, type ResearchAssistant } from './assistantClient.js';
import { setupApi, type SetupCandidates } from './setupClient.js';
let host: HTMLDivElement; let root: Root;
const original: ResearchAssistant = { id: 'stable-a', ownerId: 'alice', configurationRevision: 0, qa: { state: 'unconfigured' } };
const draft: QASetup = { id: 'setup-a', state: 'draft', applicationRef: null, connectionRefs: { model: 'connection-actual' }, preview: { mode: 'qa', name: '个人问答', modelConnectionRef: 'connection-actual', budget: { toolCalls: 8, maxDepth: 1, maxChildren: 1, operationSeconds: 30, outputBytes: 65536 } } };
const published: QASetup = { ...draft, state: 'published', applicationRef: { id: 'qa-published', version: 1, sha256: 'a'.repeat(64) } };
const caps = { rounds: 3, toolCalls: 12, tokenLimit: null, amountMicros: null, currency: null };
const budget = { caps, perQuestionCaps: { ...caps, rounds: 1, toolCalls: 4 }, deadline: new Date('2099-10-26T10:00').getTime() / 1000 };
const configured: ResearchAssistant = { ...original, configurationRevision: 1, qa: { state: 'configured', endpointId: 'e', scopeId: 's', available: true, applicationRef: published.applicationRef!, connectionRefs: published.connectionRefs, budget, accounting: { mode: 'operational_limits_only', tokenMetered: false, costMetered: false, notice: '操作额度受限，token/费用未计量' } } };
const configKey = 'factory:research-assistant-config:alice';
const candidates: SetupCandidates = { workflowPin: { kind: 'workflow', id: 'qa', revision: '1', sha256: 'a'.repeat(64) }, qaMinimumToolCalls: 2, models: [{ reference: 'registration', model: 'my-model', provider: 'openai-compatible', available: true }], connections: [{ ref: 'connection-actual', registrationRef: 'registration', kind: 'model', capabilities: ['model:invoke'], available: true }], environments: [], experimentMaterials: [] };
const resources = vi.fn();
function Harness({ initial = original, ownerId = 'alice', initialSetupId = '' }: { initial?: ResearchAssistant | null; ownerId?: string; initialSetupId?: string }) {
  const [assistant, setAssistant] = useState(initial); const [setup, setSetup] = useState(initialSetupId);
  return createElement(AssistantSettings, { ownerId, assistant, setupId: setup, onSetup: setSetup, onSaved: setAssistant, onReload: () => setAssistant({ ...original, configurationRevision: 2 }), onResources: resources });
}
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); host = document.createElement('div'); document.body.append(host); root = createRoot(host); window.sessionStorage.clear(); resources.mockReset();
  vi.spyOn(setupApi, 'candidates').mockResolvedValue(candidates);
  vi.spyOn(assistantApi, 'create').mockResolvedValue(original); vi.spyOn(assistantApi, 'draft').mockResolvedValue(draft); vi.spyOn(assistantApi, 'setup').mockResolvedValue(published); vi.spyOn(assistantApi, 'publish').mockResolvedValue(published); vi.spyOn(assistantApi, 'configure').mockResolvedValue(configured); vi.spyOn(assistantApi, 'ask').mockRejectedValue(new Error('must not call model here'));
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const button = (text: string) => [...host.querySelectorAll('button')].find(item => item.textContent === text)!;
const input = (label: string) => [...host.querySelectorAll('label')].find(item => item.firstChild?.textContent === label)!.querySelector('input,select') as HTMLInputElement | HTMLSelectElement;
async function field(label: string, value: string) {
  const target = input(label); const prototype = target.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
  await act(async () => { Object.getOwnPropertyDescriptor(prototype, 'value')!.set!.call(target, value); target.dispatchEvent(new Event(target.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true })); });
}
async function mount(initial: ResearchAssistant | null = original, ownerId = 'alice', initialSetupId = '') { await act(async () => root.render(createElement(Harness, { initial, ownerId, initialSetupId }))); }
async function remount(initial: ResearchAssistant | null = original, ownerId = 'alice', setupId = '') { await act(async () => root.unmount()); root = createRoot(host); await mount(initial, ownerId, setupId); }
async function allowance() {
  await field('个人模型连接', 'connection-actual'); await field('最多回答问题数', '3'); await field('总工具操作额度', '12'); await field('每问工具操作上限', '4'); await field('问答授权截止时间', '2099-10-26T10:00');
}
async function submit() { await act(async () => host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))); }

it('enables exact QA publication and finite consent in one action, without calling a model', async () => {
  await mount(null); expect(assistantApi.create).not.toHaveBeenCalled(); expect(assistantApi.draft).not.toHaveBeenCalled(); expect(assistantApi.configure).not.toHaveBeenCalled();
  await allowance(); await submit();
  const id = vi.mocked(assistantApi.create).mock.calls[0][1].requestId.replace(/:assistant$/, '');
  expect(assistantApi.draft).toHaveBeenCalledWith('alice', expect.objectContaining({ requestId: id + ':draft', modelConnectionRef: 'connection-actual', budget: { ...draft.preview.budget, toolCalls: 4 } }));
  expect(assistantApi.publish).toHaveBeenCalledWith('alice', 'setup-a', { requestId: id + ':publish' });
  expect(assistantApi.configure).toHaveBeenCalledWith('alice', { requestId: id + ':configure', expectedRevision: 0, applicationRef: published.applicationRef, connectionRefs: { model: 'connection-actual' }, budget, associations: { enabled: true, maxRecipients: 2 } });
  expect(sessionStorage.getItem(configKey)).toBeNull(); expect(host.textContent).toContain('操作额度受限，token/费用未计量'); expect(host.textContent).toContain('配置修订：1'); expect(host.querySelector('form')).toBeNull(); expect(assistantApi.ask).not.toHaveBeenCalled();
});
it.each([{ minimum: 2, total: '1', perQuestion: '2' }, { minimum: 2, total: '2', perQuestion: '1' }, { minimum: 3, total: '2', perQuestion: '2' }])('refuses insufficient processing allowance before any mutation: %j', async ({ minimum, total, perQuestion }) => {
  vi.mocked(setupApi.candidates).mockResolvedValue({ ...candidates, qaMinimumToolCalls: minimum }); await mount(null); await allowance(); await field('总工具操作额度', total); await field('每问工具操作上限', perQuestion); await submit();
  expect(input('总工具操作额度').getAttribute('min')).toBe(String(minimum)); expect(input('每问工具操作上限').getAttribute('min')).toBe(String(minimum)); expect(host.textContent).toContain(`每次问答至少需要 ${minimum} 次处理额度`);
  expect(input('总工具操作额度').value).toBe(total); expect(input('每问工具操作上限').value).toBe(perQuestion); expect(sessionStorage.getItem(configKey)).toBeNull();
  for (const action of ['create', 'draft', 'publish', 'configure', 'ask'] as const) expect(assistantApi[action]).not.toHaveBeenCalled();
});
it('accepts exactly the installed minimum of two operations without increasing consent', async () => {
  await mount(null); await allowance(); await field('最多回答问题数', '1'); await field('总工具操作额度', '2'); await field('每问工具操作上限', '2'); await submit();
  expect(assistantApi.draft).toHaveBeenCalledWith('alice', expect.objectContaining({ budget: { ...draft.preview.budget, toolCalls: 2 } }));
  expect(assistantApi.configure).toHaveBeenCalledWith('alice', expect.objectContaining({ budget: { ...budget, caps: { ...caps, rounds: 1, toolCalls: 2 }, perQuestionCaps: { ...budget.perQuestionCaps, toolCalls: 2 } } })); expect(assistantApi.ask).not.toHaveBeenCalled();
});
it.each([null, undefined])('does not enable QA when the deployment has no minimum capability: %s', async minimum => {
  vi.mocked(setupApi.candidates).mockResolvedValue({ ...candidates, qaMinimumToolCalls: minimum }); await mount(null); await allowance(); expect(button('按修订 0 启用离线问答').disabled).toBe(true); await submit();
  expect(host.textContent).toContain('当前部署未提供离线问答能力'); for (const action of ['create', 'draft', 'publish', 'configure', 'ask'] as const) expect(assistantApi[action]).not.toHaveBeenCalled();
});
it('retains inputs after a CAS refusal and requires a new consent for the refreshed revision', async () => {
  const configure = vi.mocked(assistantApi.configure).mockRejectedValueOnce(new ApiError('配置修订冲突', 409, 'RESEARCH_ASSISTANT_REVISION_CONFLICT'));
  await mount(); await allowance(); await submit(); const first = configure.mock.calls[0][1];
  expect(host.textContent).toContain('配置修订冲突'); expect(sessionStorage.getItem(configKey)).toBeNull(); expect(assistantApi.create).not.toHaveBeenCalled();
  await act(async () => button('读取最新助手配置').click()); expect(configure).toHaveBeenCalledOnce(); expect(input('最多回答问题数').value).toBe('3'); expect(button('按修订 2 启用离线问答')).toBeDefined();
  await submit(); expect(configure.mock.calls[1][1]).toEqual({ ...first, expectedRevision: 2, requestId: expect.any(String) }); expect(configure.mock.calls[1][1].requestId).not.toBe(first.requestId); expect(assistantApi.draft).toHaveBeenCalledOnce(); expect(assistantApi.publish).toHaveBeenCalledOnce();
});
it.each(['draft', 'publish', 'configure'] as const)('unlocks new consent after an uncertain %s recovers to a definitive configuration CAS refusal', async stage => {
  vi.mocked(assistantApi[stage]).mockRejectedValueOnce(new ApiError('lost reply', 408));
  const configure = vi.mocked(assistantApi.configure).mockRejectedValueOnce(new ApiError('配置修订冲突', 409, 'RESEARCH_ASSISTANT_REVISION_CONFLICT')).mockResolvedValue({ ...configured, configurationRevision: 3 });
  await mount(); await allowance(); await submit(); const consent = JSON.parse(sessionStorage.getItem(configKey)!).body;
  expect(host.querySelector('fieldset')!.disabled).toBe(true); await act(async () => button('重试原操作').click());
  expect(sessionStorage.getItem(configKey)).toBeNull(); expect(button('重试原操作')).toBeUndefined(); expect(host.textContent).toContain('配置修订冲突'); expect(host.querySelector('fieldset')!.disabled).toBe(false); expect(input('最多回答问题数').value).toBe('3');
  expect(configure.mock.calls.every(([, body]) => body.requestId === consent.requestId + ':configure' && body.expectedRevision === 0)).toBe(true);
  const oldCalls = configure.mock.calls.length; const drafts = vi.mocked(assistantApi.draft).mock.calls.length; const publications = vi.mocked(assistantApi.publish).mock.calls.length;
  await act(async () => button('读取最新助手配置').click()); expect(configure).toHaveBeenCalledTimes(oldCalls); await submit();
  const last = configure.mock.calls.at(-1)![1]; expect(last.expectedRevision).toBe(2); expect(last.requestId).not.toBe(consent.requestId + ':configure'); expect(last.budget).toEqual(consent.budget); expect(last.applicationRef).toEqual(published.applicationRef);
  expect(assistantApi.setup).toHaveBeenCalledWith('alice', published.id); expect(assistantApi.draft).toHaveBeenCalledTimes(drafts); expect(assistantApi.publish).toHaveBeenCalledTimes(publications); expect(assistantApi.ask).not.toHaveBeenCalled();
});
it('keeps an unresolved original request for other conflicts and repeated unknown replies', async () => {
  const configure = vi.mocked(assistantApi.configure).mockRejectedValueOnce(new ApiError('lost reply', 408)).mockRejectedValueOnce(new ApiError('different conflict', 409, 'IDEMPOTENCY_CONFLICT')).mockRejectedValueOnce(new ApiError('still unknown', 503));
  await mount(); await allowance(); await submit(); const saved = sessionStorage.getItem(configKey);
  await act(async () => button('重试原操作').click()); expect(sessionStorage.getItem(configKey)).toBe(saved); expect(host.querySelector('fieldset')!.disabled).toBe(true);
  await act(async () => button('重试原操作').click()); expect(sessionStorage.getItem(configKey)).toBe(saved); expect(host.querySelector('fieldset')!.disabled).toBe(true);
  await act(async () => button('重试原操作').click()); expect(configure).toHaveBeenCalledTimes(4); expect(configure.mock.calls.every(([, body]) => body.requestId === configure.mock.calls[0][1].requestId)).toBe(true); expect(sessionStorage.getItem(configKey)).toBeNull();
});
it.each(['publish', 'configure'] as const)('recovers an uncertain %s with every original stage ID and owner after remount', async stage => {
  vi.mocked(assistantApi[stage]).mockRejectedValueOnce(new ApiError('lost reply', 503));
  await mount(null); await allowance(); await submit();
  const saved = sessionStorage.getItem(configKey)!; const consent = JSON.parse(saved).body; const create = vi.mocked(assistantApi.create).mock.calls[0][1]; const prepare = vi.mocked(assistantApi.draft).mock.calls[0][1]; const publish = vi.mocked(assistantApi.publish).mock.calls[0][2];
  expect(host.textContent).toContain('尚未确认');
  await remount(null, 'bob'); expect(button('重试原操作')).toBeUndefined(); expect(sessionStorage.getItem(configKey)).toBe(saved);
  await remount({ ...original, configurationRevision: 9 }); expect(assistantApi.create).toHaveBeenCalledOnce(); expect(assistantApi.publish).toHaveBeenCalledOnce();
  await act(async () => button('重试原操作').click());
  expect(vi.mocked(assistantApi.create).mock.calls[1]).toEqual(['alice', create]); expect(vi.mocked(assistantApi.draft).mock.calls[1]).toEqual(['alice', prepare]); expect(vi.mocked(assistantApi.publish).mock.calls[1]).toEqual(['alice', 'setup-a', publish]);
  expect(assistantApi.configure).toHaveBeenLastCalledWith('alice', expect.objectContaining({ requestId: consent.requestId + ':configure', expectedRevision: 0, budget: consent.budget }));
  expect(sessionStorage.getItem(configKey)).toBeNull(); expect(assistantApi.ask).not.toHaveBeenCalled();
});
it('shows missing real model connections and reuses the resource entry without mutation', async () => {
  vi.mocked(setupApi.candidates).mockResolvedValue({ ...candidates, models: [], connections: [] });
  await mount(null); expect(button('按修订 0 启用离线问答').disabled).toBe(true); expect(host.textContent).toContain('缺少可用模型连接');
  await act(async () => button('配置我的模型与资源').click()); expect(resources).toHaveBeenCalledOnce(); expect(assistantApi.create).not.toHaveBeenCalled(); expect(assistantApi.draft).not.toHaveBeenCalled();
});
it('preserves old association opt-out and leaves the existing allowance unchanged when opened', async () => {
  await mount(configured); expect(host.textContent).toContain('主动关联未启用'); expect(assistantApi.configure).not.toHaveBeenCalled();
  await act(async () => button('修改离线问答设置').click()); expect((host.querySelector('input[type=checkbox]') as HTMLInputElement).checked).toBe(false); expect(input('最多回答问题数').value).toBe('');
  await allowance(); await submit(); expect(assistantApi.configure).toHaveBeenCalledWith('alice', expect.objectContaining({ associations: { enabled: false, maxRecipients: 2 } }));
});
it('resumes an old deep-link publication request only on recovery, using its original target and ID', async () => {
  const key = 'factory:research-qa-setup:alice:old-setup'; sessionStorage.setItem(key, JSON.stringify({ action: 'publish', body: { requestId: 'original-publish-id' } }));
  await mount(original, 'alice', 'old-setup'); expect(assistantApi.publish).not.toHaveBeenCalled(); expect(host.querySelector('fieldset')!.disabled).toBe(true);
  await act(async () => button('重试原操作').click()); expect(assistantApi.publish).toHaveBeenCalledWith('alice', 'old-setup', { requestId: 'original-publish-id' }); expect(sessionStorage.getItem(key)).toBeNull();
  expect(assistantApi.configure).not.toHaveBeenCalled(); await allowance(); await submit(); expect(assistantApi.draft).not.toHaveBeenCalled(); expect(assistantApi.publish).toHaveBeenCalledOnce(); expect(assistantApi.configure).toHaveBeenCalledWith('alice', expect.objectContaining({ applicationRef: published.applicationRef }));
});
it('refuses a larger allowance on an old pin and creates a new definition only after the member chooses it', async () => {
  await mount(original, 'alice', 'old-setup'); await allowance(); await field('每问工具操作上限', '12'); await submit();
  expect(host.textContent).toContain('超过原问答版本上限'); expect(assistantApi.draft).not.toHaveBeenCalled(); expect(assistantApi.configure).not.toHaveBeenCalled(); expect(sessionStorage.getItem(configKey)).toBeNull();
  await act(async () => button('为当前模型生成新配置').click()); expect(assistantApi.draft).not.toHaveBeenCalled();
  vi.mocked(assistantApi.draft).mockResolvedValue({ ...draft, preview: { ...draft.preview, budget: { ...draft.preview.budget, toolCalls: 12 } } }); await submit();
  expect(assistantApi.draft).toHaveBeenCalledWith('alice', expect.objectContaining({ budget: { ...draft.preview.budget, toolCalls: 12 } })); expect(assistantApi.configure).toHaveBeenCalledWith('alice', expect.objectContaining({ budget: { ...budget, perQuestionCaps: { ...budget.perQuestionCaps, toolCalls: 12 } } }));
});
it.each(['create', 'draft', 'configure'] as const)('retains an older pending %s without showing normal draft/publication controls', async action => {
  const body = action === 'configure' ? { requestId: 'old-configure-id', expectedRevision: 0, applicationRef: published.applicationRef, connectionRefs: published.connectionRefs, budget } : action === 'draft' ? { requestId: 'old-draft-id', name: '原草稿', modelConnectionRef: draft.preview.modelConnectionRef, budget: draft.preview.budget } : { requestId: 'old-create-id' };
  const key = action === 'configure' ? configKey : action === 'draft' ? 'factory:research-qa-setup:alice:new' : 'factory:research-assistant-create:alice';
  sessionStorage.setItem(key, JSON.stringify({ action, body })); await mount(); expect(assistantApi[action]).not.toHaveBeenCalled();
  expect(button('保存私人QA草稿')).toBeUndefined(); expect(button('明确发布QA配置')).toBeUndefined(); await act(async () => button('重试原操作').click()); expect(assistantApi[action]).toHaveBeenCalledWith('alice', body); expect(sessionStorage.getItem(key)).toBeNull(); expect(assistantApi.ask).not.toHaveBeenCalled();
});
it('does not mount recovery for an empty old storage key or accept a changed model binding', async () => {
  sessionStorage.setItem('factory:research-qa-setup:alice:new', ''); await mount(); expect(button('重试原操作')).toBeUndefined(); expect(host.querySelector('fieldset')!.disabled).toBe(false);
  vi.mocked(assistantApi.publish).mockResolvedValue({ ...published, connectionRefs: { model: 'different-model' } }); await allowance(); await submit();
  expect(assistantApi.configure).not.toHaveBeenCalled(); expect(host.textContent).toContain('模型绑定不一致'); expect(sessionStorage.getItem(configKey)).not.toBeNull();
});
