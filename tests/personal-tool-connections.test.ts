// @vitest-environment happy-dom
import { webcrypto } from 'node:crypto';
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '../web/api.js';
import { PersonalToolConnections, readToolCommand } from '../web/PersonalToolConnections.js';
import { personalToolConnectionApi as tools, ToolConnectionError, type PersonalToolConnection, type PersonalToolDescriptor } from '../web/personalToolConnectionApi.js';
import { personalRemoteApi as vault, RemoteRequestError } from '../web/personalRemoteApi.js';
import type { UserConnection } from '../web/models.js';

const descriptor: PersonalToolDescriptor = { adapterId: 'fixture-cli-v1', revision: 'descriptor-v1', toolName: 'fixture_lookup', description: 'Synthetic installed tool', inputSchema: { type: 'object' }, transport: 'cli', credentialProviderId: 'fixture-tool-token', credentialDestination: 'https://fixture.example.org', capabilities: ['tool:lookup'], permission: 'read', readOnly: true };
const saved = { credentialRef: 'credential-fixture', credentialRevision: 'credential-r1', providerId: descriptor.credentialProviderId, destination: descriptor.credentialDestination, status: 'active' };
const configured: PersonalToolConnection = { ownerId: 'alice', registrationRef: 'personal-tool-fixture', adapterId: descriptor.adapterId, revision: 'owner-config-r1', descriptorRevision: descriptor.revision, kind: 'tool', toolName: descriptor.toolName, transport: descriptor.transport, credentialRef: saved.credentialRef, credentialRevision: saved.credentialRevision, status: 'configured', available: true, capabilities: descriptor.capabilities, createdAt: '2026-10-13T00:00:00Z', expiresAt: null, allowedActions: ['inspect', 'bind', 'revoke'] };
const bound: UserConnection = { ref: 'bound-tool-fixture', ownerId: 'alice', version: 1, fingerprint: 'a'.repeat(64), kind: 'tool', revision: configured.revision, capabilities: descriptor.capabilities, taskId: null, registrationRef: configured.registrationRef, expiresAt: null, createdAt: '2026-10-13T00:00:00Z', revokedAt: null, status: 'active', available: true, allowedActions: ['inspect', 'revoke'] };
const secret = 'synthetic-tool-secret-only';
const storage = 'factory-personal-tool-command:alice';
let host: HTMLDivElement; let root: Root;
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); vi.stubGlobal('crypto', webcrypto); localStorage.clear();
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  vi.spyOn(api, 'session').mockResolvedValue({ id: 'alice', name: 'Alice', role: 'user' });
  vi.spyOn(tools, 'descriptors').mockResolvedValue([descriptor]); vi.spyOn(tools, 'list').mockResolvedValue([]);
  vi.spyOn(tools, 'configure').mockResolvedValue(configured); vi.spyOn(tools, 'bind').mockResolvedValue(bound);
  vi.spyOn(tools, 'recover').mockImplementation(async (_owner, requestId) => ({ requestId, action: 'tool.configure', tool: configured }));
  vi.spyOn(tools, 'recoverBinding').mockImplementation(async (_owner, requestId) => ({ requestId, action: 'bind', connection: bound }));
  vi.spyOn(tools, 'revoke').mockResolvedValue({ ...configured, status: 'revoked', available: false, allowedActions: ['inspect'] });
  vi.spyOn(vault, 'credentialAvailability').mockResolvedValue({ enabled: true, providerIds: [saved.providerId] });
  vi.spyOn(vault, 'credentials').mockResolvedValue([saved]); vi.spyOn(vault, 'saveCredential').mockResolvedValue(saved);
  vi.spyOn(vault, 'recoverCredential').mockResolvedValue(saved);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function mount(ownerId = 'alice') { await act(async () => root.render(createElement(PersonalToolConnections, { ownerId, onChanged: vi.fn() }))); }
async function remount() { await act(async () => root.unmount()); root = createRoot(host); await mount(); }
const button = (text: string) => Array.from(host.querySelectorAll('button')).find(b => b.textContent === text)!;
async function click(text: string) { await act(async () => button(text).click()); }
async function field(label: string, value: string) {
  await act(async () => {
    const input = host.querySelector<HTMLInputElement | HTMLSelectElement>(`[aria-label="${label}"]`)!;
    const select = input.tagName === 'SELECT'; Object.getOwnPropertyDescriptor(select ? HTMLSelectElement.prototype : HTMLInputElement.prototype, 'value')!.set!.call(input, value);
    input.dispatchEvent(new Event(select ? 'change' : 'input', { bubbles: true }));
  });
}
async function chooseSaved() { await field('个人工具', descriptor.adapterId); await field('工具已有凭据', saved.credentialRef); }
async function chooseNew() {
  await field('个人工具', descriptor.adapterId); await field('工具凭据来源', 'new'); await field('工具访问令牌', secret);
  await act(async () => host.querySelector<HTMLInputElement>('input[type=checkbox]')!.click());
}

