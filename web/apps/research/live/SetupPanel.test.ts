// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ApiError } from '../../../api.js';
import { SetupPanel } from './SetupPanel.js';
import { setupApi, type ResearchSetup, type SetupCandidates } from './setupClient.js';
let host: HTMLDivElement; let root: Root;
const onSetup = vi.fn(); const onPublished = vi.fn();
const pin = { id: 'tool-experiment', version: 1, sha256: 'a'.repeat(64) };
const candidates: SetupCandidates = { workflowPin: { kind: 'workflow', id: 'research-round', revision: '1', sha256: 'b'.repeat(64) }, models: [{ reference: 'model-registration', provider: 'provider', model: 'model-name', available: true }], connections: [{ ref: 'actual-model-connection', registrationRef: 'model-registration', kind: 'model-provider', capabilities: [], available: true }], environments: [{ adapterId: 'registered-environment', revision: '1', connectionKind: null, requiredCapabilities: [] }], experimentMaterials: [{ ...pin, name: '实验计算工具', available: true, connectionRequirements: [] }] };
const draft: ResearchSetup = { id: 'setup-1', state: 'draft', applicationRef: null, connectionRefs: { model: 'actual-model-connection' }, materialRefs: [], preview: { name: '研究配置', modelConnectionRef: 'actual-model-connection', environment: { adapterId: 'registered-environment', revision: '1' }, experimentMaterialRefs: [pin], connectionRefs: {}, workflowPin: candidates.workflowPin, budget: { toolCalls: 8, maxDepth: 2, maxChildren: 4, operationSeconds: 8, outputBytes: 65536 } } };
const published: ResearchSetup = { ...draft, state: 'published', applicationRef: { id: 'published-research', version: 1, sha256: 'c'.repeat(64) }, materialRefs: [pin] };
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); window.sessionStorage.clear(); host = document.createElement('div'); document.body.append(host); root = createRoot(host); onSetup.mockReset(); onPublished.mockReset();
  vi.spyOn(setupApi, 'candidates').mockResolvedValue(candidates); vi.spyOn(setupApi, 'read').mockResolvedValue(draft); vi.spyOn(setupApi, 'draft').mockResolvedValue(draft); vi.spyOn(setupApi, 'publish').mockResolvedValue(published);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const button = (name: string) => [...host.querySelectorAll('button')].find(item => item.textContent === name)!;
async function mount(setupId?: string, ownerId = 'alice') { await act(async () => root.render(createElement(SetupPanel, { key: `${ownerId}:${setupId ?? 'new'}`, ownerId, setupId, onSetup, onPublished, onResources: vi.fn(), onMaterials: vi.fn() }))); }
async function field(label: string, value: string) {
  const input = [...host.querySelectorAll('label')].find(item => item.firstChild?.textContent === label)!.querySelector('input,select')!;
  const prototype = input.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
  await act(async () => { Object.getOwnPropertyDescriptor(prototype, 'value')!.set!.call(input, value); input.dispatchEvent(new Event(input.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true })); });
}
it('requires an actual connection and environment rather than using registrations or demo defaults', async () => {
  vi.mocked(setupApi.candidates).mockResolvedValue({ ...candidates, connections: [], environments: [] }); await mount();
  expect(host.textContent).toContain('缺少可用模型连接'); expect(host.textContent).toContain('缺少已注册运行环境'); expect(button('保存私人配置草稿').disabled).toBe(true); expect(setupApi.draft).not.toHaveBeenCalled();
});
it('prepares only a private draft with the selected actual connection, then publishes explicitly before applying a pin', async () => {
  await mount(); await field('配置名称', '研究配置'); await field('已保存模型连接', 'actual-model-connection'); await field('运行环境', 'registered-environment:1');
  await act(async () => (host.querySelector('input[type=checkbox]') as HTMLInputElement).click()); await act(async () => button('保存私人配置草稿').click());
  expect(setupApi.draft).toHaveBeenCalledWith('alice', expect.objectContaining({ modelConnectionRef: 'actual-model-connection', experimentMaterialRefs: [pin] })); expect(setupApi.publish).not.toHaveBeenCalled(); expect(onPublished).not.toHaveBeenCalled(); expect(host.textContent).toContain('私人草稿 · 尚未发布');
  await mount('setup-1'); await act(async () => button('发布研究执行配置').click()); expect(setupApi.publish).toHaveBeenCalledWith('alice', 'setup-1', { requestId: expect.any(String) }); expect(onPublished).not.toHaveBeenCalled();
  await act(async () => button('用于当前研究约定').click()); expect(onPublished).toHaveBeenCalledWith({ applicationRef: published.applicationRef, mode: 'research', connectionRefs: published.connectionRefs });
});
it('retains the same publication key after an unknown reply and owner-isolated remount', async () => {
  vi.mocked(setupApi.publish).mockRejectedValueOnce(new ApiError('应答丢失', 408)); await mount('setup-1'); await act(async () => button('发布研究执行配置').click()); const first = vi.mocked(setupApi.publish).mock.calls[0];
  await mount('setup-1', 'bob'); expect(button('重试原操作')).toBeUndefined();
  await mount('setup-1'); await act(async () => button('重试原操作').click()); expect(vi.mocked(setupApi.publish).mock.calls[1]).toEqual(first);
});
