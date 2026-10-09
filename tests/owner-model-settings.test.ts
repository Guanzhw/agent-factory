// @vitest-environment happy-dom
import { webcrypto } from 'node:crypto';
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { ModelSettings } from '../web/ModelSettings.js';
import { ownerModel, ownerModelApi, ModelRequestError, type OwnerModel } from '../web/ownerModelApi.js';
import { personalRemoteApi } from '../web/personalRemoteApi.js';
import { modelEndpoint, readModelSetup, setupMetadata, type ModelSetup } from '../web/ownerModelSetup.js';

const credential = { credentialRef: 'credential-fixture', credentialRevision: 'credential-revision', providerId: 'byok-chat-v1', destination: 'https://api.openai.com', status: 'active' };
const row: OwnerModel = { reference: 'owner-model-fixture', revision: 'model-revision', connectionRef: 'binding-fixture', ownerId: 'alice', provider: 'openai', baseURL: 'https://api.openai.com/v1', model: 'fixture-model', credentialRef: credential.credentialRef, credentialRevision: credential.credentialRevision, updatedAt: '2026-10-09T00:00:00Z', status: 'configured', available: true, isDefault: false };
const storage = 'factory-model-setup:alice'; const secret = 'synthetic-test-key-only';
let host: HTMLDivElement; let root: Root;
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); vi.stubGlobal('crypto', webcrypto); localStorage.clear();
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  vi.spyOn(ownerModelApi, 'capabilities').mockResolvedValue({ enabled: true, providers: ['openai', 'openai-compatible'], liveCompatibilityVerified: false });
  vi.spyOn(ownerModelApi, 'list').mockResolvedValue([]);
  vi.spyOn(ownerModelApi, 'configure').mockResolvedValue(row);
  vi.spyOn(ownerModelApi, 'default').mockResolvedValue({ ...row, isDefault: true });
  vi.spyOn(personalRemoteApi, 'saveCredential').mockResolvedValue(credential);
  vi.spyOn(personalRemoteApi, 'recoverCredential').mockResolvedValue(credential);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function mount() { await act(async () => root.render(createElement(ModelSettings, { ownerId: 'alice', onResearch: vi.fn() }))); }
