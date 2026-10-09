// @vitest-environment happy-dom
import { webcrypto } from 'node:crypto';
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { api } from '../web/api.js';
import { PersonalCredentials } from '../web/PersonalCredentials.js';
import { personalRemoteApi, RemoteRequestError } from '../web/personalRemoteApi.js';
import { credentialReceipt, matchCredentialReceipt, readCredentialCommand } from '../web/credentialManagement.js';

const row = { credentialRef: 'credential-fixture', credentialRevision: 'r1', providerId: 'openresearch-personal-session-v1', destination: 'https://service.example.org', status: 'active' };
const secret = 'synthetic-credential-only'; const storage = 'factory-credential-management:alice';
let host: HTMLDivElement; let root: Root;
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); vi.stubGlobal('crypto', webcrypto); localStorage.clear();
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  vi.spyOn(api, 'session').mockResolvedValue({ id: 'alice', name: 'Alice', role: 'user' });
  vi.spyOn(personalRemoteApi, 'credentialAvailability').mockResolvedValue({ enabled: true, providerIds: [row.providerId, 'byok-chat-v1'] });
  vi.spyOn(personalRemoteApi, 'credentials').mockResolvedValue([row]);
  vi.spyOn(personalRemoteApi, 'saveCredential').mockResolvedValue(row);
  vi.spyOn(personalRemoteApi, 'rotateCredential').mockResolvedValue({ ...row, credentialRevision: 'r2' });
  vi.spyOn(personalRemoteApi, 'revokeCredential').mockResolvedValue({ ...row, status: 'revoked' });
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function mount() { await act(async () => root.render(createElement(PersonalCredentials, { ownerId: 'alice', onChanged: vi.fn(), onModels: vi.fn() }))); }
const button = (name: string) => Array.from(host.querySelectorAll('button')).find(b => b.textContent === name)!;
async function field(label: string, value: string) {
  await act(async () => {
    const el = host.querySelector<HTMLInputElement | HTMLSelectElement>(`[aria-label="${label}"]`)!;
    const select = el.tagName === 'SELECT'; Object.getOwnPropertyDescriptor(select ? HTMLSelectElement.prototype : HTMLInputElement.prototype, 'value')!.set!.call(el, value);
    el.dispatchEvent(new Event(select ? 'change' : 'input', { bubbles: true }));
  });
}
async function fillSecret() { await field('新的凭据秘密', secret); await act(async () => host.querySelector<HTMLInputElement>('input[type=checkbox]')!.click()); }
async function add() { await act(async () => button('添加个人凭据').click()); await field('凭据用途', row.providerId); await field('凭据服务源', row.destination); await fillSecret(); }
it('adds a credential once with explicit custody consent, clears input and persists no secret', async () => {
  await mount(); await add(); expect(host.querySelector('[aria-label="新的凭据秘密"]')?.getAttribute('type')).toBe('password');
  await act(async () => { button('安全保存个人凭据').click(); button('安全保存个人凭据').click(); });
  expect(personalRemoteApi.saveCredential).toHaveBeenCalledTimes(1);
  expect(personalRemoteApi.saveCredential).toHaveBeenCalledWith(expect.objectContaining({ username: 'bearer', password: secret }), 'alice');
  expect(host.textContent).toContain('凭据已安全保存'); expect(host.textContent).not.toContain(secret); expect(JSON.stringify(localStorage)).not.toContain(secret);
  expect(localStorage.getItem(storage)).toBeNull(); expect(personalRemoteApi.credentials).toHaveBeenCalledWith(expect.any(AbortSignal), 'alice');
});
it('rotates the exact current revision and explicitly requires new connection binding', async () => {
  await mount(); await act(async () => button('更换凭据').click()); await fillSecret();
  await act(async () => button('保存更换后的凭据').click());
  expect(personalRemoteApi.rotateCredential).toHaveBeenCalledWith(row, 'bearer', secret, expect.any(String), 'alice');
  expect(host.textContent).toContain('显式绑定新版本'); expect(host.textContent).toContain('原任务不会自动换用新凭据'); expect(host.textContent).not.toContain(secret);
});
it('requires explicit revoke confirmation, binds the expected owner and retains task context', async () => {
  await mount(); await act(async () => button('撤销凭据').click()); expect(personalRemoteApi.revokeCredential).not.toHaveBeenCalled();
  await act(async () => button('确认撤销凭据').click());
  expect(personalRemoteApi.revokeCredential).toHaveBeenCalledWith(row, expect.any(String), 'alice'); expect(host.textContent).toContain('原任务、上下文与结果保留');
});
it('recovers an ambiguous rotation after remount by receipt without resubmitting its secret', async () => {
  vi.mocked(personalRemoteApi.rotateCredential).mockRejectedValue(new Error(secret));
  vi.spyOn(personalRemoteApi, 'recoverCredential').mockResolvedValue({ ...row, credentialRevision: 'r2' });
  await mount(); await act(async () => button('更换凭据').click()); await fillSecret(); await act(async () => button('保存更换后的凭据').click());
  const requestId = vi.mocked(personalRemoteApi.rotateCredential).mock.calls[0][3];
  expect(host.textContent).not.toContain(secret); expect(JSON.stringify(localStorage)).not.toContain(secret); expect(button('添加个人凭据')).toBeUndefined();
  await act(async () => root.unmount()); root = createRoot(host); await mount(); await act(async () => button('核对原凭据操作').click());
  expect(personalRemoteApi.recoverCredential).toHaveBeenCalledWith(requestId, 'alice'); expect(personalRemoteApi.rotateCredential).toHaveBeenCalledTimes(1); expect(localStorage.getItem(storage)).toBeNull();
});
it('blocks and clears a stale owner before mutation and on server-side race rejection', async () => {
  await mount(); await add(); vi.mocked(api.session).mockResolvedValue({ id: 'bob', name: 'Bob', role: 'user' });
  await act(async () => button('安全保存个人凭据').click()); expect(personalRemoteApi.saveCredential).not.toHaveBeenCalled();
  expect(host.querySelector('[aria-label="新的凭据秘密"]')).toBeNull(); expect(host.textContent).toContain('当前登录账户已改变');
});
it('clears secret drafts on expected-owner mismatch after preflight', async () => {
  vi.mocked(personalRemoteApi.saveCredential).mockRejectedValue(new RemoteRequestError(true, 'EXPECTED_OWNER_MISMATCH'));
  await mount(); await add(); await act(async () => button('安全保存个人凭据').click());
  expect(host.querySelector('[aria-label="新的凭据秘密"]')).toBeNull(); expect(host.textContent).toContain('当前登录账户已改变'); expect(localStorage.getItem(storage)).toBeNull();
});
it('settles a disabled deployment or read error without secret input or false success', async () => {
  vi.mocked(personalRemoteApi.credentialAvailability).mockRejectedValueOnce(new Error(secret)); await mount();
  expect(host.textContent).toContain('暂时无法读取凭据'); expect(host.textContent).not.toContain(secret);
  vi.mocked(personalRemoteApi.credentialAvailability).mockResolvedValue({ enabled: false, providerIds: [] });
  await act(async () => button('重新读取凭据').click()); expect(host.textContent).toContain('不需要接收你的明文密钥'); expect(host.querySelector('input[type=password]')).toBeNull();
});
it('keeps a retired provider credential revocable while disabling its rotation', async () => {
  vi.mocked(personalRemoteApi.credentialAvailability).mockResolvedValue({ enabled: true, providerIds: ['byok-chat-v1'] });
  await mount(); expect(button('更换凭据').disabled).toBe(true); expect(button('撤销凭据').disabled).toBe(false);
  await act(async () => button('撤销凭据').click()); await act(async () => button('确认撤销凭据').click());
  expect(personalRemoteApi.revokeCredential).toHaveBeenCalledWith(row, expect.any(String), 'alice');
});
it('rejects secret-bearing, foreign pending, changed-scope and wrong-revision receipts', () => {
  const command = { owner: 'alice', action: 'rotate' as const, requestId: 'fixture-request', providerId: row.providerId, destination: row.destination, credentialRef: row.credentialRef, credentialRevision: row.credentialRevision };
  expect(readCredentialCommand(JSON.stringify(command), 'alice')).toEqual(command); expect(readCredentialCommand(JSON.stringify(command), 'bob')).toBeNull();
  expect(readCredentialCommand(JSON.stringify({ ...command, password: secret }), 'alice')).toBeNull();
  for (const invalid of [{ ...row, password: secret }, { ...row, destination: 'https://user:secret@example.org' }, { ...row, status: 'unknown' }]) expect(() => credentialReceipt(invalid)).toThrow();
  expect(() => matchCredentialReceipt(row, command)).toThrow(); expect(() => matchCredentialReceipt({ ...row, credentialRevision: 'r2', destination: 'https://other.example.org' }, command)).toThrow();
  expect(matchCredentialReceipt({ ...row, credentialRevision: 'r2' }, command).credentialRevision).toBe('r2');
});