it('configures and binds an ordinary member tool once using the exact saved credential and separate request IDs', async () => {
  await mount(); await chooseSaved();
  expect(host.textContent).toContain(descriptor.credentialDestination);
  await act(async () => { button('保存并绑定工具').click(); button('保存并绑定工具').click(); });
  expect(tools.configure).toHaveBeenCalledTimes(1); expect(tools.bind).toHaveBeenCalledTimes(1); expect(vault.saveCredential).not.toHaveBeenCalled();
  const config = vi.mocked(tools.configure).mock.calls[0]; const binding = vi.mocked(tools.bind).mock.calls[0];
  expect(config).toEqual(['alice', { adapterId: descriptor.adapterId, credentialRef: saved.credentialRef, credentialRevision: saved.credentialRevision, requestId: expect.any(String) }]);
  expect(binding).toEqual(['alice', configured.registrationRef, expect.any(String), descriptor.capabilities]);
  expect(config[1].requestId).not.toBe(binding[2]); expect(localStorage.getItem(storage)).toBeNull();
  expect(host.textContent).toContain('工具已保存并绑定'); expect(host.textContent).toContain('保存没有执行工具');
});

it('saves a new token through the vault and never persists or renders the secret', async () => {
  await mount(); await chooseNew(); expect(host.querySelector('[aria-label="工具访问令牌"]')?.getAttribute('type')).toBe('password');
  await click('保存并绑定工具');
  expect(vault.saveCredential).toHaveBeenCalledWith({ providerId: descriptor.credentialProviderId, destination: descriptor.credentialDestination, username: 'bearer', password: secret, requestId: expect.any(String) }, 'alice');
  expect(tools.configure).toHaveBeenCalledTimes(1); expect(tools.bind).toHaveBeenCalledTimes(1);
  expect(host.querySelector<HTMLInputElement>('[aria-label="工具访问令牌"]')?.value).toBe('');
  expect(host.textContent).not.toContain(secret); expect(JSON.stringify(localStorage)).not.toContain(secret);
  const ids = [vi.mocked(vault.saveCredential).mock.calls[0][0].requestId, vi.mocked(tools.configure).mock.calls[0][1].requestId, vi.mocked(tools.bind).mock.calls[0][2]];
  expect(new Set(ids).size).toBe(3);
});

it('keeps a missing configuration receipt pending across remount without resubmission, then binds only its unsent next step', async () => {
  vi.mocked(tools.configure).mockRejectedValue(new ToolConnectionError(0));
  await mount(); await chooseSaved(); await click('保存并绑定工具');
  const requestId = vi.mocked(tools.configure).mock.calls[0][1].requestId;
  expect(tools.bind).not.toHaveBeenCalled(); expect(localStorage.getItem(storage)).not.toBeNull();
  await remount(); expect(tools.recover).not.toHaveBeenCalled(); expect(tools.configure).toHaveBeenCalledTimes(1);
  vi.mocked(tools.recover).mockRejectedValueOnce(new ToolConnectionError(404));
  await click('核对原工具请求'); expect(localStorage.getItem(storage)).not.toBeNull(); expect(tools.bind).not.toHaveBeenCalled();
  await click('核对原工具请求');
  expect(tools.recover).toHaveBeenLastCalledWith('alice', requestId); expect(tools.configure).toHaveBeenCalledTimes(1); expect(tools.bind).toHaveBeenCalledTimes(1);
  expect(localStorage.getItem(storage)).toBeNull();
});

it('recovers a lost binding response with GET only and the original binding request', async () => {
  vi.mocked(tools.bind).mockRejectedValue(new ToolConnectionError(0));
  await mount(); await chooseSaved(); await click('保存并绑定工具');
  const requestId = vi.mocked(tools.bind).mock.calls[0][2];
  await remount();
  vi.mocked(tools.recoverBinding).mockRejectedValueOnce(new ToolConnectionError(404));
  await click('核对原工具请求');
  expect(localStorage.getItem(storage)).not.toBeNull(); expect(button('结束未发送步骤')).toBeUndefined();
  expect(button('保存并绑定工具').closest('fieldset')?.disabled).toBe(true);
  await click('核对原工具请求');
  expect(tools.recoverBinding).toHaveBeenCalledWith('alice', requestId); expect(tools.bind).toHaveBeenCalledTimes(1); expect(tools.configure).toHaveBeenCalledTimes(1);
  expect(localStorage.getItem(storage)).toBeNull();
});