const button = (name: string) => Array.from(host.querySelectorAll('button')).find(b => b.textContent === name)!;
async function fill(name: string, value: string) {
  await act(async () => {
    const input = host.querySelector<HTMLInputElement>(`[aria-label="${name}"]`)!;
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
}
async function save() { await fill('模型名称', row.model); await fill('API 密钥', secret); await act(async () => { button('保存并设为默认').click(); button('保存并设为默认').click(); }); }
it('uses one Save to custody a secret, configure metadata and confirm the owner default without exposing the key', async () => {
  await mount(); expect(host.querySelector('[aria-label="API 密钥"]')?.getAttribute('type')).toBe('password');
  await save();
  expect(personalRemoteApi.saveCredential).toHaveBeenCalledTimes(1); expect(ownerModelApi.configure).toHaveBeenCalledTimes(1); expect(ownerModelApi.default).toHaveBeenCalledTimes(1);
  expect(personalRemoteApi.saveCredential).toHaveBeenCalledWith(expect.objectContaining({ password: secret, providerId: 'byok-chat-v1', username: 'api-key', destination: 'https://api.openai.com' }));
  expect(ownerModelApi.configure).toHaveBeenCalledWith('alice', expect.objectContaining({ model: row.model, credentialRef: credential.credentialRef }), undefined);
  expect(JSON.stringify(vi.mocked(ownerModelApi.configure).mock.calls)).not.toContain(secret);
  expect(JSON.stringify(localStorage)).not.toContain(secret); expect(localStorage.getItem(storage)).toBeNull();
  expect(host.textContent).toContain('模型已保存并设为默认'); expect(host.textContent).not.toContain(secret);
  expect(host.textContent).toContain('OpenResearch 原生远程会话继续使用其服务自身的模型配置');
});
it('recovers an uncertain vault save after remount without replaying the key or changing configuration', async () => {
  vi.mocked(personalRemoteApi.saveCredential).mockRejectedValue(new Error(secret + ' unsafe transport echo'));
  await mount(); await save(); const request = vi.mocked(personalRemoteApi.saveCredential).mock.calls[0][0].requestId;
  expect(localStorage.getItem(storage)).not.toContain(secret); expect(host.textContent).not.toContain(secret);
  await act(async () => root.unmount()); root = createRoot(host); await mount();
  await act(async () => button('核对并继续原保存').click());
  expect(personalRemoteApi.recoverCredential).toHaveBeenCalledWith(request); expect(personalRemoteApi.saveCredential).toHaveBeenCalledTimes(1);
  expect(ownerModelApi.configure).toHaveBeenCalledTimes(1); expect(host.textContent).toContain('模型已保存并设为默认');
});
it('replays only the original non-secret metadata request when configuration acknowledgement is lost', async () => {
  vi.mocked(ownerModelApi.configure).mockRejectedValueOnce(new ModelRequestError(0));
  await mount(); await save(); const original = vi.mocked(ownerModelApi.configure).mock.calls[0][1];
  expect(localStorage.getItem(storage)).not.toContain(secret);
  await act(async () => button('核对并继续原保存').click());
  expect(personalRemoteApi.saveCredential).toHaveBeenCalledTimes(1); expect(ownerModelApi.configure).toHaveBeenNthCalledWith(2, 'alice', original, undefined);
  expect(ownerModelApi.default).toHaveBeenCalledTimes(1);
});
it('does not claim default selection when the server reports a different current default', async () => {
  vi.mocked(ownerModelApi.default).mockResolvedValue(row); await mount(); await save();
  expect(host.textContent).not.toContain('模型已保存并设为默认'); expect(localStorage.getItem(storage)).not.toBeNull();
  expect(host.textContent).toContain('上次保存尚未确认');
});
it('settles a failed read with a retry action and exposes no secret field when custody is unavailable', async () => {
  vi.mocked(ownerModelApi.capabilities).mockRejectedValueOnce(new ModelRequestError(0)); await mount();
  expect(host.textContent).toContain('暂时无法读取模型设置'); expect(host.textContent).not.toContain('正在读取模型设置');
  vi.mocked(ownerModelApi.capabilities).mockResolvedValue({ enabled: false, providers: ['openai'], liveCompatibilityVerified: false });
  await act(async () => button('重新读取设置').click());
  expect(host.textContent).toContain('无需向管理员发送 API 密钥'); expect(host.querySelector('[aria-label="API 密钥"]')).toBeNull();
});
it('rejects foreign, unexpected secret-bearing, and malformed model receipts', () => {
  for (const value of [{ ...row, ownerId: 'bob' }, { ...row, password: secret }, { ...row, available: false }, { ...row, baseURL: 'javascript:alert(1)' }]) expect(() => ownerModel(value, 'alice')).toThrow();
  expect(ownerModel(row, 'alice')).toBe(row);
});
it('persists only owner-scoped safe setup metadata and rejects unsupported destinations before custody', () => {
  const setup: ModelSetup = { owner: 'alice', provider: 'openai', baseURL: row.baseURL, model: row.model, credentialRequest: 'request-key-fixture', modelRequest: 'request-model-fixture', defaultRequest: 'request-default-fixture', stage: 'credential', chooseDefault: true };
  const metadata = setupMetadata({ ...setup, password: secret } as ModelSetup); expect(JSON.stringify(metadata)).not.toContain(secret);
  expect(readModelSetup(JSON.stringify(metadata), 'bob')).toBeNull(); expect(readModelSetup(JSON.stringify(metadata), 'alice')).toEqual(setup);
  for (const value of ['http://models.example/v1', 'https://user:pass@models.example/v1', 'https://models.example/v1?api_key=secret', 'https://127.0.0.1/v1', 'https://models.example/other']) expect(() => modelEndpoint(value)).toThrow();
});
