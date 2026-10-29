// @vitest-environment happy-dom
import { webcrypto } from 'node:crypto';
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { api } from '../web/api.js';
import { ModelSettings } from '../web/ModelSettings.js';
import { ownerModel, ownerModelApi, ModelRequestError, type OwnerModel, type OwnerModelReceipt } from '../web/ownerModelApi.js';
import { personalRemoteApi } from '../web/personalRemoteApi.js';
import { modelEndpoint, readModelSetup, setupMetadata, type ModelSetup } from '../web/ownerModelSetup.js';
import { MODEL_PROVIDER_PRESETS } from '../web/modelProviderConfig.js';

const credential = { credentialRef: 'credential-fixture', credentialRevision: 'credential-revision', providerId: 'byok-chat-v1', destination: 'https://api.openai.com', status: 'active' };
const row: OwnerModel = { reference: 'owner-model-fixture', revision: 'model-revision', connectionRef: 'binding-fixture', ownerId: 'alice', visibility: 'personal', isOwner: true, provider: 'openai', baseURL: 'https://api.openai.com/v1', model: 'fixture-model', credentialRef: credential.credentialRef, credentialRevision: credential.credentialRevision, updatedAt: '2026-10-09T00:00:00Z', status: 'configured', available: true, isDefault: false };
const storage = 'factory-model-setup:alice'; const secret = 'synthetic-test-key-only';
const goCredential = { ...credential, destination: 'https://opencode.ai' };
const thinkingRow: OwnerModel = { ...row, provider: 'openai-compatible', baseURL: 'https://opencode.ai/zen/go/v1', model: 'longcat-2.5-preview-free', thinkingMode: 'disabled' };

it('uses a team model as default while preserving owner-only credential controls', async () => {
  const shared: OwnerModel = { reference: row.reference, revision: row.revision, ownerId: 'bob',
    visibility: 'team', isOwner: false, provider: row.provider, baseURL: row.baseURL, model: row.model,
    updatedAt: row.updatedAt, status: 'configured', available: true, isDefault: false, maxOutputTokens: 16384 };
  expect(ownerModel(shared, 'alice')).toEqual(shared);
  expect(() => ownerModel({ ...shared, credentialRef: 'owner-vault-ref' }, 'alice')).toThrow();
  vi.mocked(ownerModelApi.list).mockResolvedValue([shared]);
  vi.mocked(ownerModelApi.default).mockResolvedValue({ ...shared, isDefault: true, connectionRef: 'actor-binding' });
  await mount();
  expect(button('更新密钥')).toBeUndefined(); expect(button('撤销模型')).toBeUndefined();
  expect(button('共享给团队')).toBeUndefined();
  expect(button('调整输出额度')).toBeUndefined();
  expect(host.textContent).toContain('单次输出上限：16384 token');
  await act(async () => button('设为默认').click());
  expect(ownerModelApi.default).toHaveBeenCalledWith('alice', row.reference, expect.any(String));
});

it('lets the resource owner change model visibility', async () => {
  vi.mocked(ownerModelApi.list).mockResolvedValue([row]);
  const share = vi.spyOn(ownerModelApi, 'sharing');
  const dispatched = new Promise<void>(resolve => {
    share.mockImplementation(async () => { resolve(); return { ...row, visibility: 'team' }; });
  });
  await mount();
  await act(async () => {
    button('共享给团队').click();
    await dispatched;
  });
  expect(share).toHaveBeenCalledTimes(1);
  expect(share).toHaveBeenCalledWith('alice', row.reference, 'team', expect.any(String));
  expect(host.textContent).toContain('团队成员现在可使用此模型。');
});

it('configures an unauthenticated model without a placeholder key or credential write', async () => {
  const publicModel: OwnerModel = { ...row, credentialRef: null, credentialRevision: null };
  vi.mocked(ownerModelApi.configure).mockResolvedValue(publicModel);
  vi.mocked(ownerModelApi.default).mockResolvedValue({ ...publicModel, isDefault: true });
  await mount(); await fill('模型名称', row.model);
  await act(async () => { const source = host.querySelector<HTMLSelectElement>('[aria-label="模型凭据来源"]')!;
    source.value = 'none'; source.dispatchEvent(new Event('change', { bubbles: true })); });
  expect(host.querySelector('[aria-label="API 密钥"]')).toBeNull();
  await act(async () => button('保存并设为默认').click());
  expect(ownerModelApi.configure).toHaveBeenCalledWith('alice', expect.not.objectContaining({ credentialRef: expect.anything() }), undefined);
  expect(personalRemoteApi.saveCredential).not.toHaveBeenCalled();
  expect(ownerModelApi.default).toHaveBeenCalled();
  expect(localStorage.getItem(storage)).toBeNull();
});