it.each(['removed', 'upgraded'])('can end an unsent binding after its descriptor is %s without losing the saved tool or replaying setup', async change => {
  vi.mocked(tools.configure).mockImplementation(async () => {
    vi.mocked(tools.descriptors).mockResolvedValue(change === 'removed' ? [] : [{ ...descriptor, revision: 'descriptor-v2' }]);
    vi.mocked(tools.list).mockResolvedValue([{ ...configured, status: 'adapter_changed', available: false, allowedActions: ['inspect', 'revoke'] }]);
    return configured;
  });
  await mount(); await chooseSaved(); await click('保存并绑定工具');
  const pending = JSON.parse(localStorage.getItem(storage)!);
  expect(pending).toMatchObject({ stage: 'bind', dispatched: false, registrationRef: configured.registrationRef });
  await remount(); await click('核对原工具请求');
  expect(JSON.parse(localStorage.getItem(storage)!)).toEqual(pending);
  expect(host.textContent).toContain('绑定尚未发送');
  await click('结束未发送步骤');
  expect(localStorage.getItem(storage)).toBeNull(); expect(host.textContent).toContain('已保存的工具配置和原保存回执保留');
  expect(host.textContent).toContain(configured.registrationRef); expect(button('撤销工具配置').disabled).toBe(false);
  expect(tools.configure).toHaveBeenCalledTimes(1); expect(tools.bind).not.toHaveBeenCalled();
  expect(tools.recoverBinding).not.toHaveBeenCalled(); expect(vault.saveCredential).not.toHaveBeenCalled();
  await click('撤销工具配置'); expect(tools.revoke).toHaveBeenCalledTimes(1);
});

it.each(['dispatched', 'request', 'action', 'stage'])('does not discard an unsent step if another tab changed its %s', async change => {
  vi.mocked(tools.configure).mockImplementation(async () => {
    vi.mocked(tools.descriptors).mockResolvedValue([]); return configured;
  });
  await mount(); await chooseSaved(); await click('保存并绑定工具');
  const pending = JSON.parse(localStorage.getItem(storage)!);
  const latest = change === 'dispatched' ? { ...pending, dispatched: true }
    : change === 'request' ? { ...pending, requestId: 'another-request' }
      : change === 'action' ? { action: 'revoke', owner: 'alice', requestId: pending.requestId, registrationRef: pending.registrationRef, dispatched: false }
        : { ...pending, stage: 'configure' };
  localStorage.setItem(storage, JSON.stringify(latest));
  await click('结束未发送步骤');
  expect(JSON.parse(localStorage.getItem(storage)!)).toEqual(latest);
  expect(tools.configure).toHaveBeenCalledTimes(1); expect(tools.bind).not.toHaveBeenCalled(); expect(tools.revoke).not.toHaveBeenCalled();
});

it('rechecks the current owner before ending an unsent step', async () => {
  vi.mocked(tools.configure).mockImplementation(async () => {
    vi.mocked(tools.descriptors).mockResolvedValue([]); return configured;
  });
  await mount(); await chooseSaved(); await click('保存并绑定工具');
  const pending = localStorage.getItem(storage);
  vi.mocked(api.session).mockResolvedValue({ id: 'bob', name: 'Bob', role: 'user' });
  await click('结束未发送步骤');
  expect(localStorage.getItem(storage)).toBe(pending); expect(host.textContent).toContain('当前登录账户已改变');
  expect(tools.configure).toHaveBeenCalledTimes(1); expect(tools.bind).not.toHaveBeenCalled();
});

