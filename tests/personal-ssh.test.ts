// @vitest-environment happy-dom
import { webcrypto } from 'node:crypto';
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { api } from '../web/api.js';
import { PersonalSSHServers } from '../web/PersonalSSHServers.js';
import { ConnectionsPanel } from '../web/ConnectionsPanel.js';
import { credentialDestination, credentialReceipt, SSH_CREDENTIAL_PROVIDER } from '../web/credentialManagement.js';
import { personalRemoteApi, RemoteRequestError } from '../web/personalRemoteApi.js';
import { personalSSHApi, type PersonalSSHServer, type SSHIdentityInput } from '../web/personalSSHApi.js';
import { personalAgentApi } from '../web/personalAgentApi.js';
import { applicationEnvironmentApi } from '../web/applicationEnvironmentApi.js';
import { ownerModelApi } from '../web/ownerModelApi.js';

const pin = 'a'.repeat(64); const destination = `ssh://fixture@127.0.0.1:2222?hostkey=${pin}`;
const publicKey = 'ssh-ed25519 ' + 'A'.repeat(68);
const input: SSHIdentityInput = { name: '合成本人服务器', address: '127.0.0.1', port: 2222, username: 'fixture', hostKey: publicKey, allowedRoot: '/tmp/af-owned-fixture' };
const identity = { address: input.address, port: input.port, username: input.username, hostKey: publicKey, hostFingerprint: 'SHA256:synthetic-host-fingerprint', origin: destination };
const credential = { credentialRef: 'credential-fixture', credentialRevision: 'r1', providerId: SSH_CREDENTIAL_PROVIDER, destination, status: 'active' };
const server: PersonalSSHServer = { ...input, reference: 'remote-' + 'a'.repeat(32), hostFingerprint: identity.hostFingerprint,
  defaultDirectory: input.allowedRoot + '/research', status: 'configured', enabled: false, diagnostic: null, lastCheckRequestId: null,
  credentialRef: credential.credentialRef, credentialRevision: credential.credentialRevision };
const secret = 'SYNTHETIC_PRIVATE_KEY_PLACEHOLDER_NOT_A_VALID_USER_KEY';
const storage = 'factory-personal-ssh:alice';
let host: HTMLDivElement; let root: Root; const onResearch = vi.fn();
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); vi.stubGlobal('crypto', webcrypto); localStorage.clear(); sessionStorage.clear(); onResearch.mockReset();
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  vi.spyOn(api, 'session').mockResolvedValue({ id: 'alice', name: 'Alice', role: 'user' });
  vi.spyOn(personalSSHApi, 'capabilities').mockResolvedValue({ enabled: true });
  vi.spyOn(personalSSHApi, 'list').mockResolvedValue([]);
  vi.spyOn(personalSSHApi, 'identity').mockResolvedValue(identity);
  vi.spyOn(personalSSHApi, 'configure').mockImplementation(async () => { vi.mocked(personalSSHApi.list).mockResolvedValue([server]); return server; });
  vi.spyOn(personalSSHApi, 'command').mockImplementation(async (_, __, action, requestId) => {
    const next = { ...server, status: action === 'revoke' ? 'revoked' : 'verified', enabled: action === 'bind', lastCheckRequestId: action === 'verify' ? requestId : null };
    vi.mocked(personalSSHApi.list).mockResolvedValue([next]); return next;
  });
  vi.spyOn(personalRemoteApi, 'credentials').mockResolvedValue([]);
  vi.spyOn(personalRemoteApi, 'saveCredential').mockResolvedValue(credential);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function mount(ownerId = 'alice') { await act(async () => root.render(createElement(PersonalSSHServers, { ownerId, onChanged: vi.fn(), onResearch }))); }
