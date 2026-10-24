// @vitest-environment happy-dom
import { webcrypto } from 'node:crypto';
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '../web/api.js';
import { ReusableToolOperations, readToolOperationRequest } from '../web/ReusableToolOperations.js';
import { personalToolConnectionApi as tools, ToolConnectionError, type ToolOperation } from '../web/personalToolConnectionApi.js';
const configuration = { transport: 'cli' as const, toolName: 'lookup', description: 'Public fixture', inputSchema: { type: 'object' }, executable: 'fixture', arguments: ['--public'], environment: { PUBLIC_MODE: 'demo' } };
const operation: ToolOperation = { ownerId: 'bob', operationRef: { id: 'lookup', version: 2, sha256: 'a'.repeat(64) }, configuration, descriptor: { adapterId: 'adapter', revision: 'v2', toolName: 'lookup', description: 'Public fixture', inputSchema: { type: 'object' }, transport: 'cli', credentialProviderId: 'fixture', credentialDestination: 'https://fixture.invalid', capabilities: ['read'], permission: 'read', readOnly: true }, runtimeBinding: { adapterId: 'adapter', revision: 'v2', config: { operationSha256: 'a'.repeat(64) } } };
const credential = { credentialRef: 'alice-key', credentialRevision: 'r1', providerId: 'fixture', destination: 'https://fixture.invalid', status: 'active' };
let host: HTMLDivElement; let root: Root;
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); vi.stubGlobal('crypto', webcrypto); localStorage.clear();
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  vi.spyOn(api, 'session').mockResolvedValue({ id: 'alice', name: 'Alice', role: 'user' });
  vi.spyOn(tools, 'operations').mockResolvedValue([operation]);
  vi.spyOn(tools, 'createOperation').mockResolvedValue({ ...operation, ownerId: 'alice' });
  vi.spyOn(tools, 'createOperationAccount').mockRejectedValue(new ToolConnectionError(0));
  vi.spyOn(tools, 'configureResource'); vi.spyOn(tools, 'bind'); vi.spyOn(tools, 'discover');
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function mount() { await act(async () => root.render(createElement(ReusableToolOperations, { ownerId: 'alice', credentials: [credential, { ...credential, credentialRef: 'wrong-destination', destination: 'https://other.invalid' }], disabled: false, onChanged: vi.fn() }))); }
const button = (text: string) => Array.from(host.querySelectorAll('button')).find(b => b.textContent === text)!;
async function click(text: string) { await act(async () => button(text).click()); }
async function field(label: string, value: string) {
  await act(async () => {
    const input = host.querySelector<HTMLTextAreaElement | HTMLSelectElement>(`[aria-label="${label}"]`)!;
    const select = input.tagName === 'SELECT'; Object.getOwnPropertyDescriptor(select ? HTMLSelectElement.prototype : HTMLTextAreaElement.prototype, 'value')!.set!.call(input, value);
    input.dispatchEvent(new Event(select ? 'change' : 'input', { bubbles: true }));
  });
}
async function open() { await mount(); await click('可复用工具操作'); }
it('requires an explicit public recipe preview and consent, without copying a private resource or executing discovery', async () => {
  await mount(); expect(tools.operations).not.toHaveBeenCalled(); await click('可复用工具操作');
  expect(host.querySelector<HTMLTextAreaElement>('textarea')!.value).not.toContain('PUBLIC_MODE');
  await field('公开操作配方', JSON.stringify(configuration));
  expect(host.querySelector('[aria-label="即将公开的完整配方"]')!.textContent).toContain('PUBLIC_MODE');
  expect(button('保存公开操作版本').disabled).toBe(true);
  await act(async () => host.querySelector<HTMLInputElement>('[aria-label="确认公开操作配方"]')!.click());
  await click('保存公开操作版本');
  expect(tools.createOperation).toHaveBeenCalledExactlyOnceWith('alice', { configuration, requestId: expect.any(String) });
  expect(tools.configureResource).not.toHaveBeenCalled(); expect(tools.bind).not.toHaveBeenCalled(); expect(tools.discover).not.toHaveBeenCalled();
  expect(host.textContent).toContain('尚未创建账号、发布工具材料或执行工具');
});
it('rejects private credential fields and authenticated URLs in an explicitly public recipe', async () => {
  await open();
  for (const bad of [{ ...configuration, credentialRef: 'private-ref' }, { ...configuration, transport: 'mcp', url: 'https://user:pass@fixture.invalid', remoteToolName: 'lookup' }]) {
    await field('公开操作配方', JSON.stringify(bad)); expect(button('保存公开操作版本').disabled).toBe(true);
  }
  expect(tools.createOperation).not.toHaveBeenCalled();
});
it('pins another author’s public operation with only this member’s matching credential and preserves an uncertain request across reload', async () => {
  await open(); await field('选择公开工具操作', 'lookup:2:' + 'a'.repeat(64));
  const select = host.querySelector<HTMLSelectElement>('[aria-label="公开操作本人凭据"]')!;
  expect(Array.from(select.options).map(item => item.value)).toEqual(['', 'alice-key']);
  expect(host.textContent).toContain('操作作者：bob'); expect(host.textContent).toContain('这不是材料摘要');
  await field('公开操作本人凭据', 'alice-key'); await click('创建本人的独立账号');
  const original = vi.mocked(tools.createOperationAccount).mock.calls[0];
  expect(original).toEqual(['alice', 'lookup', { version: 2, sha256: 'a'.repeat(64), credentialRef: 'alice-key', credentialRevision: 'r1', requestId: expect.any(String) }]);
  expect(select.closest('fieldset')!.disabled).toBe(true);
  await act(async () => root.unmount()); root = createRoot(host); await mount();
  expect(tools.createOperationAccount).toHaveBeenCalledTimes(1);
  await click('核对原操作请求'); expect(vi.mocked(tools.createOperationAccount).mock.calls[1]).toEqual(original);
  expect(tools.bind).not.toHaveBeenCalled();
});
it('locks the original public creation payload for explicit retry and refuses another session owner', async () => {
  vi.mocked(tools.createOperation).mockRejectedValue(new ToolConnectionError(0));
  await open(); await field('公开操作配方', JSON.stringify(configuration));
  await act(async () => host.querySelector<HTMLInputElement>('[aria-label="确认公开操作配方"]')!.click()); await click('保存公开操作版本');
  const original = vi.mocked(tools.createOperation).mock.calls[0];
  await click('核对原操作请求'); expect(vi.mocked(tools.createOperation).mock.calls[1]).toEqual(original);
  vi.mocked(api.session).mockResolvedValue({ id: 'bob', name: 'Bob', role: 'user' });
  await click('核对原操作请求'); expect(tools.createOperation).toHaveBeenCalledTimes(2); expect(host.textContent).toContain('当前登录账号已改变');
});
it('never revives private fields or another owner’s stored public request', () => {
  const request = { owner: 'alice', kind: 'operation', input: { configuration, requestId: 'one' } };
  expect(readToolOperationRequest(JSON.stringify(request), 'alice')).toEqual(request);
  expect(readToolOperationRequest(JSON.stringify(request), 'bob')).toBeNull();
  expect(readToolOperationRequest(JSON.stringify({ ...request, input: { ...request.input, configuration: { ...configuration, credentialRef: 'private' } } }), 'alice')).toBeNull();
});
it('cancels an obsolete list read and does not let its late response replace the current catalog', async () => {
  let resolve!: (value: ToolOperation[]) => void;
  vi.mocked(tools.operations).mockImplementationOnce(() => new Promise(done => { resolve = done; }));
  await open(); const signal = vi.mocked(tools.operations).mock.calls[0][1]!;
  await click('重新读取公开操作'); expect(signal.aborted).toBe(true);
  await act(async () => resolve([{ ...operation, operationRef: { ...operation.operationRef, id: 'obsolete' }, descriptor: { ...operation.descriptor, toolName: 'obsolete' } }]));
  expect(host.querySelector('[aria-label="选择公开工具操作"]')!.textContent).toContain('lookup');
  expect(host.querySelector('[aria-label="选择公开工具操作"]')!.textContent).not.toContain('obsolete');
});
it('keeps the original public payload visible after an uncertain creation is reloaded', async () => {
  vi.mocked(tools.createOperation).mockRejectedValue(new ToolConnectionError(0));
  await open(); await field('公开操作配方', JSON.stringify(configuration));
  await act(async () => host.querySelector<HTMLInputElement>('[aria-label="确认公开操作配方"]')!.click()); await click('保存公开操作版本');
  await act(async () => root.unmount()); root = createRoot(host); await mount();
  expect(host.querySelector('[aria-label="待确认原请求"]')!.textContent).toContain('PUBLIC_MODE');
  expect(tools.createOperation).toHaveBeenCalledTimes(1);
});
