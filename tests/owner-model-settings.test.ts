// @vitest-environment happy-dom
import { webcrypto } from 'node:crypto';
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { api } from '../web/api.js';
import { ModelSettings } from '../web/ModelSettings.js';
import { ownerModel, ownerModelApi, ModelRequestError, type OwnerModel } from '../web/ownerModelApi.js';
import { personalRemoteApi } from '../web/personalRemoteApi.js';
import { modelEndpoint, readModelSetup, setupMetadata, type ModelSetup } from '../web/ownerModelSetup.js';

const credential = { credentialRef: 'credential-fixture', credentialRevision: 'credential-revision', providerId: 'byok-chat-v1', destination: 'https://api.openai.com', status: 'active' };
const row: OwnerModel = { reference: 'owner-model-fixture', revision: 'model-revision', connectionRef: 'binding-fixture', ownerId: 'alice', provider: 'openai', baseURL: 'https://api.openai.com/v1', model: 'fixture-model', credentialRef: credential.credentialRef, credentialRevision: credential.credentialRevision, updatedAt: '2026-10-09T00:00:00Z', status: 'configured', available: true, isDefault: false };
const storage = 'factory-model-setup:alice'; const secret = 'synthetic-test-key-only';
const goCredential = { ...credential, destination: 'https://opencode.ai' };
const thinkingRow: OwnerModel = { ...row, provider: 'openai-compatible', baseURL: 'https://opencode.ai/zen/go/v1', model: 'longcat-2.5-preview-free', thinkingMode: 'disabled' };
it('accepts the official Go Chat Completions base without accepting arbitrary provider prefixes', () => {
  const baseURL = 'https://opencode.ai/zen/go/v1';
  expect(modelEndpoint(baseURL)).toBe(baseURL);
  expect(ownerModel({ ...row, provider: 'openai-compatible', baseURL }, 'alice').baseURL).toBe(baseURL);
  expect(modelEndpoint(' HTTPS://MODELS.EXAMPLE.COM/v1 ')).toBe('https://models.example.com/v1');
  for (const url of ['https://other.example.com/zen/go/v1', 'https://opencode.ai/zen/v1', 'https://opencode.ai.evil.example/zen/go/v1']) expect(() => modelEndpoint(url)).toThrow();
});
let host: HTMLDivElement; let root: Root;
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); vi.stubGlobal('crypto', webcrypto); localStorage.clear();
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  vi.spyOn(api, 'session').mockResolvedValue({ id: 'alice', name: 'Alice', role: 'user' });
  vi.spyOn(ownerModelApi, 'capabilities').mockResolvedValue({ enabled: true, providers: ['openai', 'openai-compatible'], liveCompatibilityVerified: false });
  vi.spyOn(ownerModelApi, 'list').mockResolvedValue([]);
  vi.spyOn(ownerModelApi, 'configure').mockResolvedValue(row);
  vi.spyOn(ownerModelApi, 'default').mockResolvedValue({ ...row, isDefault: true });
  vi.spyOn(personalRemoteApi, 'saveCredential').mockResolvedValue(credential);
  vi.spyOn(personalRemoteApi, 'credentials').mockResolvedValue([]);
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
it('saves the official Go endpoint with an origin-bound credential and no model invocation', async () => {
  const baseURL = 'https://opencode.ai/zen/go/v1';
  vi.mocked(personalRemoteApi.saveCredential).mockResolvedValue({ ...credential, destination: 'https://opencode.ai' });
  vi.mocked(ownerModelApi.configure).mockResolvedValue({ ...row, provider: 'openai-compatible', baseURL });
  vi.mocked(ownerModelApi.default).mockResolvedValue({ ...row, provider: 'openai-compatible', baseURL, isDefault: true });
  await mount();
  await act(async () => { const select = host.querySelector('select')!; select.value = 'openai-compatible'; select.dispatchEvent(new Event('change', { bubbles: true })); });
  await fill('API 端点', baseURL); await save();
  expect(personalRemoteApi.saveCredential).toHaveBeenCalledWith(expect.objectContaining({ destination: 'https://opencode.ai', password: secret }), 'alice');
  expect(ownerModelApi.configure).toHaveBeenCalledWith('alice', expect.objectContaining({ baseURL }), undefined);
  expect(host.textContent).toContain('模型已保存并设为默认');
  expect(JSON.stringify(localStorage)).not.toContain(secret);
});
it('retains an unknown Go credential save without replaying its secret after refresh', async () => {
  vi.mocked(personalRemoteApi.saveCredential).mockRejectedValue(new Error('unconfirmed'));
  await mount();
  await act(async () => { const select = host.querySelector('select')!; select.value = 'openai-compatible'; select.dispatchEvent(new Event('change', { bubbles: true })); });
  await fill('API 端点', 'https://opencode.ai/zen/go/v1'); await save();
  expect(ownerModelApi.configure).not.toHaveBeenCalled();
  expect(localStorage.getItem(storage)).toContain('https://opencode.ai/zen/go/v1');
  expect(localStorage.getItem(storage)).not.toContain(secret);
  vi.mocked(personalRemoteApi.recoverCredential).mockRejectedValue(new Error('still unknown'));
  await act(async () => root.unmount()); root = createRoot(host); await mount();
  await act(async () => button('核对并继续原保存').click());
  expect(personalRemoteApi.saveCredential).toHaveBeenCalledTimes(1);
  expect(ownerModelApi.configure).not.toHaveBeenCalled();
  expect(host.textContent).toContain('上次保存尚未确认');
});
it('uses one Save to custody a secret, configure metadata and confirm the owner default without exposing the key', async () => {
  await mount(); expect(host.querySelector('[aria-label="API 密钥"]')?.getAttribute('type')).toBe('password');
  await save();
  expect(personalRemoteApi.saveCredential).toHaveBeenCalledTimes(1); expect(ownerModelApi.configure).toHaveBeenCalledTimes(1); expect(ownerModelApi.default).toHaveBeenCalledTimes(1);
  expect(personalRemoteApi.saveCredential).toHaveBeenCalledWith(expect.objectContaining({ password: secret, providerId: 'byok-chat-v1', username: 'api-key', destination: 'https://api.openai.com' }), 'alice');
  expect(ownerModelApi.configure).toHaveBeenCalledWith('alice', expect.objectContaining({ model: row.model, credentialRef: credential.credentialRef }), undefined);
  expect(JSON.stringify(vi.mocked(ownerModelApi.configure).mock.calls)).not.toContain(secret);
  expect(JSON.stringify(localStorage)).not.toContain(secret); expect(localStorage.getItem(storage)).toBeNull();
  expect(host.textContent).toContain('模型已保存并设为默认'); expect(host.textContent).not.toContain(secret);
  expect(host.textContent).toContain('已有远端 OpenResearch 服务继续使用其自身配置。');
});
it('recovers an uncertain vault save after remount without replaying the key or changing configuration', async () => {
  vi.mocked(personalRemoteApi.saveCredential).mockRejectedValue(new Error(secret + ' unsafe transport echo'));
  await mount(); await save(); const request = vi.mocked(personalRemoteApi.saveCredential).mock.calls[0][0].requestId;
  expect(localStorage.getItem(storage)).not.toContain(secret); expect(host.textContent).not.toContain(secret);
  await act(async () => root.unmount()); root = createRoot(host); await mount();
  await act(async () => button('核对并继续原保存').click());
  expect(personalRemoteApi.recoverCredential).toHaveBeenCalledWith(request, 'alice'); expect(personalRemoteApi.saveCredential).toHaveBeenCalledTimes(1);
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
it('accepts the actual persisted thinking field and rejects invalid values, scope and unknown fields', () => {
  expect(ownerModel(thinkingRow, 'alice')).toBe(thinkingRow);
  for (const thinkingMode of ['enabled', 'default', null, false, {}, 0]) expect(() => ownerModel({ ...thinkingRow, thinkingMode }, 'alice')).toThrow();
  for (const value of [{ ...thinkingRow, password: secret }, { ...thinkingRow, otherOption: 'disabled' }, { ...thinkingRow, model: 'other-model' }, { ...thinkingRow, baseURL: row.baseURL }]) expect(() => ownerModel(value, 'alice')).toThrow();
});
it('reads actual JSON thinking metadata on the settings page and validates default/revoke receipts', async () => {
  vi.mocked(ownerModelApi.list).mockRestore(); vi.mocked(ownerModelApi.default).mockRestore();
  let current = thinkingRow;
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
    const path = String(input);
    if (path.endsWith('/auth/session')) return new Response(JSON.stringify({ authenticated: true, csrfToken: 'synthetic-csrf-fixture-only' }));
    if (path.endsWith('/default')) current = { ...thinkingRow, isDefault: true };
    if (path.endsWith('/revoke')) current = { ...thinkingRow, status: 'revoked', available: false, isDefault: false };
    if (options?.method === 'POST') expect(options.headers).toMatchObject({ 'X-Factory-Expected-Owner': 'alice' });
    return new Response(JSON.stringify(path.endsWith('/personal-models') ? [current] : current));
  }));
  await mount(); expect(host.textContent).toContain(thinkingRow.model); expect(host.textContent).not.toContain('暂时无法读取模型设置');
  await act(async () => { button('设为默认').click(); await new Promise(resolve => setTimeout(resolve, 20)); }); expect(host.textContent).toContain('默认模型已更新');
  await act(async () => button('撤销模型').click()); await act(async () => { button('确认撤销').click(); await new Promise(resolve => setTimeout(resolve, 20)); });
  expect(host.textContent).toContain('模型已撤销，不能用于新任务');
  expect(ownerModelApi.configure).not.toHaveBeenCalled(); expect(personalRemoteApi.saveCredential).not.toHaveBeenCalled();
});
it('retains scoped thinking metadata through password rotation, lost configure acknowledgement and refresh', async () => {
  const original = { ...thinkingRow, isDefault: true };
  const updated = { ...original, credentialRevision: 'rotated-r2', revision: 'model-r2' };
  vi.mocked(ownerModelApi.list).mockResolvedValue([original]);
  vi.mocked(personalRemoteApi.credentials).mockResolvedValue([goCredential]);
  const rotate = vi.spyOn(ownerModelApi, 'rotateCredential').mockResolvedValue({ ...goCredential, credentialRevision: 'rotated-r2' });
  vi.mocked(ownerModelApi.configure).mockRejectedValueOnce(new ModelRequestError(0)).mockResolvedValue(updated);
  vi.mocked(ownerModelApi.default).mockResolvedValue(updated);
  await mount(); await act(async () => button('更新密钥').click()); await fill('API 密钥', secret);
  await act(async () => button('保存新密钥').click());
  const request = vi.mocked(ownerModelApi.configure).mock.calls[0][1]; expect(request.thinkingMode).toBe('disabled');
  expect(localStorage.getItem(storage)).toContain('"thinkingMode":"disabled"'); expect(localStorage.getItem(storage)).not.toContain(secret);
  await act(async () => root.unmount()); root = createRoot(host); await mount();
  await act(async () => button('核对并继续原保存').click());
  expect(ownerModelApi.configure).toHaveBeenNthCalledWith(2, 'alice', request, original.reference);
  expect(rotate).toHaveBeenCalledTimes(1); expect(host.textContent).toContain('密钥已更新。旧任务绑定会按服务端规则重新检查。');
});
it('keeps thinking disabled on credential rebind and refuses a receipt that silently loses it', async () => {
  const original = { ...thinkingRow, isDefault: true, available: false, status: 'credential_unavailable' as const };
  vi.mocked(ownerModelApi.list).mockResolvedValue([original]);
  vi.mocked(personalRemoteApi.credentials).mockResolvedValue([{ ...goCredential, credentialRevision: 'rotated-r2' }]);
  vi.mocked(ownerModelApi.configure).mockResolvedValue({ ...thinkingRow, isDefault: true, credentialRevision: 'rotated-r2', thinkingMode: undefined });
  await mount(); await act(async () => button('绑定更新后的凭据').click());
  expect(ownerModelApi.configure).toHaveBeenCalledWith('alice', expect.objectContaining({ thinkingMode: 'disabled' }), original.reference);
  expect(ownerModelApi.default).not.toHaveBeenCalled(); expect(host.textContent).toContain('设置尚未确认');
  expect(localStorage.getItem(storage)).toContain('"thinkingMode":"disabled"'); expect(personalRemoteApi.saveCredential).not.toHaveBeenCalled();
});
it('persists thinking as bounded metadata and rejects malformed storage values', () => {
  const setup: ModelSetup = { owner: 'alice', provider: thinkingRow.provider, baseURL: thinkingRow.baseURL, model: thinkingRow.model, thinkingMode: 'disabled', credentialRequest: 'request-key-fixture', modelRequest: 'request-model-fixture', defaultRequest: 'request-default-fixture', stage: 'model', chooseDefault: true, credential: goCredential };
  expect(readModelSetup(JSON.stringify(setupMetadata(setup)), 'alice')).toEqual(setup);
  for (const thinkingMode of ['default', 'enabled', null, false, {}]) expect(readModelSetup(JSON.stringify({ ...setup, thinkingMode }), 'alice')).toBeNull();
  expect(readModelSetup(JSON.stringify({ ...setup, baseURL: row.baseURL }), 'alice')).toBeNull();
});
it('persists only owner-scoped safe setup metadata and rejects unsupported destinations before custody', () => {
  const setup: ModelSetup = { owner: 'alice', provider: 'openai', baseURL: row.baseURL, model: row.model, credentialRequest: 'request-key-fixture', modelRequest: 'request-model-fixture', defaultRequest: 'request-default-fixture', stage: 'credential', chooseDefault: true };
  const metadata = setupMetadata({ ...setup, password: secret } as ModelSetup); expect(JSON.stringify(metadata)).not.toContain(secret);
  expect(readModelSetup(JSON.stringify(metadata), 'bob')).toBeNull(); expect(readModelSetup(JSON.stringify(metadata), 'alice')).toEqual(setup);
  for (const value of ['http://models.example/v1', 'https://user:pass@models.example/v1', 'https://models.example/v1?api_key=secret', 'https://127.0.0.1/v1', 'https://models.example/other']) expect(() => modelEndpoint(value)).toThrow();
});