it('recovers an unknown sharing request by its original receipt without another write', async () => {
  vi.mocked(ownerModelApi.list).mockResolvedValue([row]);
  const share = vi.spyOn(ownerModelApi, 'sharing');
  const dispatched = new Promise<void>(resolve => {
    share.mockImplementation(async () => { resolve(); throw new ModelRequestError(0); });
  });
  vi.mocked(ownerModelApi.recover).mockImplementation(async (_owner, requestId) => ({ ownerId: 'alice', requestId,
    action: 'model.sharing', result: { ...row, visibility: 'team' }, completedAt: '2026-10-09T00:00:01Z' }));
  await mount();
  await act(async () => {
    button('共享给团队').click();
    await dispatched;
  });
  expect(share).toHaveBeenCalledTimes(1);
  expect(button('共享给团队').disabled).toBe(true);
  await act(async () => button('核对原共享请求').click());
  expect(ownerModelApi.recover).toHaveBeenCalledWith('alice', share.mock.calls[0][3]);
  expect(share).toHaveBeenCalledTimes(1);
  expect(button('核对原共享请求')).toBeUndefined();
});
it('accepts model API bases with custom paths and local network destinations', () => {
  const baseURL = 'https://opencode.ai/zen/go/v1';
  expect(modelEndpoint(baseURL)).toBe(baseURL);
  expect(modelEndpoint('https://opencode.ai/inference/go/v1')).toBe('https://opencode.ai/inference/go/v1');
  expect(ownerModel({ ...row, provider: 'openai-compatible', baseURL }, 'alice').baseURL).toBe(baseURL);
  expect(modelEndpoint(' HTTPS://MODELS.EXAMPLE.COM/v1 ')).toBe('https://models.example.com/v1');
  for (const url of ['http://localhost:11434', 'http://127.0.0.1:8080/custom/api', 'https://192.168.1.2:9443/api', 'http://[::1]:1234/v1']) expect(modelEndpoint(url)).toBe(url);
  expect(modelEndpoint('http://localhost:11434/v1/')).toBe('http://localhost:11434/v1');
  for (const url of ['https://other.example.com/zen/go/v1', 'https://opencode.ai/zen/v1', 'https://opencode.ai.evil.example/zen/go/v1']) expect(modelEndpoint(url)).toBe(url);
});
let host: HTMLDivElement; let root: Root;
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); vi.stubGlobal('crypto', webcrypto); localStorage.clear(); sessionStorage.clear();
  vi.stubGlobal('fetch', vi.fn(() => { throw new Error('Network forbidden in model settings test'); }));
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  vi.spyOn(api, 'session').mockResolvedValue({ id: 'alice', name: 'Alice', role: 'user' });
  vi.spyOn(ownerModelApi, 'capabilities').mockResolvedValue({ enabled: true, providers: ['openai', 'openai-compatible'], liveCompatibilityVerified: false });
  vi.spyOn(ownerModelApi, 'list').mockResolvedValue([]);
  vi.spyOn(ownerModelApi, 'configure').mockResolvedValue(row);
  vi.spyOn(ownerModelApi, 'default').mockResolvedValue({ ...row, isDefault: true });
  vi.spyOn(ownerModelApi, 'recover').mockImplementation(async (_owner, requestId): Promise<OwnerModelReceipt> => ({ ownerId: 'alice', requestId, action: 'model.configure', result: row, completedAt: '2026-10-09T00:00:01Z' }));
  vi.spyOn(personalRemoteApi, 'saveCredential').mockResolvedValue(credential);
  vi.spyOn(personalRemoteApi, 'credentials').mockResolvedValue([]);
  vi.spyOn(personalRemoteApi, 'recoverCredential').mockResolvedValue(credential);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function mount() { await act(async () => root.render(createElement(ModelSettings, { ownerId: 'alice', onBack: vi.fn() }))); }