it.each(['rotated', 'revoked'])('settles a directly rejected binding after the credential is %s while preserving its saved configuration', async change => {
  vi.mocked(tools.configure).mockImplementation(async () => {
    vi.mocked(vault.credentials).mockResolvedValue(change === 'rotated' ? [{ ...saved, credentialRevision: 'credential-r2' }] : [{ ...saved, status: 'revoked' }]);
    vi.mocked(tools.list).mockResolvedValue([{ ...configured, status: 'credential_unavailable', available: false, allowedActions: ['inspect', 'revoke'] }]);
    return configured;
  });
  vi.mocked(tools.bind).mockRejectedValue(new ToolConnectionError(409, 'PERSONAL_TOOL_CREDENTIAL_UNAVAILABLE'));
  await mount(); await chooseSaved(); await click('保存并绑定工具');
  expect(localStorage.getItem(storage)).toBeNull(); expect(host.textContent).toContain('绑定请求已被明确拒绝');
  expect(host.textContent).toContain('已保存的工具配置和原保存回执保留'); expect(host.textContent).not.toContain('操作尚未确认');
  expect(host.textContent).toContain(configured.registrationRef); expect(button('撤销工具配置').disabled).toBe(false);
  expect(host.querySelector<HTMLFieldSetElement>('fieldset')?.disabled).toBe(false);
  expect(tools.configure).toHaveBeenCalledTimes(1); expect(tools.bind).toHaveBeenCalledTimes(1);
  expect(tools.recoverBinding).not.toHaveBeenCalled(); expect(vault.saveCredential).not.toHaveBeenCalled();
  await remount(); expect(localStorage.getItem(storage)).toBeNull();
  expect(tools.configure).toHaveBeenCalledTimes(1); expect(tools.bind).toHaveBeenCalledTimes(1);
});

it.each(['PERSONAL_TOOL_REVOKED', 'PERSONAL_TOOL_ADAPTER_UNAVAILABLE', 'PERSONAL_TOOL_ADAPTER_CHANGED'])('settles only a direct binding precondition rejection %s', async code => {
  vi.mocked(tools.bind).mockRejectedValue(new ToolConnectionError(409, code));
  await mount(); await chooseNew(); await click('保存并绑定工具');
  expect(localStorage.getItem(storage)).toBeNull(); expect(host.textContent).toContain('绑定请求已被明确拒绝');
  expect(host.querySelector<HTMLInputElement>('[aria-label="工具访问令牌"]')?.value).toBe('');
  expect(host.querySelector<HTMLInputElement>('input[type=checkbox]')?.checked).toBe(false);
  expect(vault.saveCredential).toHaveBeenCalledTimes(1); expect(tools.configure).toHaveBeenCalledTimes(1); expect(tools.bind).toHaveBeenCalledTimes(1);
  expect(tools.recoverBinding).not.toHaveBeenCalled();
});

it.each([undefined, 'PERSONAL_TOOL_UNKNOWN', 'IDEMPOTENCY_CONFLICT'])('keeps an unclassified binding 409 (%s) pending and never permits discarding or replaying it', async code => {
  vi.mocked(tools.bind).mockRejectedValue(new ToolConnectionError(409, code));
  vi.mocked(tools.recoverBinding).mockRejectedValue(new ToolConnectionError(404));
  await mount(); await chooseSaved(); await click('保存并绑定工具'); await remount(); await click('核对原工具请求');
  expect(JSON.parse(localStorage.getItem(storage)!)).toMatchObject({ stage: 'bind', dispatched: true });
  expect(button('结束未发送步骤')).toBeUndefined(); expect(host.textContent).toContain('操作尚未确认');
  expect(tools.bind).toHaveBeenCalledTimes(1); expect(tools.configure).toHaveBeenCalledTimes(1);
});

it('does not treat a credential rejection during GET recovery as proof that the original binding was rejected', async () => {
  vi.mocked(tools.bind).mockRejectedValue(new ToolConnectionError(0));
  vi.mocked(tools.recoverBinding).mockRejectedValue(new ToolConnectionError(409, 'PERSONAL_TOOL_CREDENTIAL_UNAVAILABLE'));
  await mount(); await chooseSaved(); await click('保存并绑定工具'); await click('核对原工具请求');
  expect(JSON.parse(localStorage.getItem(storage)!)).toMatchObject({ stage: 'bind', dispatched: true });
  expect(button('结束未发送步骤')).toBeUndefined(); expect(host.textContent).toContain('操作尚未确认');
  expect(tools.bind).toHaveBeenCalledTimes(1); expect(tools.configure).toHaveBeenCalledTimes(1);
});

it('recovers an uncertain vault save without resending the token', async () => {
  vi.mocked(vault.saveCredential).mockRejectedValue(new Error(secret));
  await mount(); await chooseNew(); await click('保存并绑定工具');
  const requestId = vi.mocked(vault.saveCredential).mock.calls[0][0].requestId;
  expect(JSON.stringify(localStorage)).not.toContain(secret); expect(host.textContent).not.toContain(secret); expect(tools.configure).not.toHaveBeenCalled();
  await remount(); await click('核对原工具请求');
  expect(vault.recoverCredential).toHaveBeenCalledWith(requestId, 'alice'); expect(vault.saveCredential).toHaveBeenCalledTimes(1);
  expect(tools.configure).toHaveBeenCalledTimes(1); expect(tools.bind).toHaveBeenCalledTimes(1);
});