it('clears stale drafts when another tab changes the cookie owner before Save, without submitting any secret', async () => {
  await mount(); vi.mocked(api.session).mockResolvedValue({ id: 'bob', name: 'Bob', role: 'user' }); await save();
  expect(personalRemoteApi.saveCredential).not.toHaveBeenCalled(); expect(ownerModelApi.configure).not.toHaveBeenCalled();
  expect(host.querySelector('[aria-label="API 密钥"]')).toBeNull(); expect(host.textContent).toContain('当前登录账户已改变');
  expect(localStorage.getItem(storage)).toBeNull();
});
it('stops metadata writes when the account changes after secret custody', async () => {
  vi.mocked(api.session).mockResolvedValueOnce({ id: 'alice', name: 'Alice', role: 'user' }).mockResolvedValue({ id: 'bob', name: 'Bob', role: 'user' });
  await mount(); await save(); expect(personalRemoteApi.saveCredential).toHaveBeenCalledTimes(1);
  expect(ownerModelApi.configure).not.toHaveBeenCalled(); expect(ownerModelApi.default).not.toHaveBeenCalled();
  expect(host.textContent).toContain('当前登录账户已改变'); expect(JSON.stringify(localStorage)).not.toContain(secret);
});
it('clears drafts on a server-side owner mismatch in the race after live preflight', async () => {
  vi.mocked(personalRemoteApi.saveCredential).mockRejectedValue(new (await import('../web/personalRemoteApi.js')).RemoteRequestError(true, 'EXPECTED_OWNER_MISMATCH'));
  await mount(); await save(); expect(ownerModelApi.configure).not.toHaveBeenCalled(); expect(host.textContent).toContain('当前登录账户已改变');
  expect(host.querySelector('[aria-label="API 密钥"]')).toBeNull();
});