const button = (label: string) => [...host.querySelectorAll('button')].find(b => b.textContent === label)!;
async function field(label: string, value: string) {
  await act(async () => {
    const element = [...host.querySelectorAll('label')].find(l => l.textContent?.startsWith(label))!.querySelector<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>('input,textarea,select')!;
    const prototype = element.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : element.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, 'value')!.set!.call(element, value);
    element.dispatchEvent(new Event(element.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true }));
  });
}
async function preview() {
  await act(async () => button('添加我的服务器').click());
  for (const [label, value] of [['服务器名称', input.name], ['服务器 IP', input.address], ['SSH 端口', String(input.port)], ['SSH 账户', input.username], ['服务器 Ed25519 主机公钥', publicKey], ['私有工作目录', input.allowedRoot]]) await field(label, value);
  await act(async () => button('核对服务器身份').click());
}
async function consent() { await act(async () => host.querySelector<HTMLInputElement>('input[type=checkbox]')!.click()); }
async function save() { await field('专用 SSH 私钥', secret); await consent(); await act(async () => button('保存身份并登记服务器').click()); }
async function remount() { await act(async () => root.unmount()); root = createRoot(host); await mount(); }

it('requires explicit fixed-host authority, stores only encrypted-key metadata, then checks and enables before returning to research', async () => {
  await mount(); await preview(); await field('专用 SSH 私钥', secret);
  expect(button('保存身份并登记服务器').disabled).toBe(true); expect(personalRemoteApi.saveCredential).not.toHaveBeenCalled();
  expect(personalSSHApi.command).not.toHaveBeenCalled(); await consent();
  await act(async () => { button('保存身份并登记服务器').click(); button('保存身份并登记服务器').click(); });
  expect(personalRemoteApi.saveCredential).toHaveBeenCalledTimes(1); expect(personalRemoteApi.saveCredential).toHaveBeenCalledWith(expect.objectContaining({ providerId: SSH_CREDENTIAL_PROVIDER, destination, username: 'fixture', password: secret }), 'alice');
  expect(personalSSHApi.configure).toHaveBeenCalledTimes(1); expect(personalSSHApi.configure).toHaveBeenCalledWith('alice', expect.objectContaining({ confirmedHostKey: true, credentialRef: credential.credentialRef, credentialRevision: 'r1' }), undefined);
  expect(JSON.stringify(localStorage)).not.toContain(secret); expect(host.textContent).not.toContain(secret); expect(localStorage.getItem(storage)).toBeNull(); expect(personalSSHApi.command).not.toHaveBeenCalled();
  await act(async () => button('检查连接与依赖').click()); expect(personalSSHApi.command).toHaveBeenLastCalledWith('alice', server.reference, 'verify', expect.any(String));
  await act(async () => button('启用此服务器').click()); expect(personalSSHApi.command).toHaveBeenLastCalledWith('alice', server.reference, 'bind', expect.any(String));
  await act(async () => button('去 OpenResearch 准备').click()); expect(onResearch).toHaveBeenCalledTimes(1);
  expect(JSON.parse(sessionStorage.getItem('factory-research-server:alice')!)).toEqual({ owner: 'alice', reference: server.reference, directory: server.defaultDirectory });
  expect(host.textContent).not.toContain('credential-fixture'); expect(host.textContent).not.toContain(server.reference);
});

it('uses an already saved exact-host credential without sending another secret', async () => {
  vi.mocked(personalRemoteApi.credentials).mockResolvedValue([credential, { ...credential, credentialRef: 'credential-other', destination: destination.replace('2222', '2223') }]);
  await mount(); await preview(); await field('已保存的此服务器 SSH 身份', credential.credentialRef); await consent();
  await act(async () => button('保存身份并登记服务器').click()); expect(personalRemoteApi.saveCredential).not.toHaveBeenCalled(); expect(personalSSHApi.configure).toHaveBeenCalledTimes(1);
});

