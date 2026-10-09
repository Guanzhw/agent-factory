// @vitest-environment happy-dom
import { webcrypto } from 'node:crypto';
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { CredentialForm } from '../web/CredentialForm.js';
import { PersonalRemotes } from '../web/PersonalRemotes.js';
import { personalAgentApi } from '../web/personalAgentApi.js';
import { api } from '../web/api.js';
import { personalRemoteApi, remoteCanBind, definitivelyRejected, RemoteRequestError, type PersonalRemote } from '../web/personalRemoteApi.js';
const owner = { id: 'fixture-owner', name: 'Fixture', role: 'user' as const };
const credential = { providerId: 'opencode-serve-v1', destination: 'https://fixture.example.org', credentialRef: 'credential-fixture', credentialRevision: 'r1', status: 'active' };
let host: HTMLDivElement; let root: Root;
const saved = vi.fn(); const cancelled = vi.fn();
beforeEach(() => { vi.spyOn(personalAgentApi, 'sessions').mockResolvedValue([]); vi.spyOn(personalAgentApi, 'capabilities').mockRejectedValue(new Error('personal sessions disabled in this fixture')); vi.spyOn(api, 'userConnections').mockResolvedValue([]); vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); vi.stubGlobal('crypto', webcrypto); window.localStorage.clear(); host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host); saved.mockReset(); cancelled.mockReset(); });
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function mountCredential() { await act(async () => root.render(createElement(CredentialForm, { owner: owner.id, providerId: credential.providerId, destination: credential.destination, onSaved: saved, onCancel: cancelled }))); }
function button(label: string) { return [...host.querySelectorAll('button')].find(b => b.textContent === label)!; }
async function fill() {
  await act(async () => {
    for (const [label, value] of [['服务用户名', 'synthetic-user'], ['服务密码', 'synthetic-secret-only']]) {
      const el = host.querySelector<HTMLInputElement>(`[aria-label="${label}"]`)!;
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(el, value); el.dispatchEvent(new Event('input', { bubbles: true }));
    }
    host.querySelector<HTMLInputElement>('input[type=checkbox]')!.click();
  });
}
it('requires explicit custody consent, password field, one submission and clears successful secret', async () => {
  let finish!: (value: typeof credential) => void;
  const save = vi.spyOn(personalRemoteApi, 'saveCredential').mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  await mountCredential(); expect(button('确认安全保存凭据').disabled).toBe(true); expect(host.querySelector('[aria-label="服务密码"]')?.getAttribute('type')).toBe('password');
  await fill(); await act(async () => { button('确认安全保存凭据').click(); button('确认安全保存凭据').click(); });
  expect(save).toHaveBeenCalledWith(expect.objectContaining({ password: 'synthetic-secret-only' }), owner.id); expect(save).toHaveBeenCalledTimes(1); expect(JSON.stringify(window.localStorage)).not.toContain('synthetic-secret-only');
  await act(async () => finish(credential)); expect(saved).toHaveBeenCalledWith(credential); expect(host.querySelector<HTMLInputElement>('[aria-label="服务密码"]')!.value).toBe('');
});
it('redacts failure bodies, freezes unknown saves, recovers by original request without secret replay', async () => {
  const save = vi.spyOn(personalRemoteApi, 'saveCredential').mockRejectedValue(new Error('synthetic-secret-only upstream echo'));
  const recover = vi.spyOn(personalRemoteApi, 'recoverCredential').mockResolvedValue(credential);
  await mountCredential(); await fill(); await act(async () => button('确认安全保存凭据').click());
  expect(host.textContent).not.toContain('synthetic-secret-only'); expect(button('确认安全保存凭据').disabled).toBe(true);
  expect(host.querySelector<HTMLInputElement>('[aria-label="服务密码"]')!.value).toBe('');
  const id = save.mock.calls[0][0].requestId;
  await act(async () => button('核对原凭据请求').click()); expect(recover).toHaveBeenCalledWith(id, owner.id); expect(save).toHaveBeenCalledTimes(1); expect(saved).toHaveBeenCalledWith(credential);
});
it('cancel clears input and never saves credentials', async () => { const save = vi.spyOn(personalRemoteApi, 'saveCredential'); await mountCredential(); await fill(); await act(async () => button('取消并清空').click()); expect(cancelled).toHaveBeenCalled(); expect(save).not.toHaveBeenCalled(); expect(host.querySelector<HTMLInputElement>('[aria-label="服务密码"]')!.value).toBe(''); });
it('uses deployment availability and does not imply remote execution readiness', async () => {
  vi.spyOn(api, 'session').mockResolvedValue(owner); vi.spyOn(personalRemoteApi, 'providers').mockResolvedValue([]); vi.spyOn(personalRemoteApi, 'list').mockResolvedValue([]); vi.spyOn(personalRemoteApi, 'credentialAvailability').mockResolvedValue({ enabled: false, providerIds: [] });
  await act(async () => root.render(createElement(PersonalRemotes, { user: owner, jobs: [], onChanged: vi.fn() })));
  expect(host.textContent).toContain('此部署尚未启用'); expect(host.textContent).toContain('受管完整研究执行仍需单独验证'); expect(host.querySelector('input[type=password]')).toBeNull();
});
it('expired or revoked metadata cannot bind even with stale available/action flags', () => {
  const remote = { available: true, status: 'verified', allowedActions: ['bind'], expiresAt: new Date(Date.now() + 60_000).toISOString() } as PersonalRemote;
  expect(remoteCanBind(remote)).toBe(true); expect(remoteCanBind({ ...remote, status: 'revoked' })).toBe(false); expect(remoteCanBind({ ...remote, expiresAt: new Date(0).toISOString() })).toBe(false); expect(remoteCanBind({ ...remote, expiresAt: null })).toBe(false);
});
it('keeps verify and bind separate and reconciles an unknown verify without replay', async () => {
  const remote = { registrationRef: 'remote-fixture', providerId: credential.providerId, configRevision: 'r1', revision: 'r1', status: 'configured', available: false, origin: credential.destination, projectId: 'fixture-project', capabilities: [], expiresAt: null, allowedActions: ['inspect', 'verify', 'configure', 'revoke'] } satisfies PersonalRemote;
  vi.spyOn(api, 'session').mockResolvedValue(owner); const bind = vi.spyOn(api, 'bindConnection');
  vi.spyOn(personalRemoteApi, 'providers').mockResolvedValue([{ providerId: credential.providerId, kind: 'environment', capabilities: ['runtime:health'] }]); vi.spyOn(personalRemoteApi, 'list').mockResolvedValue([remote]); vi.spyOn(personalRemoteApi, 'credentials').mockResolvedValue([]); vi.spyOn(personalRemoteApi, 'credentialAvailability').mockResolvedValue({ enabled: true, providerIds: [credential.providerId] });
  const command = vi.spyOn(personalRemoteApi, 'command').mockRejectedValue(new Error('untrusted provider detail'));
  const recovery = vi.spyOn(personalRemoteApi, 'recover').mockImplementation(async requestId => ({ requestId, action: 'remote.verify', remote }));
  await act(async () => root.render(createElement(PersonalRemotes, { user: owner, jobs: [], onChanged: vi.fn() })));
  expect(button('确认绑定只读连接').disabled).toBe(true);
  await act(async () => button('验证远程服务').click());
  await vi.waitFor(() => expect(command).toHaveBeenCalledTimes(1));
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); });
  expect(host.textContent).not.toContain('untrusted provider detail'); expect(bind).not.toHaveBeenCalled();
  await act(async () => button('核对原远程请求').click()); expect(recovery).toHaveBeenCalledWith(command.mock.calls[0][2]); expect(command).toHaveBeenCalledTimes(1); expect(bind).not.toHaveBeenCalled();
});