it('explicitly binds the latest saved credential revision without asking for or replaying a secret', async () => {
  const stale = { ...row, status: 'credential_unavailable' as const, available: false, isDefault: true };
  vi.mocked(ownerModelApi.list).mockResolvedValue([stale]);
  vi.mocked(personalRemoteApi.credentials).mockResolvedValue([{ ...credential, credentialRevision: 'rotated-r2' }]);
  vi.mocked(ownerModelApi.configure).mockResolvedValue({ ...row, isDefault: true, credentialRevision: 'rotated-r2', connectionRef: 'updated-connection' });
  await mount(); expect(button('绑定更新后的凭据')).toBeDefined(); await act(async () => button('绑定更新后的凭据').click());
  expect(ownerModelApi.configure).toHaveBeenCalledWith('alice', expect.objectContaining({ credentialRef: credential.credentialRef, credentialRevision: 'rotated-r2' }), row.reference);
  expect(personalRemoteApi.saveCredential).not.toHaveBeenCalled(); expect(personalRemoteApi.recoverCredential).not.toHaveBeenCalled();
  expect(host.textContent).toContain('旧任务绑定会按服务端规则重新检查'); expect(JSON.stringify(localStorage)).not.toContain(secret);
});
it('creates a new model from an existing matching reference without custody or secret input', async () => {
  vi.mocked(personalRemoteApi.credentials).mockResolvedValue([credential, { ...credential, credentialRef: 'wrong-provider', providerId: 'opencode-serve-v1' }, { ...credential, credentialRef: 'other-origin', destination: 'https://other.example.org' }, { ...credential, credentialRef: 'revoked-ref', status: 'revoked' }]);
  await mount(); await fill('模型名称', row.model);
  await act(async () => { const select = host.querySelector<HTMLSelectElement>('[aria-label="模型凭据来源"]')!; select.value = 'saved'; select.dispatchEvent(new Event('change', { bubbles: true })); });
  expect(host.querySelector('[aria-label="API 密钥"]')).toBeNull();
  const select = host.querySelector<HTMLSelectElement>('[aria-label="已保存的模型凭据"]')!;
  expect([...select.options].map(o => o.value)).toEqual(['', credential.credentialRef]);
  await act(async () => { select.value = credential.credentialRef; select.dispatchEvent(new Event('change', { bubbles: true })); });
  await act(async () => button('保存模型并设为默认').click());
  expect(ownerModelApi.configure).toHaveBeenCalledWith('alice', expect.objectContaining({ credentialRef: credential.credentialRef, credentialRevision: credential.credentialRevision }), undefined);
  expect(personalRemoteApi.saveCredential).not.toHaveBeenCalled(); expect(personalRemoteApi.recoverCredential).not.toHaveBeenCalled(); expect(localStorage.getItem(storage)).toBeNull();
});
it('retains only metadata when saved-reference configuration acknowledgement is lost', async () => {
  vi.mocked(personalRemoteApi.credentials).mockResolvedValue([credential]); vi.mocked(ownerModelApi.configure).mockRejectedValueOnce(new ModelRequestError(0));
  await mount(); await fill('模型名称', row.model);
  await act(async () => { const source = host.querySelector<HTMLSelectElement>('[aria-label="模型凭据来源"]')!; source.value = 'saved'; source.dispatchEvent(new Event('change', { bubbles: true })); });
  await act(async () => { const saved = host.querySelector<HTMLSelectElement>('[aria-label="已保存的模型凭据"]')!; saved.value = credential.credentialRef; saved.dispatchEvent(new Event('change', { bubbles: true })); });
  await act(async () => button('保存模型并设为默认').click()); const original = vi.mocked(ownerModelApi.configure).mock.calls[0][1];
  await act(async () => button('核对并继续原保存').click());
  expect(ownerModelApi.configure).toHaveBeenNthCalledWith(2, 'alice', original, undefined); expect(personalRemoteApi.saveCredential).not.toHaveBeenCalled(); expect(personalRemoteApi.recoverCredential).not.toHaveBeenCalled();
});