it('does not configure after a recovered credential differs from the original descriptor target', async () => {
  vi.mocked(vault.saveCredential).mockRejectedValue(new RemoteRequestError(false));
  vi.mocked(vault.recoverCredential).mockResolvedValue({ ...saved, destination: 'https://other.example.org' });
  await mount(); await chooseNew(); await click('保存并绑定工具'); await click('核对原工具请求');
  expect(tools.configure).not.toHaveBeenCalled(); expect(tools.bind).not.toHaveBeenCalled(); expect(localStorage.getItem(storage)).not.toBeNull();
});

it('clears secret input and blocks writes when the owner changes before submission', async () => {
  await mount(); await chooseNew(); vi.mocked(api.session).mockResolvedValue({ id: 'bob', name: 'Bob', role: 'user' });
  await click('保存并绑定工具');
  expect(vault.saveCredential).not.toHaveBeenCalled(); expect(tools.configure).not.toHaveBeenCalled(); expect(tools.bind).not.toHaveBeenCalled();
  expect(host.querySelector('[aria-label="工具访问令牌"]')).toBeNull(); expect(host.textContent).toContain('当前登录账户已改变');
});

it('does not bind when the owner changes after configuration, retaining Alice original intent', async () => {
  vi.mocked(tools.configure).mockImplementation(async () => {
    vi.mocked(api.session).mockResolvedValue({ id: 'bob', name: 'Bob', role: 'user' });
    return configured;
  });
  await mount(); await chooseSaved(); await click('保存并绑定工具');
  expect(tools.configure).toHaveBeenCalledTimes(1); expect(tools.bind).not.toHaveBeenCalled();
  expect(host.textContent).toContain('当前登录账户已改变'); expect(localStorage.getItem(storage)).not.toBeNull();
  const pending = JSON.parse(localStorage.getItem(storage)!);
  expect(pending.stage).toBe('bind'); expect(pending.dispatched).toBe(false);
  vi.mocked(api.session).mockResolvedValue({ id: 'alice', name: 'Alice', role: 'user' });
  await remount(); await click('核对原工具请求');
  expect(tools.bind).toHaveBeenCalledExactlyOnceWith('alice', configured.registrationRef, pending.bindRequestId, descriptor.capabilities);
  expect(tools.recoverBinding).not.toHaveBeenCalled(); expect(tools.configure).toHaveBeenCalledTimes(1); expect(localStorage.getItem(storage)).toBeNull();
});

it('does not mark or dispatch an unsent binding when descriptor preflight finishes after unmount', async () => {
  let finish!: (value: PersonalToolDescriptor[]) => void;
  vi.mocked(tools.descriptors).mockResolvedValueOnce([descriptor]).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  await mount(); await chooseSaved(); await click('保存并绑定工具');
  expect(tools.configure).toHaveBeenCalledTimes(1); expect(tools.bind).not.toHaveBeenCalled();
  await act(async () => root.unmount());
  await act(async () => finish([descriptor]));
  const pending = JSON.parse(localStorage.getItem(storage)!);
  expect(pending.stage).toBe('bind'); expect(pending.dispatched).toBe(false); expect(tools.bind).not.toHaveBeenCalled();
  root = createRoot(host); await mount(); await click('核对原工具请求');
  expect(tools.bind).toHaveBeenCalledExactlyOnceWith('alice', configured.registrationRef, pending.bindRequestId, descriptor.capabilities);
  expect(tools.configure).toHaveBeenCalledTimes(1); expect(tools.recoverBinding).not.toHaveBeenCalled();
});

it('remounts on owner prop change and does not carry Alice secret, credential selection or requests into Bob', async () => {
  await mount(); await chooseNew(); vi.mocked(api.session).mockResolvedValue({ id: 'bob', name: 'Bob', role: 'user' });
  vi.mocked(vault.credentials).mockResolvedValue([]); await mount('bob');
  expect(host.querySelector('[aria-label="工具访问令牌"]')).toBeNull(); expect(host.textContent).not.toContain(secret);
  expect(tools.configure).not.toHaveBeenCalled(); expect(tools.bind).not.toHaveBeenCalled(); expect(localStorage.getItem('factory-personal-tool-command:bob')).toBeNull();
});

