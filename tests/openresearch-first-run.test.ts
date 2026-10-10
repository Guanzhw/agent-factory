// @vitest-environment happy-dom
import { webcrypto } from 'node:crypto';
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { PersonalAgentSessions } from '../web/PersonalAgentSessions.js';
import { api } from '../web/api.js';
import { personalAgentApi, ORX_PERSONAL_PROVIDER } from '../web/personalAgentApi.js';
import { personalRemoteApi, type PersonalRemote, type PersonalCredential } from '../web/personalRemoteApi.js';
import { personalOrxProjectApi, type OrxProjectReceipt, type ProjectPreview, type OrxProjectPrepared } from '../web/personalOrxProjectApi.js';
import type { Plan, UserConnection } from '../web/models.js';
vi.mock('../web/PlanReviews.js', () => ({ PlanReviewGate: () => null }));
const owner = { id: 'fixture-owner', name: 'Fixture', role: 'user' as const };
const connection = { ref: 'creation-binding', registrationRef: 'creation-remote', ownerId: owner.id, kind: 'orx', status: 'active', available: true, taskId: null, capabilities: ['runtime:health', 'project:read', 'project:create'], fingerprint: 'a'.repeat(64), revision: 'r1', version: 1 } as UserConnection;
const remote = { registrationRef: connection.registrationRef, providerId: ORX_PERSONAL_PROVIDER } as PersonalRemote;
const request = { name: 'Synthetic project', path: '/synthetic/new-project', createFolder: true, requireNewFolder: true, initializeGit: true, cloneUrl: null, paperId: null, locale: 'zh', github_sync_enabled: false, githubSyncEnabled: false } as const;
const preview: ProjectPreview = { previewHash: 'b'.repeat(64), connectionPin: connection, request,
  disclosure: { version: 'native-orx-create-consent-v2', remotePath: request.path, repository: null, paperId: null, remoteWrites: 'create-new-folder-and-project', clone: false, paperDownload: false, gitInitialization: true, githubSyncEnabled: false, pathResolution: 'upstream-canonical-path-and-enclosing-git-root', starterSuggestions: 'may-request-four-project-chat-suggestions', modelInput: ['README', 'selected-code', 'file-list', 'paper-summary'], modelSelection: 'remote-preferred-or-ready-harness', billing: 'owner-remote-account-possible-cost', hardBudgetEnforced: false, automaticExperiment: false, emptyCacheHitOrNoHarness: 'may-skip-model-request', unknownResponse: 'read-only-reconcile-never-resend' } };
function receipt(requestId = 'original-request', extra: Partial<OrxProjectReceipt> = {}): OrxProjectReceipt { return { requestId, action: 'project_create', planId: 'plan-project', consentState: 'awaiting', state: 'awaiting', preview, result: null, factoryIdentity: null, candidates: [], candidateCorrelation: 'unproven-does-not-settle-original-request', liveEndToEndVerified: false, ...extra }; }
function prepared(requestId = 'original-request', extra: Partial<OrxProjectReceipt> = {}): OrxProjectPrepared { const r = receipt(requestId, extra); return { plan: { id: r.planId, fingerprint: 'plan-fingerprint', status: 'ready', applicationRef: { id: 'personal-orx-project-create-v1', version: 1, sha256: 'c'.repeat(64) }, inputValues: { requestId, action: 'project_create', text: JSON.stringify(r.preview) }, missing: [] } as unknown as Plan, authorization: {} as OrxProjectPrepared['authorization'], receipt: r }; }