it('allows correction after definitive rejection and blocks submission without durable recovery storage', async () => {
  const save = vi.spyOn(personalRemoteApi, 'saveCredential').mockRejectedValue(new RemoteRequestError(true));
  await mountCredential(); await fill(); await act(async () => button('确认安全保存凭据').click());
  expect(host.textContent).toContain('请求未保存'); expect(host.textContent).not.toContain('保存结果未知');
  expect(window.localStorage.getItem(`factory-credential-pending:${owner.id}`)).toBeNull();
  const original = window.localStorage;
  const denied = new Proxy(original, { get(target, key) { return key === 'setItem' ? () => { throw new Error('storage denied'); } : Reflect.get(target, key); } });
  const getter = vi.spyOn(window, 'localStorage', 'get').mockReturnValue(denied);
  try { await fill(); await act(async () => button('确认安全保存凭据').click()); expect(save).toHaveBeenCalledTimes(1); } finally { getter.mockRestore(); }
});
it('recovers original receipt after form destination changes without resubmitting', async () => {
  window.localStorage.setItem(`factory-credential-pending:${owner.id}`, 'original-request');
  const recover = vi.spyOn(personalRemoteApi, 'recoverCredential').mockResolvedValue({ ...credential, destination: 'https://original.example.org' });
  const save = vi.spyOn(personalRemoteApi, 'saveCredential'); await mountCredential();
  await act(async () => button('核对原凭据请求').click()); expect(recover).toHaveBeenCalledWith('original-request', owner.id); expect(saved).toHaveBeenCalledWith(expect.objectContaining({ destination: 'https://original.example.org' })); expect(save).not.toHaveBeenCalled();
});
it('recovers unknown binding through original owner-scoped receipt without rebinding', async () => {
  window.localStorage.setItem(`factory-remote-pending:${owner.id}`, JSON.stringify({ requestId: 'original-bind', action: 'bind' }));
  vi.spyOn(api, 'session').mockResolvedValue(owner); const bind = vi.spyOn(api, 'bindConnection');
  vi.spyOn(personalRemoteApi, 'providers').mockResolvedValue([]); vi.spyOn(personalRemoteApi, 'list').mockResolvedValue([]); vi.spyOn(personalRemoteApi, 'credentialAvailability').mockResolvedValue({ enabled: false, providerIds: [] });
  const recovery = vi.spyOn(personalRemoteApi, 'recoverBinding').mockResolvedValue({ requestId: 'original-bind', action: 'bind', connection: { ownerId: owner.id } as Awaited<ReturnType<typeof api.bindConnection>> });
  await act(async () => root.render(createElement(PersonalRemotes, { user: owner, jobs: [], onChanged: vi.fn() })));
  await act(async () => button('核对原远程请求').click()); expect(recovery).toHaveBeenCalledWith('original-bind'); expect(bind).not.toHaveBeenCalled(); expect(window.localStorage.getItem(`factory-remote-pending:${owner.id}`)).toBeNull();
});