it('does not bind a recovered revoked tool or replace its credential with another available account', async () => {
  vi.mocked(tools.configure).mockRejectedValue(new ToolConnectionError(0));
  vi.mocked(tools.recover).mockImplementation(async (_owner, requestId) => ({ requestId, action: 'tool.configure', tool: { ...configured, status: 'revoked', available: false, allowedActions: ['inspect'] } }));
  await mount(); await chooseSaved(); await click('保存并绑定工具'); await click('核对原工具请求');
  expect(tools.configure).toHaveBeenCalledTimes(1); expect(tools.bind).not.toHaveBeenCalled(); expect(vault.saveCredential).not.toHaveBeenCalled();
  expect(localStorage.getItem(storage)).toBeNull(); expect(host.textContent).toContain('没有继续绑定'); expect(host.textContent).not.toContain('工具已保存并绑定');
});

it('settles an unavailable recovered binding without creating a replacement or blocking a new explicit choice', async () => {
  vi.mocked(tools.bind).mockRejectedValue(new ToolConnectionError(0));
  vi.mocked(tools.recoverBinding).mockImplementation(async (_owner, requestId) => ({ requestId, action: 'bind', connection: { ...bound, status: 'revoked', available: false } }));
  await mount(); await chooseSaved(); await click('保存并绑定工具'); await click('核对原工具请求');
  expect(tools.bind).toHaveBeenCalledTimes(1); expect(tools.configure).toHaveBeenCalledTimes(1); expect(localStorage.getItem(storage)).toBeNull();
  expect(host.textContent).toContain('没有重新绑定或改用其他凭据');
});

it('shows an explicit empty installation without collecting credentials or offering approval', async () => {
  vi.mocked(tools.descriptors).mockResolvedValue([]); await mount();
  expect(host.textContent).toContain('此部署尚未安装个人 CLI/MCP 工具'); expect(host.querySelector('input[type=password]')).toBeNull();
  expect(vault.credentials).not.toHaveBeenCalled(); expect(vault.credentialAvailability).not.toHaveBeenCalled(); expect(tools.configure).not.toHaveBeenCalled();
});

it('filters saved credentials by exact purpose, target and active status with no fallback', async () => {
  vi.mocked(vault.credentials).mockResolvedValue([{ ...saved, status: 'revoked' }, { ...saved, credentialRef: 'foreign-purpose', providerId: 'other' }, { ...saved, credentialRef: 'foreign-target', destination: 'https://other.example.org' }]);
  await mount(); await field('个人工具', descriptor.adapterId);
  expect(host.querySelector('[aria-label="工具已有凭据"]')?.querySelectorAll('option')).toHaveLength(1);
  expect(button('保存并绑定工具').disabled).toBe(true); expect(host.textContent).toContain('不会使用服务器或其他账户的凭据');
});

it('recovers tool revocation without repeating its POST', async () => {
  vi.mocked(tools.list).mockResolvedValue([configured]); vi.mocked(tools.revoke).mockRejectedValue(new ToolConnectionError(0));
  vi.mocked(tools.recover).mockImplementation(async (_owner, requestId) => ({ requestId, action: 'tool.revoke', tool: { ...configured, status: 'revoked', available: false, allowedActions: ['inspect'] } }));
  await mount(); await click('撤销工具配置');
  const requestId = vi.mocked(tools.revoke).mock.calls[0][2]; await remount(); await click('核对原工具请求');
  expect(tools.revoke).toHaveBeenCalledTimes(1); expect(tools.recover).toHaveBeenCalledWith('alice', requestId); expect(tools.bind).not.toHaveBeenCalled();
  expect(host.textContent).toContain('没有重发撤销请求');
});

it('retains only public command metadata and rejects foreign-owner or secret-bearing stored commands', async () => {
  vi.mocked(tools.configure).mockRejectedValue(new ToolConnectionError(0));
  await mount(); await chooseSaved(); await click('保存并绑定工具');
  const command = JSON.parse(localStorage.getItem(storage)!);
  expect(readToolCommand(JSON.stringify(command), 'alice')).toEqual(command);
  expect(readToolCommand(JSON.stringify(command), 'bob')).toBeNull();
  expect(readToolCommand(JSON.stringify({ ...command, password: secret }), 'alice')).toBeNull();
  expect(readToolCommand(JSON.stringify({ ...command, credential: { ...saved, password: secret } }), 'alice')).toBeNull();
});