let host: HTMLDivElement; let root: Root;
let bindings: UserConnection[]; let records: PersonalRemote[];
const credential: PersonalCredential = { providerId: ORX_PERSONAL_PROVIDER, destination: 'https://runtime.example.com', status: 'active', credentialRef: 'synthetic-credential', credentialRevision: 'r1' };
const configured: PersonalRemote = { ...remote, origin: credential.destination, projectId: '', configRevision: 'r1', revision: 'r1', status: 'configured', available: false, capabilities: ['runtime:health', 'project:read', 'project:create'], expiresAt: null, allowedActions: ['verify'] };
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); vi.stubGlobal('crypto', webcrypto); localStorage.clear(); sessionStorage.clear();
  host = document.createElement('div'); document.body.append(host); root = createRoot(host); bindings = []; records = [];
  vi.spyOn(api, 'session').mockResolvedValue(owner); vi.spyOn(api, 'userConnections').mockImplementation(async () => bindings);
  vi.spyOn(personalAgentApi, 'capabilities').mockResolvedValue({ executionContract: 'personal-external-v1', nativeQueue: true, ownerSubmit: '/api/factory/personal-agent/commands/submit', modelConfiguration: 'remote-configured-model', factoryBYOKForwarded: false });
  vi.spyOn(personalAgentApi, 'sessions').mockResolvedValue([]); vi.spyOn(personalAgentApi, 'submit');
  vi.spyOn(personalRemoteApi, 'list').mockImplementation(async () => records);
  vi.spyOn(personalRemoteApi, 'providers').mockResolvedValue([{ providerId: ORX_PERSONAL_PROVIDER, kind: 'orx', capabilities: configured.capabilities, authModes: ['bearer'], projectCreationSupported: true }]);
  vi.spyOn(personalRemoteApi, 'credentialAvailability').mockResolvedValue({ enabled: true, providerIds: [ORX_PERSONAL_PROVIDER] });
  vi.spyOn(personalRemoteApi, 'credentials').mockResolvedValue([]);
  vi.spyOn(personalRemoteApi, 'saveCredential').mockResolvedValue(credential);
  vi.spyOn(personalRemoteApi, 'configure').mockImplementation(async () => { records = [configured]; return configured; });
  vi.spyOn(personalRemoteApi, 'command').mockImplementation(async () => { records = [{ ...configured, status: 'verified', available: true, expiresAt: new Date(Date.now() + 3600000).toISOString(), allowedActions: ['verify', 'bind'] }]; return records[0]; });
  vi.spyOn(api, 'bindConnection').mockImplementation(async () => { bindings = [connection]; return connection; });
  vi.spyOn(personalOrxProjectApi, 'existing').mockResolvedValue([]);
  vi.spyOn(personalOrxProjectApi, 'prepare').mockImplementation(async input => prepared(input.requestId));
  vi.spyOn(personalOrxProjectApi, 'submit');
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const button = (name: string) => [...host.querySelectorAll('button')].find(b => b.textContent === name)!;
async function click(name: string) { await act(async () => { button(name).click(); await new Promise(resolve => setTimeout(resolve, 10)); }); }
async function fill(label: string, value: string) { await act(async () => {
  const el = host.querySelector<HTMLInputElement | HTMLTextAreaElement>(`[aria-label="${label}"]`)!;
  Object.getOwnPropertyDescriptor(el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype, 'value')!.set!.call(el, value);
  el.dispatchEvent(new Event('input', { bubbles: true }));
}); }
it('adds, verifies and binds an empty service on the same first-run page, then previews its first project without remounting or losing the goal', async () => {
  await act(async () => root.render(createElement(PersonalAgentSessions, { ownerId: owner.id, namespace: 'native-openresearch', researchJourney: true })));
  expect(bindings).toEqual([]); expect(host.querySelector<HTMLSelectElement>('[aria-label="项目创建资源"]')!.options.length).toBe(1);
  await fill('研究目标', 'Preserve my first research goal'); await fill('HTTPS 服务源', credential.destination);
  await click('输入并保存个人凭据'); await fill('OpenResearch 服务令牌', 'synthetic-only');
  await act(async () => host.querySelector<HTMLInputElement>('[aria-label="安全保存个人凭据"] input[type="checkbox"]')!.click());
  await click('确认安全保存凭据'); await click('确认保存配置'); await click('验证远程服务'); await click('确认绑定项目创建连接');
  expect(api.bindConnection).toHaveBeenCalledTimes(1); expect(host.textContent).toContain('此服务还没有可读取的项目');
  await click('设置我的第一个研究项目');
  const select = host.querySelector<HTMLSelectElement>('[aria-label="项目创建资源"]')!;
  expect(select.value).toBe(connection.ref); expect(select.options.length).toBe(2);
  await fill('远端项目绝对路径', request.path); expect(button('预览项目创建').disabled).toBe(false);
  await click('预览项目创建');
  expect(personalOrxProjectApi.prepare).toHaveBeenCalledWith(expect.objectContaining({ connectionRef: connection.ref, project: expect.objectContaining({ path: request.path, source: 'empty' }) }));
  expect(host.querySelector('[aria-label="项目创建副作用预览"]')).not.toBeNull();
  expect(host.querySelector<HTMLTextAreaElement>('[aria-label="研究目标"]')!.value).toBe('Preserve my first research goal');
  expect(personalOrxProjectApi.submit).not.toHaveBeenCalled(); expect(personalAgentApi.submit).not.toHaveBeenCalled();
  expect(JSON.stringify(localStorage)).not.toContain('synthetic-only');
});