it('refreshes SSH identity revisions after rotation in the sibling credentials panel and requires new consent', async () => {
  let current = credential;
  vi.mocked(personalRemoteApi.credentials).mockImplementation(async () => [current]);
  vi.mocked(personalSSHApi.list).mockResolvedValue([server]);
  vi.spyOn(personalRemoteApi, 'credentialAvailability').mockResolvedValue({ enabled: true, providerIds: [SSH_CREDENTIAL_PROVIDER] });
  vi.spyOn(personalRemoteApi, 'providers').mockResolvedValue([]);
  vi.spyOn(personalRemoteApi, 'list').mockResolvedValue([]);
  vi.spyOn(personalRemoteApi, 'rotateCredential').mockImplementation(async () => { current = { ...credential, credentialRevision: 'r2' }; return current; });
  vi.spyOn(api, 'userConnections').mockResolvedValue([]);
  vi.spyOn(api, 'connectionRegistrations').mockResolvedValue([]);
  vi.spyOn(api, 'resourceLeases').mockResolvedValue({ leases: [], nextCursor: null });
  vi.spyOn(personalAgentApi, 'capabilities').mockResolvedValue({ executionContract: 'personal-remote-agent-v1', nativeQueue: false });
  vi.spyOn(personalAgentApi, 'sessions').mockResolvedValue([]);
  vi.spyOn(applicationEnvironmentApi, 'capabilities').mockResolvedValue({ locations: [], applications: [] });
  vi.spyOn(ownerModelApi, 'list').mockResolvedValue([]);
  await act(async () => root.render(createElement(ConnectionsPanel, {
    user: { id: 'alice', name: 'Alice', role: 'user' }, jobs: [], busy: '',
    act: async (_name: string, work: () => Promise<void>) => { await work(); }, onNotice: vi.fn(),
  })));
  await act(async () => button('更换连接设置').click());
  await act(async () => button('核对服务器身份').click());
  await field('已保存的此服务器 SSH 身份', credential.credentialRef); await consent();
  await act(async () => button('更换凭据').click());
  await field('新的专用 Ed25519 SSH 私钥', secret);
  await act(async () => host.querySelector<HTMLInputElement>('.personal-credentials input[type=checkbox]')!.click());
  await act(async () => button('保存更换后的凭据').click());
  expect(personalRemoteApi.rotateCredential).toHaveBeenCalledTimes(1);
  expect(host.textContent).toContain('SSH 身份版本已改变或撤销');
  expect(button('保存身份并登记服务器').disabled).toBe(true);
  await field('已保存的此服务器 SSH 身份', credential.credentialRef); await consent();
  await act(async () => button('保存身份并登记服务器').click());
  expect(personalSSHApi.configure).toHaveBeenLastCalledWith('alice', expect.objectContaining({
    credentialRef: credential.credentialRef, credentialRevision: 'r2', confirmedHostKey: true,
  }), server.reference);
  expect(personalRemoteApi.saveCredential).not.toHaveBeenCalled();
});

it('recovers a lost key receipt after remount with GET only, no secret resend and no automatic registration', async () => {
  vi.mocked(personalRemoteApi.saveCredential).mockRejectedValue(new Error(secret));
  vi.spyOn(personalRemoteApi, 'recoverCredential').mockResolvedValue(credential);
  await mount(); await preview(); await save(); const p = JSON.parse(localStorage.getItem(storage)!);
  expect(p.action).toBe('credential'); expect(JSON.stringify(localStorage)).not.toContain(secret); expect(host.querySelector('textarea')?.value ?? '').not.toContain(secret);
  await remount(); await act(async () => button('核对原操作').click());
  expect(personalRemoteApi.recoverCredential).toHaveBeenCalledWith(p.requestId, 'alice'); expect(personalRemoteApi.saveCredential).toHaveBeenCalledTimes(1);
  expect(personalSSHApi.identity).toHaveBeenCalledTimes(1); expect(personalSSHApi.configure).not.toHaveBeenCalled();
  expect(button('保存身份并登记服务器').disabled).toBe(true); expect(localStorage.getItem(storage)).toBeNull();
});

