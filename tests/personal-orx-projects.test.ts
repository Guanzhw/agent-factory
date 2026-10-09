// @vitest-environment happy-dom
import { webcrypto } from 'node:crypto';
import { act, createElement, useEffect } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { PersonalOrxProjects } from '../web/PersonalOrxProjects.js';
import { api } from '../web/api.js';
import { personalAgentApi, ORX_PERSONAL_PROVIDER } from '../web/personalAgentApi.js';
import { personalRemoteApi, type PersonalRemote } from '../web/personalRemoteApi.js';
import { personalOrxProjectApi, checkOrxProjectReceipt, checkOrxProjectPrepared, type OrxProjectReceipt, type ProjectPreview, type OrxProjectPrepared } from '../web/personalOrxProjectApi.js';
import type { FactoryJob, Plan, UserConnection } from '../web/models.js';

vi.mock('../web/PlanReviews.js', () => ({ PlanReviewGate: ({ onAllowed }: { onAllowed: (value: boolean) => void }) => { useEffect(() => { onAllowed(true); return () => onAllowed(false); }, [onAllowed]); return createElement('p', {}, 'Existing administrative plan review fixture'); } }));
const owner = { id: 'fixture-owner', name: 'Fixture', role: 'user' as const };
const connection = { ref: 'creation-binding', registrationRef: 'creation-remote', ownerId: owner.id, kind: 'orx', status: 'active', available: true, taskId: null, capabilities: ['runtime:health', 'project:read', 'project:create'], fingerprint: 'a'.repeat(64), revision: 'r1', version: 1 } as UserConnection;
const remote = { registrationRef: connection.registrationRef, providerId: ORX_PERSONAL_PROVIDER } as PersonalRemote;
const request = { name: 'Synthetic project', path: '/synthetic/new-project', createFolder: true, requireNewFolder: true, initializeGit: true, cloneUrl: null, paperId: null, locale: 'zh', github_sync_enabled: false, githubSyncEnabled: false } as const;
const preview: ProjectPreview = { previewHash: 'b'.repeat(64), connectionPin: connection, request,
  disclosure: { version: 'native-orx-create-consent-v2', remotePath: request.path, repository: null, paperId: null, remoteWrites: 'create-new-folder-and-project', clone: false, paperDownload: false, gitInitialization: true, githubSyncEnabled: false, pathResolution: 'upstream-canonical-path-and-enclosing-git-root', starterSuggestions: 'may-request-four-project-chat-suggestions', modelInput: ['README', 'selected-code', 'file-list', 'paper-summary'], modelSelection: 'remote-preferred-or-ready-harness', billing: 'owner-remote-account-possible-cost', hardBudgetEnforced: false, automaticExperiment: false, emptyCacheHitOrNoHarness: 'may-skip-model-request', unknownResponse: 'read-only-reconcile-never-resend' } };
function receipt(requestId = 'original-request', extra: Partial<OrxProjectReceipt> = {}): OrxProjectReceipt { return { requestId, action: 'project_create', planId: 'plan-project', consentState: 'awaiting', state: 'awaiting', preview, result: null, factoryIdentity: null, candidates: [], candidateCorrelation: 'unproven-does-not-settle-original-request', liveEndToEndVerified: false, ...extra }; }
function prepared(requestId = 'original-request', extra: Partial<OrxProjectReceipt> = {}): OrxProjectPrepared { const r = receipt(requestId, extra); return { plan: { id: r.planId, fingerprint: 'plan-fingerprint', status: 'ready', applicationRef: { id: 'personal-orx-project-create-v1', version: 1, sha256: 'c'.repeat(64) }, inputValues: { requestId, action: 'project_create', text: JSON.stringify(r.preview) }, missing: [] } as unknown as Plan, authorization: {} as OrxProjectPrepared['authorization'], receipt: r }; }
const job = { id: 'task-project', planId: 'plan-project', ownerId: owner.id, status: 'running' } as FactoryJob;
const identity = { planId: job.planId!, taskId: job.id, nativeRunId: 'run-project', executionContract: 'personal-external-v1' as const };
const key = `factory-orx-project-create:${owner.id}`;
let host: HTMLDivElement; let root: Root; const connected = vi.fn(); const navigateTask = vi.fn();
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); vi.stubGlobal('crypto', webcrypto); localStorage.clear(); connected.mockReset(); navigateTask.mockReset();
  host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host);
  vi.spyOn(api, 'session').mockResolvedValue(owner); vi.spyOn(api, 'userConnections').mockResolvedValue([connection]); vi.spyOn(personalRemoteApi, 'list').mockResolvedValue([remote]);
  vi.spyOn(personalOrxProjectApi, 'prepare').mockImplementation(async input => prepared(input.requestId));
  vi.spyOn(personalOrxProjectApi, 'decide').mockImplementation(async (id, _hash, approved) => receipt(id, { consentState: approved ? 'approved' : 'cancelled', state: approved ? 'approved' : 'cancelled' }));
  vi.spyOn(personalAgentApi, 'start').mockResolvedValue(job); vi.spyOn(personalOrxProjectApi, 'submit').mockResolvedValue(job);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function mount(ownerId = owner.id) { await act(async () => root.render(createElement(PersonalOrxProjects, { ownerId, onConnected: connected, onTask: navigateTask }))); }