it('keeps timeout, conflict, throttling and server errors ambiguous', () => { for (const status of [0, 200, 408, 409, 429, 500, 503]) expect(definitivelyRejected(status)).toBe(false); for (const status of [400, 401, 403, 422]) expect(definitivelyRejected(status)).toBe(true); });
it('explicitly configures a creation-only ORX connection without requiring an existing project', async () => {
  const providerId = 'openresearch-personal-session-v1'; const origin = 'https://fixture.example.org';
  const savedCredential = { ...credential, providerId, destination: origin };
  vi.spyOn(api, 'session').mockResolvedValue(owner);
  vi.spyOn(personalRemoteApi, 'providers').mockResolvedValue([{ providerId, kind: 'orx', capabilities: ['session:read'], authModes: ['bearer'], projectCreationSupported: true }]);
  vi.spyOn(personalRemoteApi, 'list').mockResolvedValue([]); vi.spyOn(personalRemoteApi, 'credentials').mockResolvedValue([savedCredential]); vi.spyOn(personalRemoteApi, 'credentialAvailability').mockResolvedValue({ enabled: true, providerIds: [providerId] });
  const configure = vi.spyOn(personalRemoteApi, 'configure').mockResolvedValue({ registrationRef: 'created-service-config' } as PersonalRemote);
  const command = vi.spyOn(personalRemoteApi, 'command'); const bind = vi.spyOn(api, 'bindConnection');
  await act(async () => root.render(createElement(PersonalRemotes, { user: owner, jobs: [], onChanged: vi.fn() })));
  async function change(label: string, value: string) { await act(async () => { const field = host.querySelector<HTMLInputElement | HTMLSelectElement>(`[aria-label="${label}"]`)!; const select = field.tagName === 'SELECT'; Object.getOwnPropertyDescriptor(select ? HTMLSelectElement.prototype : HTMLInputElement.prototype, 'value')!.set!.call(field, value); field.dispatchEvent(new Event(select ? 'change' : 'input', { bubbles: true })); }); }
  await change('远程提供方', providerId); await change('HTTPS 服务源', origin); await change('OpenResearch 认证方式', 'bearer');
  await act(async () => host.querySelector<HTMLInputElement>('[aria-label="用于创建新项目"]')!.click());
  expect(host.querySelector('[aria-label="预期项目 ID"]')).toBeNull();
  await change('已有此目标的凭据', credential.credentialRef); await act(async () => button('确认保存配置').click());
  await vi.waitFor(() => expect(configure).toHaveBeenCalledTimes(1));
  expect(configure).toHaveBeenCalledWith(expect.objectContaining({ providerId, origin, authMode: 'bearer', projectCreation: true }), undefined);
  expect(configure.mock.calls[0][0]).not.toHaveProperty('projectId'); expect(command).not.toHaveBeenCalled(); expect(bind).not.toHaveBeenCalled();
});
it('collects an existing ORX service token without asking for a model key or username', async () => {
  const value = { ...credential, providerId: 'openresearch-personal-session-v1' };
  const save = vi.spyOn(personalRemoteApi, 'saveCredential').mockResolvedValue(value);
  await act(async () => root.render(createElement(CredentialForm, { owner: owner.id, providerId: value.providerId, destination: value.destination, credentialKind: 'service-token', onSaved: saved, onCancel: cancelled })));
  expect(host.querySelector('[aria-label="服务用户名"]')).toBeNull(); expect(host.textContent).toContain('不要填写模型 API 密钥');
  const input = host.querySelector<HTMLInputElement>('[aria-label="OpenResearch 服务令牌"]')!; expect(input.type).toBe('password');
  await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, 'synthetic-service-token'); input.dispatchEvent(new Event('input', { bubbles: true })); host.querySelector<HTMLInputElement>('input[type=checkbox]')!.click(); });
  await act(async () => button('确认安全保存凭据').click()); expect(save).toHaveBeenCalledWith(expect.objectContaining({ username: 'bearer', password: 'synthetic-service-token' }), owner.id); expect(JSON.stringify(localStorage)).not.toContain('synthetic-service-token'); expect(input.value).toBe('');
});
it('requires explicit ORX auth mode and carries an optional existing session template only in the configuration request', async () => {
  const providerId = 'openresearch-personal-session-v1'; const stored = { ...credential, providerId };
  vi.spyOn(api, 'session').mockResolvedValue(owner); vi.spyOn(personalRemoteApi, 'providers').mockResolvedValue([{ providerId, kind: 'orx', capabilities: ['session:read'], namespace: 'native-openresearch', authModes: ['bearer', 'basic-proxy'], sessionTemplateSupported: true }]); vi.spyOn(personalRemoteApi, 'list').mockResolvedValue([]); vi.spyOn(personalRemoteApi, 'credentialAvailability').mockResolvedValue({ enabled: true, providerIds: [providerId] }); vi.spyOn(personalRemoteApi, 'credentials').mockResolvedValue([stored]);
  const configure = vi.spyOn(personalRemoteApi, 'configure').mockResolvedValue({ registrationRef: 'orx-configured' } as PersonalRemote);
  await act(async () => root.render(createElement(PersonalRemotes, { user: owner, jobs: [], onChanged: vi.fn() })));
  async function field(label: string, value: string) { await act(async () => { const el = host.querySelector<HTMLInputElement | HTMLSelectElement>(`[aria-label="${label}"]`)!; Object.getOwnPropertyDescriptor(el.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype, 'value')!.set!.call(el, value); el.dispatchEvent(new Event(el.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true })); }); }
  await field('远程提供方', providerId); await field('HTTPS 服务源', stored.destination); await field('预期项目 ID', 'native-project');
  expect(button('输入并保存个人凭据').disabled).toBe(true); await field('OpenResearch 认证方式', 'bearer'); expect(button('输入并保存个人凭据').disabled).toBe(false);
  await field('新会话模板 ID（可选）', 'existing-session-template'); await field('已有此目标的凭据', stored.credentialRef); await act(async () => button('确认保存配置').click());
  await vi.waitFor(() => expect(configure).toHaveBeenCalledTimes(1)); expect(configure).toHaveBeenCalledWith(expect.objectContaining({ authMode: 'bearer', sessionTemplateId: 'existing-session-template', projectId: 'native-project', credentialRef: stored.credentialRef }), undefined); expect(JSON.stringify(localStorage)).not.toContain('existing-session-template');
});

it('binds remote service secret custody to the form owner and clears a rejected stale-tab draft', async () => {
  const save = vi.spyOn(personalRemoteApi, 'saveCredential').mockRejectedValue(new RemoteRequestError(true, 'EXPECTED_OWNER_MISMATCH'));
  await mountCredential(); await fill(); await act(async () => button('确认安全保存凭据').click());
  expect(save).toHaveBeenCalledWith(expect.objectContaining({ password: 'synthetic-secret-only' }), owner.id);
  expect(saved).not.toHaveBeenCalled(); expect(host.querySelector<HTMLInputElement>('[aria-label="服务密码"]')!.value).toBe('');
  expect(localStorage.getItem('factory-credential-pending:fixture-owner')).toBeNull();
});