it('recovers ambiguous registration without another credential or configuration mutation', async () => {
  vi.mocked(personalSSHApi.configure).mockRejectedValue(new Error('lost response'));
  vi.spyOn(personalSSHApi, 'recover').mockImplementation(async (_, requestId, action) => ({ requestId, action, server }));
  await mount(); await preview(); await save(); const p = JSON.parse(localStorage.getItem(storage)!);
  expect(p.action).toBe('configure'); expect(JSON.stringify(p)).not.toContain(secret);
  await remount(); await act(async () => button('核对原操作').click());
  expect(personalSSHApi.recover).toHaveBeenCalledWith('alice', p.requestId, 'configure'); expect(personalSSHApi.configure).toHaveBeenCalledTimes(1); expect(personalRemoteApi.saveCredential).toHaveBeenCalledTimes(1); expect(localStorage.getItem(storage)).toBeNull();
});

it('makes a known missing dependency correctable and never enables or prepares the server', async () => {
  let release!: (value: PersonalSSHServer[]) => void;
  vi.mocked(personalSSHApi.list).mockResolvedValueOnce([{ ...server, diagnostic: 'SSH_DOCKER_MISSING' }]).mockImplementationOnce(() => new Promise(resolve => { release = resolve; }));
  vi.mocked(personalSSHApi.command).mockRejectedValue(new RemoteRequestError(true, 'SSH_PYTHON_MISSING'));
  await mount(); await act(async () => button('检查连接与依赖').click());
  expect(host.textContent).toContain('未找到 python3'); expect(host.textContent).toContain('Python 3.12+'); expect(localStorage.getItem(storage)).toBeNull(); expect(button('启用此服务器')).toBeUndefined(); expect(personalSSHApi.command).toHaveBeenCalledTimes(1);
  expect(host.textContent).not.toContain('未找到 Docker');
  await act(async () => release([{ ...server, status: 'failed', diagnostic: 'SSH_PYTHON_MISSING' }]));
});

it('recovers a failed original check by its matching failure evidence without checking again', async () => {
  vi.mocked(personalSSHApi.list).mockResolvedValue([server]); vi.mocked(personalSSHApi.command).mockRejectedValue(new Error('lost check result'));
  vi.spyOn(personalSSHApi, 'recover').mockRejectedValue(new RemoteRequestError(true));
  vi.spyOn(personalSSHApi, 'inspect').mockImplementation(async () => ({ ...server, status: 'failed', diagnostic: 'SSH_DOCKER_PERMISSION', lastCheckRequestId: JSON.parse(localStorage.getItem(storage)!).requestId }));
  await mount(); await act(async () => button('检查连接与依赖').click()); await act(async () => button('核对原操作').click());
  expect(personalSSHApi.command).toHaveBeenCalledTimes(1); expect(localStorage.getItem(storage)).toBeNull(); expect(host.textContent).toContain('此 SSH 账户无权使用 Docker');
});

it('keeps an unknown enable receipt pending until lookup, without auto binding on reload', async () => {
  vi.mocked(personalSSHApi.list).mockResolvedValue([{ ...server, status: 'verified' }]); vi.mocked(personalSSHApi.command).mockRejectedValue(new Error('lost bind result'));
  vi.spyOn(personalSSHApi, 'recover').mockImplementation(async (_, requestId, action) => ({ requestId, action, server: { ...server, status: 'verified', enabled: true } }));
  await mount(); await act(async () => button('启用此服务器').click()); const p = JSON.parse(localStorage.getItem(storage)!);
  await remount(); expect(personalSSHApi.command).toHaveBeenCalledTimes(1); await act(async () => button('核对原操作').click());
  expect(personalSSHApi.recover).toHaveBeenCalledWith('alice', p.requestId, 'bind'); expect(personalSSHApi.command).toHaveBeenCalledTimes(1); expect(localStorage.getItem(storage)).toBeNull();
});