const button = (name: string) => Array.from(host.querySelectorAll('button')).find(b => b.textContent === name)!;
async function fill(name: string, value: string) {
  await act(async () => {
    const input = host.querySelector<HTMLInputElement>(`[aria-label="${name}"]`)!;
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
}
async function choose(label: string, value: string) {
  await act(async () => { const select = host.querySelector<HTMLSelectElement>(`[aria-label="${label}"]`)!; select.value = value; select.dispatchEvent(new Event('change', { bubbles: true })); });
}
async function save() { await fill('模型名称', row.model); await fill('API 密钥', secret); await act(async () => { button('保存并设为默认').click(); button('保存并设为默认').click(); }); }
it('shows missing model fields in place without sending a save request', async () => {
  await mount(); await act(async () => button('保存并设为默认').click());
  expect(host.querySelector('[aria-label="模型名称"]')?.getAttribute('aria-invalid')).toBe('true');
  expect(host.querySelector('#model-name-error')?.textContent).toContain('填写');
  expect(host.querySelector('#model-key-error')?.textContent).toContain('API 密钥');
  expect(ownerModelApi.configure).not.toHaveBeenCalled(); expect(personalRemoteApi.saveCredential).not.toHaveBeenCalled();
  await choose('模型提供方', 'openai-compatible'); await fill('模型名称', row.model); await fill('API 端点', 'not-a-url');
  await act(async () => button('保存并设为默认').click());
  expect(host.querySelector('#model-endpoint-error')?.textContent).toContain('HTTP');
  expect(ownerModelApi.configure).not.toHaveBeenCalled();
});
it('keeps the current form when another model becomes the default, including original-request recovery', async () => {
  vi.mocked(ownerModelApi.list).mockResolvedValue([row]);
  vi.mocked(ownerModelApi.default).mockRejectedValueOnce(new ModelRequestError(0));
  vi.mocked(ownerModelApi.recover).mockImplementation(async (_owner, requestId) => ({ ownerId: 'alice', requestId,
    action: 'model.default', result: { ...row, isDefault: true }, completedAt: '2026-10-09T00:00:01Z' }));
  await mount(); await fill('模型名称', 'my-unsubmitted-model'); await fill('API 密钥', secret); await fill('单次输出上限（token）', '16384');
  await act(async () => button('设为默认').click());
  expect(button('核对并继续原保存')).toBeDefined();
  await act(async () => button('核对并继续原保存').click());
  expect(host.querySelector<HTMLInputElement>('[aria-label="模型名称"]')?.value).toBe('my-unsubmitted-model');
  expect(host.querySelector<HTMLInputElement>('[aria-label="API 密钥"]')?.value).toBe(secret);
  expect(host.querySelector<HTMLInputElement>('[aria-label="单次输出上限（token）"]')?.value).toBe('16384');
  expect(ownerModelApi.default).toHaveBeenCalledTimes(1); expect(ownerModelApi.configure).not.toHaveBeenCalled();
});
it('restores only non-secret model inputs after leaving and returning', async () => {
  await mount(); await choose('模型提供方', 'openai-compatible'); await fill('模型名称', 'draft-model');
  await fill('API 端点', 'http://localhost:11434/v1'); await fill('单次输出上限（token）', '16384'); await fill('API 密钥', secret);
  expect(JSON.stringify(sessionStorage)).not.toContain(secret);
  await act(async () => root.unmount()); root = createRoot(host); await mount();
  expect(host.querySelector<HTMLInputElement>('[aria-label="模型名称"]')?.value).toBe('draft-model');
  expect(host.querySelector<HTMLInputElement>('[aria-label="API 端点"]')?.value).toBe('http://localhost:11434/v1');
  expect(host.querySelector<HTMLInputElement>('[aria-label="单次输出上限（token）"]')?.value).toBe('16384');
  expect(host.querySelector<HTMLInputElement>('[aria-label="API 密钥"]')?.value).toBe('');
  expect(ownerModelApi.configure).not.toHaveBeenCalled(); expect(ownerModelApi.default).not.toHaveBeenCalled();
});
it('offers the research continuation only after confirmed saving and permits ordinary return while unknown', async () => {
  const back = vi.fn();
  await act(async () => root.render(createElement(ModelSettings, { ownerId: 'alice', onBack: back, returnLabel: '返回原研究' })));
  vi.mocked(ownerModelApi.default).mockRejectedValueOnce(new ModelRequestError(0));
  await save();
  expect(button('继续原研究')).toBeUndefined();
  await act(async () => button('返回原研究').click()); expect(back).toHaveBeenCalledOnce();
  vi.mocked(ownerModelApi.recover).mockImplementation(async (_owner, requestId) => ({ ownerId: 'alice', requestId,
    action: 'model.default', result: { ...row, isDefault: true }, completedAt: '2026-10-09T00:00:01Z' }));
  await act(async () => button('核对并继续原保存').click());
  expect(button('继续原研究')).toBeDefined(); expect(ownerModelApi.default).toHaveBeenCalledTimes(1);
});
it('saves the official Go endpoint with an origin-bound credential and no model invocation', async () => {
  const baseURL = 'https://opencode.ai/zen/go/v1';
  vi.mocked(personalRemoteApi.saveCredential).mockResolvedValue({ ...credential, destination: 'https://opencode.ai' });
  vi.mocked(ownerModelApi.configure).mockResolvedValue({ ...row, provider: 'openai-compatible', baseURL });
  vi.mocked(ownerModelApi.default).mockResolvedValue({ ...row, provider: 'openai-compatible', baseURL, isDefault: true });
  await mount();
  await act(async () => { const select = host.querySelector<HTMLSelectElement>('[aria-label="模型提供方"]')!; select.value = 'openai-compatible'; select.dispatchEvent(new Event('change', { bubbles: true })); });
  await fill('API 端点', baseURL); await save();
  expect(personalRemoteApi.saveCredential).toHaveBeenCalledWith(expect.objectContaining({ destination: 'https://opencode.ai', password: secret }), 'alice');
  expect(ownerModelApi.configure).toHaveBeenCalledWith('alice', expect.objectContaining({ baseURL }), undefined);
  expect(host.textContent).toContain('模型已保存并设为默认');
  expect(JSON.stringify(localStorage)).not.toContain(secret);
});
it.each(MODEL_PROVIDER_PRESETS)('applies and saves preset $id with its explicit protocol and Go base', async preset => {
  vi.mocked(personalRemoteApi.saveCredential).mockResolvedValue({ ...credential, destination: 'https://opencode.ai' });
  const configured = { ...row, provider: 'openai-compatible' as const, baseURL: preset.baseURL, model: preset.model,
    ...(preset.protocol === 'responses' ? { protocol: preset.protocol } : {}) };
  vi.mocked(ownerModelApi.configure).mockResolvedValue(configured);
  vi.mocked(ownerModelApi.default).mockResolvedValue({ ...configured, isDefault: true });
  await mount(); await choose('模型快捷配置', preset.id);
  expect((host.querySelector('[aria-label="模型 API 协议"]') as HTMLSelectElement).value).toBe(preset.protocol);
  expect((host.querySelector('[aria-label="API 端点"]') as HTMLInputElement).value).toBe('https://opencode.ai/inference/go/v1');
  await fill('API 密钥', secret); await act(async () => button('保存并设为默认').click());
  expect(personalRemoteApi.saveCredential).toHaveBeenCalledWith(expect.objectContaining({ destination: 'https://opencode.ai', password: secret }), 'alice');
  expect(ownerModelApi.configure).toHaveBeenCalledWith('alice', expect.objectContaining({ baseURL: preset.baseURL, model: preset.model, protocol: preset.protocol }), undefined);
  expect(localStorage.getItem(storage)).toBeNull();
  expect(host.textContent).toContain('模型已保存并设为默认');
});
it('uses the manual protocol selection and never infers protocol from an arbitrary model name', async () => {
  const configured = { ...row, model: 'gpt-6-luna-custom', protocol: 'responses' as const };
  vi.mocked(ownerModelApi.configure).mockResolvedValue(configured);
  vi.mocked(ownerModelApi.default).mockResolvedValue({ ...configured, isDefault: true });
  await mount(); await fill('模型名称', configured.model);
  expect((host.querySelector('[aria-label="模型 API 协议"]') as HTMLSelectElement).value).toBe('chat-completions');
  await choose('模型 API 协议', 'responses'); await fill('API 密钥', secret);
  await act(async () => button('保存并设为默认').click());
  expect(ownerModelApi.configure).toHaveBeenCalledWith('alice', expect.objectContaining({ model: configured.model, protocol: 'responses' }), undefined);
});
it('retains an unknown Go credential save without replaying its secret after refresh', async () => {
  vi.mocked(personalRemoteApi.saveCredential).mockRejectedValue(new Error('unconfirmed'));
  await mount();
  await act(async () => { const select = host.querySelector<HTMLSelectElement>('[aria-label="模型提供方"]')!; select.value = 'openai-compatible'; select.dispatchEvent(new Event('change', { bubbles: true })); });
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
  expect(host.textContent).toContain('已有远端服务继续使用其自身配置。');
});
it('recovers an uncertain vault save after remount without replaying the key or changing configuration', async () => {
  vi.mocked(personalRemoteApi.saveCredential).mockRejectedValue(new Error(secret + ' unsafe transport echo'));
  await mount(); await save(); const request = vi.mocked(personalRemoteApi.saveCredential).mock.calls[0][0].requestId;
  expect(localStorage.getItem(storage)).not.toContain(secret); expect(host.textContent).not.toContain(secret);
  await act(async () => root.unmount()); root = createRoot(host); await mount();
  await act(async () => button('核对并继续原保存').click());
  expect(personalRemoteApi.recoverCredential).toHaveBeenCalledWith(request, 'alice'); expect(personalRemoteApi.saveCredential).toHaveBeenCalledTimes(1);
  expect(ownerModelApi.configure).toHaveBeenCalledTimes(1); expect(host.textContent).toContain('原保存已核对完成');
});
it('recovers the original non-secret metadata request when configuration acknowledgement is lost', async () => {
  vi.mocked(ownerModelApi.configure).mockRejectedValueOnce(new ModelRequestError(0));
  await mount(); await save(); const original = vi.mocked(ownerModelApi.configure).mock.calls[0][1];
  expect(localStorage.getItem(storage)).not.toContain(secret);
  await act(async () => button('核对并继续原保存').click());
  expect(personalRemoteApi.saveCredential).toHaveBeenCalledTimes(1); expect(ownerModelApi.recover).toHaveBeenCalledTimes(1);
  expect(ownerModelApi.recover).toHaveBeenCalledWith('alice', original.requestId);
  expect(ownerModelApi.configure).toHaveBeenCalledTimes(1); expect(ownerModelApi.configure).toHaveBeenCalledWith('alice', original, undefined);
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
it('projects harmless/secret unknown model fields while rejecting malformed required fields', () => {
  for (const value of [{ ...row, ownerId: 'bob' }, { ...row, available: false }, { ...row, status: 'odd' }, { ...row, protocol: 'unknown' }, { ...row, baseURL: 'javascript:alert(1)' }]) expect(() => ownerModel(value, 'alice')).toThrow();
  expect(ownerModel({ ...row, password: secret, harmless: 'ignored' }, 'alice')).toEqual(row);
  expect(ownerModel({ ...row, password: secret }, 'alice')).not.toHaveProperty('password');
});
it('fetches model receipts by GET with owner scope, projects unknown fields, and rejects mismatched receipts', async () => {
  const requestId = 'fixture-model-request-001';
  const receipt = { ownerId: 'alice', requestId, action: 'model.configure', result: { ...row, password: secret, harmless: 'ignored' }, completedAt: '2026-10-09T00:00:01Z', extra: 'ignored' };
  const mockedFetch = vi.fn(async () => new Response(JSON.stringify(receipt), { status: 200, headers: { 'Content-Type': 'application/json' } }));
  vi.mocked(ownerModelApi.recover).mockRestore();
  vi.stubGlobal('fetch', mockedFetch);
  const result = await ownerModelApi.recover('alice', requestId);
  expect(mockedFetch).toHaveBeenCalledTimes(1);
  const [url, init] = mockedFetch.mock.calls[0] as unknown as [string, RequestInit];
  expect(url).toBe(`/api/factory/personal-models/requests/${requestId}`);
  expect(init.method).toBe('GET'); expect(init.headers).toMatchObject({ 'X-Factory-Expected-Owner': 'alice' });
  expect(result).toEqual({ ownerId: 'alice', requestId, action: 'model.configure', result: row, completedAt: receipt.completedAt });
  expect(JSON.stringify(result)).not.toContain(secret);
  for (const invalid of [
    { ...receipt, ownerId: 'bob' }, { ...receipt, requestId: 'different-request' }, { ...receipt, action: 'credential.save' },
    { ...receipt, completedAt: 'not-a-date' }, { ...receipt, result: { ...row, ownerId: 'bob' } },
    { ...receipt, result: { ...row, status: 'unknown' } },
  ]) {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(invalid), { status: 200 })));
    await expect(ownerModelApi.recover('alice', requestId)).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
  }
});
it('accepts the actual persisted thinking field and rejects invalid values, scope and unknown fields', () => {
  expect(ownerModel(thinkingRow, 'alice')).toEqual(thinkingRow);
  for (const thinkingMode of ['enabled', 'default', null, false, {}, 0]) expect(() => ownerModel({ ...thinkingRow, thinkingMode }, 'alice')).toThrow();
  expect(() => ownerModel({ ...thinkingRow, protocol: 'responses' }, 'alice')).toThrow();
  expect(ownerModel({ ...thinkingRow, password: secret, otherOption: 'disabled' }, 'alice')).toEqual(thinkingRow);
  for (const value of [{ ...thinkingRow, model: 'other-model' }, { ...thinkingRow, baseURL: row.baseURL }]) expect(() => ownerModel(value, 'alice')).toThrow();
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
  await act(async () => button('撤销模型').click()); await act(async () => { button('确认撤销').click(); await new Promise(resolve => setTimeout(resolve, 200)); });
  expect(host.textContent).toContain('模型已撤销，不能用于新任务');
  expect(ownerModelApi.configure).not.toHaveBeenCalled(); expect(personalRemoteApi.saveCredential).not.toHaveBeenCalled();
});
it('retains scoped thinking metadata through password rotation, lost configure acknowledgement and refresh', async () => {
  const original = { ...thinkingRow, isDefault: true };
  const updated = { ...original, credentialRevision: 'rotated-r2', revision: 'model-r2' };
  vi.mocked(ownerModelApi.list).mockResolvedValue([original]);
  vi.mocked(personalRemoteApi.credentials).mockResolvedValue([goCredential]);
  const rotate = vi.spyOn(personalRemoteApi, 'rotateCredential').mockResolvedValue({ ...goCredential, credentialRevision: 'rotated-r2' });
  vi.mocked(ownerModelApi.configure).mockRejectedValueOnce(new ModelRequestError(0)).mockResolvedValue(updated);
  vi.mocked(ownerModelApi.default).mockResolvedValue(updated);
  await mount(); await act(async () => button('更新密钥').click()); await fill('API 密钥', secret);
  await act(async () => button('保存新密钥').click());
  const request = vi.mocked(ownerModelApi.configure).mock.calls[0][1]; expect(request.thinkingMode).toBe('disabled');
  vi.mocked(ownerModelApi.recover).mockResolvedValue({ ownerId: 'alice', requestId: request.requestId, action: 'model.configure', result: updated, completedAt: '2026-10-09T00:00:01Z' });
  expect(localStorage.getItem(storage)).toContain('"thinkingMode":"disabled"'); expect(localStorage.getItem(storage)).not.toContain(secret);
  await act(async () => root.unmount()); root = createRoot(host); await mount();
  await act(async () => button('核对并继续原保存').click());
  expect(ownerModelApi.configure).toHaveBeenCalledTimes(1); expect(ownerModelApi.recover).toHaveBeenCalledWith('alice', request.requestId);
  expect(rotate).toHaveBeenCalledTimes(1); expect(host.textContent).toContain('原保存已核对完成');
});
const legacyGoRow: OwnerModel = { ...row, provider: 'openai-compatible', baseURL: 'https://opencode.ai/zen/go/v1', isDefault: false, status: 'credential_unavailable', available: false };
it.each(['rotate', 'rebind'] as const)('keeps protocol absent for legacy Go records during %s', async operation => {
  vi.mocked(ownerModelApi.list).mockResolvedValue([legacyGoRow]);
  vi.mocked(personalRemoteApi.credentials).mockResolvedValue(operation === 'rotate' ? [] : [{ ...goCredential, credentialRevision: 'rotated-r2' }]);
  const updated = { ...legacyGoRow, credentialRevision: 'rotated-r2', status: 'configured' as const, available: true };
  vi.mocked(ownerModelApi.configure).mockResolvedValue(updated);
  await mount();
  if (operation === 'rotate') {
    vi.spyOn(personalRemoteApi, 'rotateCredential').mockResolvedValue({ ...goCredential, credentialRevision: 'rotated-r2' });
    await act(async () => button('更新密钥').click()); await fill('API 密钥', secret); await act(async () => button('保存新密钥').click());
  } else await act(async () => button('绑定更新后的凭据').click());
  expect(ownerModelApi.configure).toHaveBeenCalledTimes(1);
  expect(vi.mocked(ownerModelApi.configure).mock.calls[0][1]).not.toHaveProperty('protocol');
  expect(localStorage.getItem(storage)).toBeNull();
});
it('retains Responses protocol through rotation and receipt recovery', async () => {
  const original = { ...legacyGoRow, protocol: 'responses' as const, isDefault: true, maxOutputTokens: 16384 };
  const updated = { ...original, credentialRevision: 'rotated-r2', revision: 'model-r2', status: 'configured' as const, available: true };
  vi.mocked(ownerModelApi.list).mockResolvedValue([original]);
  vi.mocked(personalRemoteApi.credentials).mockResolvedValue([goCredential]);
  vi.spyOn(personalRemoteApi, 'rotateCredential').mockResolvedValue({ ...goCredential, credentialRevision: 'rotated-r2' });
  vi.mocked(ownerModelApi.configure).mockRejectedValueOnce(new ModelRequestError(0));
  vi.mocked(ownerModelApi.default).mockResolvedValue({ ...updated, isDefault: true });
  await mount(); await act(async () => button('更新密钥').click()); await fill('API 密钥', secret); await act(async () => button('保存新密钥').click());
  const request = vi.mocked(ownerModelApi.configure).mock.calls[0][1];
  expect(request.protocol).toBe('responses'); expect(localStorage.getItem(storage)).toContain('"protocol":"responses"');
  expect(request.maxOutputTokens).toBe(16384); expect(localStorage.getItem(storage)).toContain('"maxOutputTokens":16384');
  vi.mocked(ownerModelApi.recover).mockResolvedValue({ ownerId: 'alice', requestId: request.requestId, action: 'model.configure', result: updated, completedAt: '2026-10-09T00:00:01Z' });
  await act(async () => root.unmount()); root = createRoot(host); await mount(); await act(async () => button('核对并继续原保存').click());
  expect(ownerModelApi.configure).toHaveBeenCalledTimes(1); expect(ownerModelApi.recover).toHaveBeenCalledWith('alice', request.requestId);
  expect(host.textContent).toContain('原保存已核对完成'); expect(localStorage.getItem(storage)).toBeNull();
});
it('retains Responses protocol during credential rebind', async () => {
  const stale = { ...legacyGoRow, protocol: 'responses' as const, isDefault: false, maxOutputTokens: 16384 };
  vi.mocked(ownerModelApi.list).mockResolvedValue([stale]);
  vi.mocked(personalRemoteApi.credentials).mockResolvedValue([{ ...goCredential, credentialRevision: 'rotated-r2' }]);
  vi.mocked(ownerModelApi.configure).mockResolvedValue({ ...stale, credentialRevision: 'rotated-r2', status: 'configured', available: true });
  await mount(); await act(async () => button('绑定更新后的凭据').click());
  expect(ownerModelApi.configure).toHaveBeenCalledWith('alice', expect.objectContaining({ protocol: 'responses', maxOutputTokens: 16384 }), stale.reference);
  expect(localStorage.getItem(storage)).toBeNull();
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
it('preserves explicit Responses metadata and retains missing protocol on legacy setup records', () => {
  const legacy: ModelSetup = { owner: 'alice', provider: 'openai-compatible', baseURL: legacyGoRow.baseURL, model: legacyGoRow.model,
    credentialRequest: 'request-key-fixture', modelRequest: 'request-model-fixture', defaultRequest: 'request-default-fixture', stage: 'model', chooseDefault: false };
  const responses = { ...legacy, protocol: 'responses' as const };
  expect(readModelSetup(JSON.stringify(setupMetadata(legacy)), 'alice')).toEqual(legacy);
  expect(readModelSetup(JSON.stringify(setupMetadata(responses)), 'alice')).toEqual(responses);
  expect(readModelSetup(JSON.stringify({ ...responses, protocol: 'other' }), 'alice')).toBeNull();
});
it('persists only owner-scoped safe setup metadata and rejects unsupported destinations before custody', () => {
  const setup: ModelSetup = { owner: 'alice', provider: 'openai', baseURL: row.baseURL, model: row.model, credentialRequest: 'request-key-fixture', modelRequest: 'request-model-fixture', defaultRequest: 'request-default-fixture', stage: 'credential', chooseDefault: true };
  const metadata = setupMetadata({ ...setup, password: secret } as ModelSetup); expect(JSON.stringify(metadata)).not.toContain(secret);
  expect(readModelSetup(JSON.stringify(metadata), 'bob')).toBeNull(); expect(readModelSetup(JSON.stringify(metadata), 'alice')).toEqual(setup);
  for (const value of ['ftp://models.example/v1', 'https://user:pass@models.example/v1', 'https://models.example/v1?api_key=secret', 'https://models.example/v1#secret', 'https://models.example/../other']) expect(() => modelEndpoint(value)).toThrow();
});

it('clears stale drafts when another tab changes the cookie owner before Save, without submitting any secret', async () => {
  await mount(); vi.mocked(api.session).mockResolvedValue({ id: 'bob', name: 'Bob', role: 'user' }); await save();
  expect(api.session).toHaveBeenCalledTimes(1);
  expect(personalRemoteApi.saveCredential).not.toHaveBeenCalled(); expect(ownerModelApi.configure).not.toHaveBeenCalled();
  expect(host.querySelector('[aria-label="API 密钥"]')).toBeNull(); expect(host.textContent).toContain('当前登录账户已改变');
  expect(localStorage.getItem(storage)).toBeNull();
});
it('preflights once and honors the server expected-owner response after secret custody', async () => {
  vi.mocked(api.session).mockResolvedValueOnce({ id: 'alice', name: 'Alice', role: 'user' });
  vi.mocked(ownerModelApi.configure).mockRejectedValue(new ModelRequestError(403, 'EXPECTED_OWNER_MISMATCH'));
  await mount(); await save(); expect(personalRemoteApi.saveCredential).toHaveBeenCalledTimes(1);
  expect(api.session).toHaveBeenCalledTimes(1);
  expect(ownerModelApi.configure).toHaveBeenCalledTimes(1); expect(ownerModelApi.configure).toHaveBeenCalledWith('alice', expect.anything(), undefined);
  expect(ownerModelApi.default).not.toHaveBeenCalled();
  expect(host.textContent).toContain('当前登录账户已改变'); expect(JSON.stringify(localStorage)).not.toContain(secret);
});
it('clears drafts on a server-side owner mismatch in the race after live preflight', async () => {
  vi.mocked(ownerModelApi.configure).mockRejectedValue(new ModelRequestError(403, 'EXPECTED_OWNER_MISMATCH'));
  await mount(); await save(); expect(ownerModelApi.configure).toHaveBeenCalledWith('alice', expect.anything(), undefined);
  expect(ownerModelApi.default).not.toHaveBeenCalled(); expect(host.textContent).toContain('当前登录账户已改变');
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
it('recovers saved-reference configuration acknowledgement without repeating its POST', async () => {
  vi.mocked(personalRemoteApi.credentials).mockResolvedValue([credential]); vi.mocked(ownerModelApi.configure).mockRejectedValueOnce(new ModelRequestError(0));
  await mount(); await fill('模型名称', row.model);
  await act(async () => { const source = host.querySelector<HTMLSelectElement>('[aria-label="模型凭据来源"]')!; source.value = 'saved'; source.dispatchEvent(new Event('change', { bubbles: true })); });
  await act(async () => { const saved = host.querySelector<HTMLSelectElement>('[aria-label="已保存的模型凭据"]')!; saved.value = credential.credentialRef; saved.dispatchEvent(new Event('change', { bubbles: true })); });
  await act(async () => button('保存模型并设为默认').click()); const original = vi.mocked(ownerModelApi.configure).mock.calls[0][1];
  await act(async () => button('核对并继续原保存').click());
  expect(ownerModelApi.configure).toHaveBeenCalledTimes(1); expect(ownerModelApi.configure).toHaveBeenCalledWith('alice', original, undefined);
  expect(ownerModelApi.recover).toHaveBeenCalledWith('alice', original.requestId);
  expect(personalRemoteApi.saveCredential).not.toHaveBeenCalled(); expect(personalRemoteApi.recoverCredential).not.toHaveBeenCalled();
});

it('preserves optional output metadata and rejects invalid stored or received limits without backfilling legacy records', () => {
  const setup: ModelSetup = { owner: 'alice', provider: row.provider, baseURL: row.baseURL, model: row.model,
    credentialRequest: 'request-key-fixture', modelRequest: 'request-model-fixture', defaultRequest: 'request-default-fixture', stage: 'model', chooseDefault: false };
  expect(ownerModel(row, 'alice')).not.toHaveProperty('maxOutputTokens');
  expect(setupMetadata(setup)).not.toHaveProperty('maxOutputTokens');
  expect(ownerModel({ ...row, maxOutputTokens: 16384 }, 'alice').maxOutputTokens).toBe(16384);
  expect(readModelSetup(JSON.stringify({ ...setup, maxOutputTokens: 16384 }), 'alice')?.maxOutputTokens).toBe(16384);
  for (const maxOutputTokens of [null, false, '16384', 0, -1, 1.5, Number.MAX_SAFE_INTEGER + 1]) {
    expect(() => ownerModel({ ...row, maxOutputTokens }, 'alice')).toThrow();
    expect(readModelSetup(JSON.stringify({ ...setup, maxOutputTokens }), 'alice')).toBeNull();
  }
});

it('creates a model with its chosen output limit and confirms the same default', async () => {
  const configured = { ...row, maxOutputTokens: 16384 };
  vi.mocked(ownerModelApi.configure).mockResolvedValue(configured);
  vi.mocked(ownerModelApi.default).mockResolvedValue({ ...configured, isDefault: true });
  await mount(); await fill('单次输出上限（token）', '16384'); await save();
  expect(ownerModelApi.configure).toHaveBeenCalledTimes(1);
  expect(vi.mocked(ownerModelApi.configure).mock.calls[0][1].maxOutputTokens).toBe(16384);
  expect(localStorage.getItem(storage)).toBeNull();
  expect(host.textContent).toContain('模型已保存并设为默认');
});

it('updates only output configuration once and recovers its lost acknowledgement after remount without credential writes', async () => {
  const original = { ...row, protocol: 'responses' as const, isDefault: true };
  const updated = { ...original, revision: 'updated-output-revision', connectionRef: 'updated-output-binding', maxOutputTokens: 16384 };
  vi.mocked(ownerModelApi.list).mockResolvedValue([original]);
  vi.mocked(ownerModelApi.configure).mockRejectedValueOnce(new ModelRequestError(0));
  vi.mocked(ownerModelApi.default).mockResolvedValue(updated);
  const rotate = vi.spyOn(personalRemoteApi, 'rotateCredential');
  await mount(); await act(async () => button('调整输出额度').click());
  expect(host.querySelector('[aria-label="API 密钥"]')).toBeNull();
  expect(host.textContent).toContain('已有会话不会自动切换');
  await fill('单次输出上限（token）', '16384');
  await act(async () => { button('保存输出额度').click(); button('保存输出额度').click(); });
  expect(ownerModelApi.configure).toHaveBeenCalledTimes(1);
  const request = vi.mocked(ownerModelApi.configure).mock.calls[0][1];
  expect(request).toMatchObject({ maxOutputTokens: 16384, protocol: 'responses', credentialRef: row.credentialRef, credentialRevision: row.credentialRevision });
  expect(vi.mocked(ownerModelApi.configure).mock.calls[0][2]).toBe(row.reference);
  expect(localStorage.getItem(storage)).toContain('"maxOutputTokens":16384');
  vi.mocked(ownerModelApi.recover).mockResolvedValue({ ownerId: 'alice', requestId: request.requestId, action: 'model.configure', result: updated, completedAt: '2026-10-09T00:00:01Z' });
  await act(async () => root.unmount()); root = createRoot(host); await mount();
  await act(async () => button('核对并继续原保存').click());
  expect(ownerModelApi.configure).toHaveBeenCalledTimes(1);
  expect(ownerModelApi.recover).toHaveBeenCalledWith('alice', request.requestId);
  expect(ownerModelApi.default).toHaveBeenCalledTimes(1);
  expect(localStorage.getItem(storage)).toBeNull();
  expect(host.textContent).toContain('原保存已核对完成');
  expect(personalRemoteApi.saveCredential).not.toHaveBeenCalled();
  expect(personalRemoteApi.recoverCredential).not.toHaveBeenCalled();
  expect(rotate).not.toHaveBeenCalled();
});

it('shows an invalid output limit at the field and keeps a mismatched saved limit unresolved', async () => {
  vi.mocked(ownerModelApi.list).mockResolvedValue([row]);
  await mount(); await act(async () => button('调整输出额度').click());
  await fill('单次输出上限（token）', '1.5');
  expect(host.querySelector('[aria-label="单次输出上限（token）"]')?.getAttribute('aria-invalid')).toBe('true');
  expect(host.querySelector('#model-output-error')?.textContent).toContain('请输入正整数');
  expect(button('保存输出额度').disabled).toBe(true);
  expect(ownerModelApi.configure).not.toHaveBeenCalled();
  await fill('单次输出上限（token）', '16384'); await act(async () => button('保存输出额度').click());
  expect(ownerModelApi.configure).toHaveBeenCalledTimes(1);
  expect(ownerModelApi.default).not.toHaveBeenCalled();
  expect(localStorage.getItem(storage)).toContain('"maxOutputTokens":16384');
  expect(host.textContent).toContain('设置尚未确认');
  expect(personalRemoteApi.saveCredential).not.toHaveBeenCalled();
});

it('can restore the default output limit on a model with no credentials without writing a key or choosing another default', async () => {
  const original = { ...row, credentialRef: null, credentialRevision: null, maxOutputTokens: 16384 };
  vi.mocked(ownerModelApi.list).mockResolvedValue([original]);
  vi.mocked(ownerModelApi.configure).mockResolvedValue({ ...row, credentialRef: null, credentialRevision: null });
  await mount(); await act(async () => button('调整输出额度').click());
  await fill('单次输出上限（token）', ''); await act(async () => button('保存输出额度').click());
  expect(ownerModelApi.configure).toHaveBeenCalledTimes(1);
  const request = vi.mocked(ownerModelApi.configure).mock.calls[0][1];
  expect(request).not.toHaveProperty('maxOutputTokens');
  expect(request).not.toHaveProperty('credentialRef');
  expect(ownerModelApi.default).not.toHaveBeenCalled();
  expect(personalRemoteApi.saveCredential).not.toHaveBeenCalled();
  expect(localStorage.getItem(storage)).toBeNull();
});