function button(text: string) { const value = [...host.querySelectorAll('button')].find(b => b.textContent === text); if (!value) throw new Error('Missing ' + text); return value; }
async function click(text: string) { await act(async () => button(text).click()); }
async function fill(label: string, value: string) { await act(async () => { const el = host.querySelector<HTMLInputElement | HTMLSelectElement>(`[aria-label="${label}"]`)!; const select = el.tagName === 'SELECT'; Object.getOwnPropertyDescriptor(select ? HTMLSelectElement.prototype : HTMLInputElement.prototype, 'value')!.set!.call(el, value); el.dispatchEvent(new Event(select ? 'change' : 'input', { bubbles: true })); }); }
async function enter() { await mount(); await fill('项目创建资源', connection.ref); await fill('项目名称', request.name); await fill('远端项目绝对路径', request.path); }
async function previewCreation() { await enter(); await click('预览项目创建'); }
async function consent() { await act(async () => host.querySelector<HTMLInputElement>('[aria-label="批准此次项目创建副作用"]')!.click()); }

it('requires disclosed per-request approval and one submission on double click', async () => {
  await enter(); await act(async () => { button('预览项目创建').click(); button('预览项目创建').click(); });
  expect(personalOrxProjectApi.prepare).toHaveBeenCalledTimes(1); expect(personalAgentApi.start).not.toHaveBeenCalled();
  expect(host.textContent).toContain('README、部分代码、文件清单或论文摘要'); expect(host.textContent).toContain('GitHub 自动同步明确关闭'); expect(host.textContent).toContain('不自动开展实验');
  expect(button('批准并提交此次创建').disabled).toBe(true); await consent();
  await act(async () => { button('批准并提交此次创建').click(); button('批准并提交此次创建').click(); });
  expect(personalOrxProjectApi.submit).toHaveBeenCalledTimes(1); expect(personalOrxProjectApi.submit).toHaveBeenCalledWith(expect.any(String), preview.previewHash, job.planId); expect(personalOrxProjectApi.decide).not.toHaveBeenCalled(); expect(personalAgentApi.start).not.toHaveBeenCalled();
  expect(navigateTask).not.toHaveBeenCalled(); await click('查看原创建任务进度与结果'); expect(navigateTask).toHaveBeenCalledWith(job.id);
  expect(localStorage.getItem(key)).not.toContain(request.path); expect(localStorage.getItem(key)).not.toContain(request.name);
});
it('cancels the exact prepared request without dispatch and releases only proven cancelled consent', async () => {
  await previewCreation(); await click('取消此次创建批准');
  expect(personalOrxProjectApi.decide).toHaveBeenCalledWith(expect.any(String), preview.previewHash, false);
  expect(personalAgentApi.start).not.toHaveBeenCalled(); expect(localStorage.getItem(key)).toBeNull(); expect(host.textContent).toContain('已取消此创建批准');
});
it('discloses cloning into an existing empty directory and symlink targets before consent', async () => {
  const cloneRequest = { ...request, initializeGit: false, path: '/synthetic/already-empty', cloneUrl: 'https://github.com/synthetic-fixture/example' };
  const clonePreview: ProjectPreview = { ...preview, request: cloneRequest, disclosure: { ...preview.disclosure, remotePath: cloneRequest.path, repository: cloneRequest.cloneUrl, clone: true, gitInitialization: false, remoteWrites: 'clone-into-new-or-existing-empty-folder-and-project', pathResolution: 'upstream-clone-target-symlinks-followed-no-new-folder-guarantee' } };
  vi.mocked(personalOrxProjectApi.prepare).mockImplementation(async input => prepared(input.requestId, { preview: clonePreview }));
  await enter(); await fill('项目来源', 'clone'); await fill('远端项目绝对路径', cloneRequest.path); await fill('公开仓库 HTTPS URL', cloneRequest.cloneUrl); await click('预览项目创建');
  expect(host.textContent).toContain(cloneRequest.path); expect(host.textContent).toContain(cloneRequest.cloneUrl);
  expect(host.textContent).toContain('新目录或已有空目录'); expect(host.textContent).toContain('clone 可能修改已有空目录'); expect(host.textContent).toContain('符号链接'); expect(host.textContent).toContain('Factory 未检查或锁定远端路径');
  expect(host.textContent).not.toContain('将在远端新建目录并登记项目'); expect(button('批准并提交此次创建').disabled).toBe(true); expect(personalAgentApi.start).not.toHaveBeenCalled();
  const r = receipt('original-request', { preview: clonePreview });
  expect(checkOrxProjectReceipt(r, 'original-request', owner.id)).toEqual(r);
  expect(() => checkOrxProjectReceipt({ ...r, preview: { ...clonePreview, disclosure: { ...clonePreview.disclosure, remoteWrites: 'create-new-folder-and-project' } } }, 'original-request', owner.id)).toThrow();
  expect(() => checkOrxProjectReceipt({ ...r, preview: { ...clonePreview, disclosure: { ...clonePreview.disclosure, version: 'native-orx-create-consent-v1' } } }, 'original-request', owner.id)).toThrow();
});
it('lost preview recovers the original immutable plan read-only and requires fresh consent', async () => {
  vi.mocked(personalOrxProjectApi.prepare).mockRejectedValue(new Error('private service token'));
  const recover = vi.spyOn(personalOrxProjectApi, 'recover').mockImplementation(async id => ({ ...prepared(id), requestId: id, job: null, nativeRunId: null }));
  await enter(); await click('预览项目创建'); const id = vi.mocked(personalOrxProjectApi.prepare).mock.calls[0][0].requestId;
  expect(host.textContent).not.toContain('private service token'); await click('核对原项目创建请求');
  expect(recover).toHaveBeenCalledWith(id); expect(personalOrxProjectApi.prepare).toHaveBeenCalledTimes(1); expect(personalAgentApi.start).not.toHaveBeenCalled(); expect(button('批准并提交此次创建').disabled).toBe(true);
});
it('lost start and missing job never permit replay after reload', async () => {
  localStorage.setItem(key, JSON.stringify({ requestId: 'original-request', planId: 'plan-project', startAttempt: true }));
  vi.spyOn(personalOrxProjectApi, 'recover').mockResolvedValue({ ...prepared(), requestId: 'original-request', job: null, nativeRunId: null });
  await mount(); await click('核对原项目创建请求'); expect(host.textContent).toContain('尚未找到原任务不代表未提交');
  expect([...host.querySelectorAll('button')].some(b => b.textContent === '批准并提交此次创建')).toBe(false);
  expect(personalAgentApi.start).not.toHaveBeenCalled(); expect(personalOrxProjectApi.prepare).not.toHaveBeenCalled();
});
it('UNKNOWN candidates remain unproven and cannot trigger connect, approval or create', async () => {
  localStorage.setItem(key, JSON.stringify({ requestId: 'original-request', planId: 'plan-project', startAttempt: true }));
  const unknown = receipt('original-request', { state: 'ack_unknown', consentState: 'dispatch_started', factoryIdentity: identity });
  vi.spyOn(personalOrxProjectApi, 'recover').mockResolvedValue({ ...prepared('original-request', unknown), requestId: 'original-request', job, nativeRunId: identity.nativeRunId });
  const reconcile = vi.spyOn(personalOrxProjectApi, 'reconcile').mockResolvedValue({ ...unknown, candidates: [{ nativeProjectId: 'possible-project', name: '<script>candidate</script>', path: request.path }] });
  await mount(); await click('核对原项目创建请求'); await click('只读核对远端候选项目');
  expect(reconcile).toHaveBeenCalledWith('original-request'); expect(host.textContent).toContain('关联未经证明'); expect(host.querySelector('script')).toBeNull();
  expect(host.textContent).not.toContain('关联新项目并进入原生会话'); expect(personalAgentApi.start).not.toHaveBeenCalled(); expect(personalOrxProjectApi.decide).not.toHaveBeenCalled();
});
it('connects an acknowledged original project only after explicit harness/model selection', async () => {
  localStorage.setItem(key, JSON.stringify({ requestId: 'original-request', planId: 'plan-project', startAttempt: true }));
  const ack = receipt('original-request', { state: 'acknowledged', consentState: 'dispatch_started', factoryIdentity: identity, result: { nativeProjectId: 'native-created', name: request.name, path: request.path, namespace: 'native-openresearch', githubSyncRequested: false, correlationSource: 'native-create-response', liveEndToEndVerified: false } });
  vi.spyOn(personalOrxProjectApi, 'recover').mockResolvedValue({ ...prepared('original-request', ack), requestId: 'original-request', job, nativeRunId: identity.nativeRunId });
  const connect = vi.spyOn(personalOrxProjectApi, 'connect').mockResolvedValue({ ...connection, ref: 'created-project-binding', capabilities: ['session:read', 'session:create'] });
  await mount(); await click('核对原项目创建请求'); expect(button('关联新项目并进入原生会话').disabled).toBe(true);
  await fill('新会话 harness', 'opencode'); await fill('新会话模型 ID', 'owner/model'); await click('关联新项目并进入原生会话');
  expect(connect).toHaveBeenCalledWith('original-request', 'opencode', 'owner/model'); expect(connected).toHaveBeenCalledWith('created-project-binding'); expect(personalAgentApi.start).not.toHaveBeenCalled(); expect(localStorage.getItem(key)).toBeNull();
});
it('does not upgrade existing project bindings into project creation authority', async () => {
  vi.mocked(api.userConnections).mockResolvedValue([{ ...connection, capabilities: ['session:read', 'session:create'] }]); await mount();
  expect(host.textContent).toContain('启用“用于创建新项目”'); expect(host.querySelectorAll('[aria-label="项目创建资源"] option')).toHaveLength(1);
});
it('storage failure blocks preparation before any HTTP intent', async () => {
  await enter(); const storage = localStorage; vi.stubGlobal('localStorage', new Proxy(storage, { get(target, key) { return key === 'setItem' ? () => { throw new Error('denied'); } : Reflect.get(target, key); } }));
  await click('预览项目创建'); expect(personalOrxProjectApi.prepare).not.toHaveBeenCalled(); expect(personalAgentApi.start).not.toHaveBeenCalled();
});
it('ignores late owner responses and clears prior owner material', async () => {
  let finish!: (value: OrxProjectPrepared) => void; let id = '';
  vi.mocked(personalOrxProjectApi.prepare).mockImplementation(input => { id = input.requestId; return new Promise(resolve => { finish = resolve; }); });
  await enter(); await click('预览项目创建'); await mount('other-owner'); await act(async () => finish(prepared(id)));
  expect(host.textContent).not.toContain(request.path); expect(host.querySelector('[aria-label="项目创建副作用预览"]')).toBeNull(); expect(personalAgentApi.start).not.toHaveBeenCalled();
});
it('rejects changed preview, sync/billing promises, owner and live claims', () => {
  expect(checkOrxProjectPrepared(prepared(), 'original-request', owner.id)).toEqual(prepared());
  for (const r of [receipt('other-request'), receipt('original-request', { liveEndToEndVerified: true } as unknown as Partial<OrxProjectReceipt>), receipt('original-request', { preview: { ...preview, request: { ...request, githubSyncEnabled: true } } as unknown as ProjectPreview }), receipt('original-request', { preview: { ...preview, disclosure: { ...preview.disclosure, hardBudgetEnforced: true } } as unknown as ProjectPreview })]) expect(() => checkOrxProjectReceipt(r, 'original-request', owner.id)).toThrow();
  expect(() => checkOrxProjectReceipt(receipt(), 'original-request', 'other-owner')).toThrow();
  expect(() => checkOrxProjectPrepared({ ...prepared(), receipt: receipt('original-request', { preview: { ...preview, request: { ...request, path: '/changed' }, disclosure: { ...preview.disclosure, remotePath: '/changed' } } }) }, 'original-request')).toThrow();
});