it('preserves an unresolved original lookup when explicitly stopping waiting', async () => {
  vi.mocked(personalSSHApi.list).mockResolvedValue([server]); vi.mocked(personalSSHApi.command).mockRejectedValue(new Error('unknown'));
  const recover = vi.spyOn(personalSSHApi, 'recover').mockRejectedValue(new RemoteRequestError(true)); vi.spyOn(personalSSHApi, 'inspect').mockResolvedValue(server);
  await mount(); await act(async () => button('检查连接与依赖').click()); const p = JSON.parse(localStorage.getItem(storage)!);
  await act(async () => button('核对原操作').click()); expect(localStorage.getItem(storage)).not.toBeNull();
  await act(async () => button('停止等待').click()); expect(localStorage.getItem(storage)).not.toBeNull(); await act(async () => button('确认停止等待并保留记录').click());
  expect(localStorage.getItem(storage)).toBeNull(); expect(JSON.parse(localStorage.getItem(storage + ':unresolved')!)).toEqual([p]);
  await remount(); await act(async () => button('核对保留结果').click()); expect(recover).toHaveBeenCalledWith('alice', p.requestId, 'verify'); expect(personalSSHApi.command).toHaveBeenCalledTimes(1);
});

it('clears secret input and blocks a stale owner before saving or on expected-owner rejection', async () => {
  await mount(); await preview(); await field('专用 SSH 私钥', secret); await consent(); vi.mocked(api.session).mockResolvedValue({ id: 'bob', name: 'Bob', role: 'user' });
  await act(async () => button('保存身份并登记服务器').click()); expect(personalRemoteApi.saveCredential).not.toHaveBeenCalled(); expect(host.textContent).toContain('登录账户已改变'); expect(host.querySelector('textarea')).toBeNull(); expect(JSON.stringify(localStorage)).not.toContain(secret);
});

it('rejects a server-side owner race and never chains registration after a rejected key save', async () => {
  vi.mocked(personalRemoteApi.saveCredential).mockRejectedValue(new RemoteRequestError(true, 'EXPECTED_OWNER_MISMATCH'));
  await mount(); await preview(); await save(); expect(personalSSHApi.configure).not.toHaveBeenCalled(); expect(host.textContent).toContain('登录账户已改变'); expect(host.querySelector('textarea')).toBeNull();
});

it('remounts owner state and ignores a late key receipt after switching owners', async () => {
  let release!: (value: typeof credential) => void;
  vi.mocked(personalRemoteApi.saveCredential).mockImplementation(() => new Promise(resolve => { release = resolve; }));
  await mount(); await preview(); await field('专用 SSH 私钥', secret); await consent();
  await act(async () => button('保存身份并登记服务器').click());
  expect(personalRemoteApi.saveCredential).toHaveBeenCalledTimes(1);
  const original = localStorage.getItem(storage); expect(original).not.toBeNull();
  vi.mocked(api.session).mockResolvedValue({ id: 'bob', name: 'Bob', role: 'user' });
  await mount('bob');
  expect(button('核对原操作')).toBeUndefined(); expect(host.querySelector('textarea')).toBeNull();
  await act(async () => release(credential));
  expect(personalSSHApi.configure).not.toHaveBeenCalled(); expect(localStorage.getItem(storage)).toBe(original);
  expect(localStorage.getItem('factory-personal-ssh:bob')).toBeNull(); expect(JSON.stringify(localStorage)).not.toContain(secret);
});

it('ignores another owner lookup and malformed secret-bearing browser state', async () => {
  localStorage.setItem(storage, JSON.stringify({ owner: 'bob', action: 'credential', requestId: 'original', input, destination }));
  await mount(); expect(button('核对原操作')).toBeUndefined();
  await act(async () => root.unmount()); root = createRoot(host); localStorage.setItem(storage, JSON.stringify({ owner: 'alice', action: 'credential', requestId: 'original', input, destination, password: secret }));
  await mount(); expect(button('核对原操作')).toBeUndefined(); expect(personalRemoteApi.saveCredential).not.toHaveBeenCalled();
});

it('retains the HTTPS credential domain and accepts SSH only for its explicit provider', () => {
  expect(credentialDestination('https://example.org')).toBe('https://example.org'); expect(credentialReceipt(credential)).toEqual(credential);
  expect(() => credentialDestination(destination)).toThrow(); expect(() => credentialReceipt({ ...credential, providerId: 'byok-chat-v1' })).toThrow(); expect(() => credentialReceipt({ ...credential, destination: destination + '&extra=1' })).toThrow();
});
