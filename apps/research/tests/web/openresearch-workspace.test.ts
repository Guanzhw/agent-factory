// @vitest-environment happy-dom
import { webcrypto } from 'node:crypto';
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { OpenResearchWorkspace } from '../../web/OpenResearchWorkspace.js';
import { personalAgentApi } from '../../web/personalAgentApi.js';
import { personalRemoteApi } from '../../../../web/personalRemoteApi.js';
import { api, ApiError } from '../../../../web/api.js';
import { openresearchApi, researchProject, researchSession, type ResearchProject, type ResearchSession, type ManagedResearchSession } from '../../web/openresearchApi.js';
import type { UserConnection, PlanAuthorization } from '../../../../web/models.js';
const hash = 'a'.repeat(64);
const owner = { id: 'alice', name: 'Alice', role: 'user' as const };
const native = { id: 'native-1', name: '真实来源项目', projectIdentityHash: hash, verificationStatus: 'metadata-observed', evidenceKind: 'native-project-metadata' };
const project: ResearchProject = { id: 'orp-one', name: native.name, description: '', kind: 'native-openresearch', upstreamProjectId: native.id, nativeProject: native, connectionRefs: { workspace: 'orx-alice' }, sessionExecutionAvailable: false, sessionBlocker: 'NATIVE_PROJECT_GOVERNED_SESSION_BINDING_REQUIRED' };
const group: ResearchProject = { id: 'orp-group', name: '受控分组', description: '', kind: 'factory-workspace', connectionRefs: {}, upstreamProjectId: null };
const session: ResearchSession = { id: 'ors-one', projectId: group.id, goal: '受控目标', workloadPresetId: 'preset-one', state: 'unknown', taskId: null, executionContract: 'controlled-workload-v1', contextSource: 'approved-workload-preset', verificationStatus: 'not-live-verified' };
const connection: UserConnection = { ref: 'orx-alice', ownerId: 'alice', kind: 'orx', status: 'active', available: true, taskId: null, capabilities: ['project:read'], revision: 'one', version: 1, fingerprint: hash, registrationRef: 'installed-orx', expiresAt: null, revokedAt: null, createdAt: '', allowedActions: ['inspect'] };
let host: HTMLDivElement; let root: Root;
const onTask = vi.fn();
const find = (label: string) => [...host.querySelectorAll('button')].find(b => b.textContent === label)!;
async function click(label: string) { expect(find(label)).toBeTruthy(); await act(async () => find(label).click()); }
async function mount() { await act(async () => root.render(createElement(OpenResearchWorkspace, { ownerId: 'alice', onTask, onResources: vi.fn(), onCatalog: vi.fn() }))); await click('切换受管模式（可选）'); }
async function mountManaged() { await act(async () => root.render(createElement(OpenResearchWorkspace, { ownerId: 'alice', selectedMode: 'managed', onTask, onResources: vi.fn(), onCatalog: vi.fn() }))); }
async function input(label: string, value: string) { await act(async () => { const el = host.querySelector<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>(`[aria-label="${label}"]`)!; const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : el.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype; Object.getOwnPropertyDescriptor(proto, 'value')!.set!.call(el, value); el.dispatchEvent(new Event(el.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true })); }); }
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); vi.stubGlobal('crypto', webcrypto); localStorage.clear(); onTask.mockReset();
  host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host);
  vi.spyOn(personalAgentApi, 'sessions').mockResolvedValue([]); vi.spyOn(personalAgentApi, 'capabilities').mockRejectedValue(new Error('ordinary disabled in managed fixture')); vi.spyOn(personalRemoteApi, 'list').mockResolvedValue([]);
  vi.spyOn(api, 'session').mockResolvedValue(owner); vi.spyOn(api, 'userConnections').mockResolvedValue([connection]);
  vi.spyOn(openresearchApi, 'capabilities').mockResolvedValue({ contractVersion: 1, nativeProjectAttachment: true, upstreamProjectCreation: false, liveEndToEndVerified: false, workloads: [{ id: 'preset-one', name: '受控预设', ready: true, blockers: [], limits: { maxExperiments: 1 } }] });
  vi.spyOn(openresearchApi, 'projects').mockResolvedValue([]); vi.spyOn(openresearchApi, 'project').mockImplementation(async id => id === group.id ? group : project);
  vi.spyOn(openresearchApi, 'native').mockResolvedValue([native]); vi.spyOn(openresearchApi, 'attach').mockResolvedValue(project); vi.spyOn(openresearchApi, 'refresh').mockResolvedValue(project);
  vi.spyOn(openresearchApi, 'managedProfiles').mockResolvedValue([]);
  vi.spyOn(openresearchApi, 'sessions').mockResolvedValue([]); vi.spyOn(openresearchApi, 'start').mockResolvedValue(session); vi.spyOn(openresearchApi, 'create').mockResolvedValue(group);
  vi.spyOn(openresearchApi, 'reconcile').mockResolvedValue(session); vi.spyOn(openresearchApi, 'recover').mockResolvedValue({ session });
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
it('reads actual owner resources, attaches exact identity, refreshes native metadata, never substitutes a preset', async () => {
  await mount(); expect(host.querySelector('#application-selector')).toBeNull();
  expect(host.querySelector('input[placeholder*="path"]')).toBeNull();
  await input('我的 OpenResearch 连接', connection.ref); await click('读取原生项目'); await click('关联此项目');
  expect(openresearchApi.attach).toHaveBeenCalledWith(connection.ref, native, expect.any(String));
  expect(host.textContent).toContain('NATIVE_PROJECT_GOVERNED_SESSION_BINDING_REQUIRED');
  expect(find('原生会话不可用').disabled).toBe(true);
  expect(host.querySelector('[aria-label="已批准工作负载"]')).toBeNull();
  await click('刷新原项目元数据'); expect(openresearchApi.refresh).toHaveBeenCalledWith(project.id);
  expect(openresearchApi.start).not.toHaveBeenCalled();
});
it('does not invent usable connections for unconfigured, foreign-owner, revoked or environment resources', async () => {
  vi.mocked(api.userConnections).mockResolvedValue([{ ...connection, kind: 'environment' }, { ...connection, ref: 'revoked', status: 'revoked', available: false }]);
  await mount(); expect(find('读取原生项目').disabled).toBe(true); expect(host.textContent).toContain('尚未配置可用的原生工作区连接');
  await act(async () => root.unmount()); root = createRoot(host); vi.mocked(api.userConnections).mockResolvedValue([{ ...connection, ownerId: 'bob' }]); await mount();
  expect(find('读取原生项目').disabled).toBe(true); expect(host.querySelectorAll('option')).toHaveLength(1);
});
it('persists an interrupted original request, suppresses repeated submissions, and only performs request lookup on recovery', async () => {
  vi.mocked(openresearchApi.projects).mockResolvedValue([group]);
  vi.mocked(openresearchApi.start).mockRejectedValue(new ApiError('lost reply', 0, 'OFFLINE'));
  await mount(); await act(async () => host.querySelector<HTMLButtonElement>('.or-project-card')!.click());
  await input('已批准工作负载', 'preset-one'); await input('研究目标', '受控目标');
  await act(async () => { find('确认范围并提交受控会话').click(); find('确认范围并提交受控会话').click(); });
  expect(openresearchApi.start).toHaveBeenCalledTimes(1);
  const original = vi.mocked(openresearchApi.start).mock.calls[0][3]; expect(localStorage.getItem('factory-or-pending:alice')).toBe(original);
  await act(async () => root.unmount()); root = createRoot(host); await mount();
  expect(host.textContent).toContain(original); expect(openresearchApi.start).toHaveBeenCalledTimes(1);
  vi.mocked(openresearchApi.sessions).mockResolvedValue([session]);
  await click('核对原请求'); expect(openresearchApi.recover).toHaveBeenCalledWith(original);
  expect(host.textContent).toContain('存在未核实准入的原会话'); expect(find('确认范围并提交受控会话').disabled).toBe(true);
  await click('核对原会话'); expect(openresearchApi.reconcile).toHaveBeenCalledWith(group.id, session.id);
  expect(openresearchApi.start).toHaveBeenCalledTimes(1);
});
it('routes results and cancellation to the original task and preserves unknown as unknown', async () => {
  vi.mocked(openresearchApi.projects).mockResolvedValue([group]); vi.mocked(openresearchApi.sessions).mockResolvedValue([{ ...session, taskId: 'original-task', state: 'running' }]);
  await mount(); await act(async () => host.querySelector<HTMLButtonElement>('.or-project-card')!.click());
  await click('任务、证据与取消'); expect(onTask).toHaveBeenCalledWith('original-task'); expect(host.textContent).toContain('not-live-verified');
  expect(openresearchApi.start).not.toHaveBeenCalled();
});
it('rejects wrong identities, malformed session results and native/factory boundary confusion', () => {
  expect(() => researchProject({ ...project, upstreamProjectId: 'different' })).toThrow();
  expect(() => researchProject({ ...group, upstreamProjectId: 'pretend-native' })).toThrow();
  expect(() => researchSession(session, 'other-project')).toThrow();
  expect(() => researchSession({ ...session, contextSource: 'native-project' }, group.id)).toThrow();
});
it('restores an original project pointer through read-only APIs without a new attach or admission', async () => {
  await act(async () => root.render(createElement(OpenResearchWorkspace, { ownerId: 'alice', selectedProject: project.id, onProject: vi.fn(), onTask, onResources: vi.fn(), onCatalog: vi.fn() })));
  expect(openresearchApi.project).toHaveBeenCalledWith(project.id, expect.any(AbortSignal));
  expect(host.textContent).toContain('NATIVE_PROJECT_GOVERNED_SESSION_BINDING_REQUIRED');
  expect(openresearchApi.attach).not.toHaveBeenCalled(); expect(openresearchApi.start).not.toHaveBeenCalled();
});
it('keeps an absent request lookup unresolved and does not infer permission to resend', async () => {
  localStorage.setItem('factory-or-pending:alice', 'original-unknown-request');
  vi.mocked(openresearchApi.recover).mockRejectedValue(new ApiError('absent', 404));
  await mount(); await click('核对原请求'); await click('刷新工作区');
  expect(localStorage.getItem('factory-or-pending:alice')).toBe('original-unknown-request');
  expect(openresearchApi.start).not.toHaveBeenCalled(); expect(openresearchApi.create).not.toHaveBeenCalled(); expect(openresearchApi.attach).not.toHaveBeenCalled();
});

async function recoverControlled(value: ResearchSession = { ...session, state: 'prepared' }) {
  const requestId = 'controlled-original-request';
  localStorage.setItem('factory-or-pending:alice', requestId);
  vi.mocked(openresearchApi.projects).mockResolvedValue([group]);
  vi.mocked(openresearchApi.sessions).mockResolvedValue([value]);
  vi.mocked(openresearchApi.recover).mockResolvedValue({ session: value });
  await mountManaged(); await click('核对原请求');
  return requestId;
}
it('retains the rejected original request through reload and explicitly resumes its fixed input once', async () => {
  let current: ResearchSession[] = [];
  vi.mocked(openresearchApi.projects).mockResolvedValue([group]);
  vi.mocked(openresearchApi.sessions).mockImplementation(async () => current);
  vi.mocked(openresearchApi.start).mockImplementationOnce(async () => {
    current = [{ ...session, state: 'prepared' }];
    throw new ApiError('RESEARCH_PLAN_REVIEW_REQUIRED', 409);
  }).mockImplementationOnce(async () => {
    current = [{ ...session, state: 'running', taskId: 'original-task' }];
    return current[0];
  });
  vi.mocked(openresearchApi.recover).mockImplementation(async () => ({ session: current[0] }));
  await mountManaged(); await act(async () => host.querySelector<HTMLButtonElement>('.or-project-card')!.click());
  await input('已批准工作负载', session.workloadPresetId!); await input('研究目标', session.goal);
  await click('确认范围并提交受控会话');
  const original = vi.mocked(openresearchApi.start).mock.calls[0][3];
  expect(host.textContent).toContain('原方案需要审查');
  expect(localStorage.getItem('factory-or-pending:alice')).toBe(original);
  expect(find('继续原受控会话请求')).toBeUndefined();
  await click('核对原请求');
  expect(localStorage.getItem('factory-or-pending:alice')).toBe(original);
  expect(find('确认范围并提交受控会话').disabled).toBe(true);
  expect(host.querySelector<HTMLTextAreaElement>('[aria-label="研究目标"]')!.disabled).toBe(true);
  expect(host.querySelector<HTMLTextAreaElement>('[aria-label="研究目标"]')!.value).toBe(session.goal);
  expect(openresearchApi.start).toHaveBeenCalledTimes(1);
  await act(async () => root.unmount()); root = createRoot(host); await mountManaged();
  expect(find('继续原受控会话请求')).toBeUndefined();
  await click('核对原请求');
  expect(openresearchApi.start).toHaveBeenCalledTimes(1);
  const recoveredBeforeResume = vi.mocked(openresearchApi.recover).mock.calls.length;
  await act(async () => { find('继续原受控会话请求').click(); find('继续原受控会话请求').click(); });
  expect(openresearchApi.recover).toHaveBeenCalledTimes(recoveredBeforeResume + 1);
  expect(openresearchApi.recover).toHaveBeenLastCalledWith(original);
  expect(openresearchApi.start).toHaveBeenCalledTimes(2);
  expect(vi.mocked(openresearchApi.start).mock.calls[1]).toEqual(vi.mocked(openresearchApi.start).mock.calls[0]);
  expect(openresearchApi.start).toHaveBeenLastCalledWith(group.id, session.workloadPresetId, session.goal, original);
  expect(localStorage.getItem('factory-or-pending:alice')).toBeNull();
  await click('任务、证据与取消'); expect(onTask).toHaveBeenCalledWith('original-task');
});
it.each(['unknown', 'dispatch-intent'])('keeps %s admission read-only and retains its original request', async state => {
  const requestId = await recoverControlled({ ...session, state });
  expect(find('继续原受控会话请求')).toBeUndefined();
  expect(find('确认范围并提交受控会话').disabled).toBe(true);
  expect(localStorage.getItem('factory-or-pending:alice')).toBe(requestId);
  await click('核对原会话');
  expect(openresearchApi.reconcile).toHaveBeenCalledWith(group.id, session.id);
  expect(openresearchApi.start).not.toHaveBeenCalled();
  expect(localStorage.getItem('factory-or-pending:alice')).toBe(requestId);
});
it.each(['unknown', 'dispatch-intent'])('rechecks a prepared request and suppresses retry when it has become %s', async state => {
  const requestId = await recoverControlled();
  expect(find('继续原受控会话请求').disabled).toBe(false);
  vi.mocked(openresearchApi.recover).mockResolvedValue({ session: { ...session, state } });
  await click('继续原受控会话请求');
  expect(openresearchApi.recover).toHaveBeenLastCalledWith(requestId);
  expect(openresearchApi.start).not.toHaveBeenCalled();
  expect(find('继续原受控会话请求')).toBeUndefined();
  expect(localStorage.getItem('factory-or-pending:alice')).toBe(requestId);
});
it.each([{ id: 'replacement-session' }, { projectId: 'replacement-project' }, { workloadPresetId: 'replacement-preset' }, { goal: 'replacement goal' }])('does not retry a changed recovered request scope %j', async patch => {
  const requestId = await recoverControlled();
  vi.mocked(openresearchApi.recover).mockResolvedValue({ session: { ...session, state: 'prepared', ...patch } });
  await click('继续原受控会话请求');
  expect(openresearchApi.start).not.toHaveBeenCalled();
  expect(localStorage.getItem('factory-or-pending:alice')).toBe(requestId);
  expect(host.textContent).toContain('INVALID_RESPONSE');
});
it.each([new ApiError('RESEARCH_PLAN_REVIEW_REQUIRED', 409), new ApiError('lost acknowledgement', 0, 'OFFLINE')])('retains the original request after another explicit retry refusal or lost reply', async error => {
  const requestId = await recoverControlled();
  vi.mocked(openresearchApi.start).mockRejectedValue(error);
  await click('继续原受控会话请求');
  expect(openresearchApi.start).toHaveBeenCalledWith(group.id, session.workloadPresetId, session.goal, requestId);
  expect(localStorage.getItem('factory-or-pending:alice')).toBe(requestId);
  expect(find('继续原受控会话请求')).toBeUndefined();
  expect(find('确认范围并提交受控会话').disabled).toBe(true);
  vi.mocked(openresearchApi.recover).mockResolvedValue({ session });
  vi.mocked(openresearchApi.sessions).mockResolvedValue([session]);
  await click('核对原请求');
  expect(openresearchApi.start).toHaveBeenCalledTimes(1);
  expect(find('继续原受控会话请求')).toBeUndefined();
  expect(localStorage.getItem('factory-or-pending:alice')).toBe(requestId);
});
it('does not replace a prepared session with a fresh request when its original pointer is absent', async () => {
  vi.mocked(openresearchApi.projects).mockResolvedValue([group]);
  vi.mocked(openresearchApi.sessions).mockResolvedValue([{ ...session, state: 'prepared' }]);
  await mountManaged(); await act(async () => host.querySelector<HTMLButtonElement>('.or-project-card')!.click());
  await input('已批准工作负载', session.workloadPresetId!); await input('研究目标', 'Another goal');
  expect(find('确认范围并提交受控会话').disabled).toBe(true);
  expect(find('继续原受控会话请求')).toBeUndefined();
  expect(openresearchApi.start).not.toHaveBeenCalled();
});

const usage = { schema: 1, currency: 'USD', amountMicros: 10000, tokenLimit: 2000, provider: 'test-provider', model: 'test-model', adapterId: 'managed-orx-pause-model-v1', adapterRevision: '1', pricingRevision: 'fixture', pricingSha256: hash, perAttemptInputTokens: 1000, perAttemptOutputTokens: 1000, bindingSha256: hash, sha256: hash };
const blockedAuthorization: PlanAuthorization = { executionAllowed: false, reviewRequired: true, nativeToolConfirmationRequired: false, policy: { name: 'admin-review', revision: 'one', fingerprint: hash, review_ttl_seconds: 300, nativeToolConfirmationSeparate: true } };
const managed: ManagedResearchSession = { id: 'ors-managed', projectId: project.id, goal: '检查文本往返', state: 'prepared', taskId: null, executionContract: 'managed-native-attachment-v1', contextSource: 'original-native-project-session', verificationStatus: 'not-live-verified', managedProfileId: 'installed-one', nativeProfileId: 'original-profile', upstreamSessionId: 'native-session-one', planId: 'plan-managed', authorization: blockedAuthorization,
  plan: { id: 'plan-managed', fingerprint: hash, status: 'ready', normalizedGoal: '检查文本往返', materialRefs: [], capabilities: [], missing: [], createdAt: '2026-10-08T00:00:00Z', usageBudget: usage, inputValues: { managedAttachment: { ownerId: owner.id, connectionRef: connection.ref, profile: { harness: 'opencode', model: 'test-model' }, projectId: native.id, sessionId: 'native-session-one', projectIdentityHash: hash, modelRequests: 1, nativeTools: 'disabled' } } } };
async function nativeEntry() { await mount(); await act(async () => host.querySelector<HTMLButtonElement>('.or-project-card')!.click()); }
function managedMocks() {
  let current: ManagedResearchSession | undefined;
  vi.mocked(openresearchApi.projects).mockResolvedValue([project]);
  vi.mocked(openresearchApi.managedProfiles).mockResolvedValue([{ kind: 'managed-connection-probe', modelRequests: 1, nativeTools: 'disabled', nativeResearchAvailable: false, id: 'installed-one', name: '受管连接验证配置', nativeProfileId: 'original-profile', upstreamSessionId: managed.upstreamSessionId, profile: { harness: 'opencode', model: 'test-model' }, executionContract: 'managed-native-attachment-v1', liveEndToEndVerified: false }]);
  vi.mocked(openresearchApi.sessions).mockImplementation(async () => current ? [current] : []);
  vi.spyOn(openresearchApi, 'prepareManaged').mockImplementation(async () => { current = structuredClone(managed); return current; });
  vi.spyOn(openresearchApi, 'startManaged').mockImplementation(async () => { current = { ...managed, state: 'running', taskId: 'original-managed-task' }; return current; });
  vi.spyOn(api, 'planAuthorization').mockResolvedValue(blockedAuthorization);
  vi.spyOn(api, 'planReviews').mockResolvedValue([]);
  return { set: (value: ManagedResearchSession) => { current = value; } };
}
it('keeps prepared managed probes on their existing approval path without a controlled retry', async () => {
  const fixture = managedMocks(); fixture.set(managed);
  localStorage.setItem('factory-or-pending:alice', 'original-managed-prepare');
  vi.mocked(openresearchApi.recover).mockResolvedValue({ session: managed });
  await mountManaged(); await click('核对原请求');
  expect(find('继续原受控会话请求')).toBeUndefined();
  expect(find('确认预算并执行单轮文本探测').disabled).toBe(true);
  expect(localStorage.getItem('factory-or-pending:alice')).toBeNull();
  expect(openresearchApi.start).not.toHaveBeenCalled(); expect(openresearchApi.startManaged).not.toHaveBeenCalled();
});
it('prepares without execution, requests the existing plan review, then starts the original one-turn probe only after approval', async () => {
  managedMocks();
  vi.spyOn(api, 'requestPlanReview').mockImplementation(async (_planId, requestId) => {
    const review = { id: 'review-one', ownerId: owner.id, planId: managed.planId, planDigest: hash, planFingerprint: hash, policyDigest: hash, policyRevision: 'one', requestId, createdAt: '2026-10-08T00:00:00Z', expiresAt: '2099-01-01T00:00:00Z', expired: false, currentPolicy: true, planIntegrityMatches: true, decision: 'pending' as const, approvalEffective: false, reviewerId: null, planSummary: {} };
    vi.mocked(api.planReviews).mockResolvedValue([review]); return review;
  });
  await nativeEntry();
  expect(host.textContent).toContain('多步研究、原生工具循环与研究结果验证尚不可用');
  await input('已安装验证配置', 'installed-one'); await input('文本探测目标', managed.goal); await click('准备单轮连接验证方案');
  expect(openresearchApi.prepareManaged).toHaveBeenCalledWith(project.id, 'installed-one', managed.goal, expect.any(String));
  expect(openresearchApi.startManaged).not.toHaveBeenCalled(); expect(openresearchApi.start).not.toHaveBeenCalled();
  expect(find('确认预算并执行单轮文本探测').disabled).toBe(true);
  expect(host.textContent).toContain('原生工具禁用'); expect(host.textContent).toContain(managed.upstreamSessionId);
  await click('提交方案审查'); expect(api.requestPlanReview).toHaveBeenCalledTimes(1);
  expect(find('确认预算并执行单轮文本探测').disabled).toBe(true);
  vi.mocked(api.planAuthorization).mockResolvedValue({ ...blockedAuthorization, executionAllowed: true });
  await click('刷新授权与审查状态'); expect(find('确认预算并执行单轮文本探测').disabled).toBe(false);
  await act(async () => { find('确认预算并执行单轮文本探测').click(); find('确认预算并执行单轮文本探测').click(); });
  expect(openresearchApi.startManaged).toHaveBeenCalledTimes(1);
  expect(openresearchApi.startManaged).toHaveBeenCalledWith(project.id, expect.objectContaining({ id: managed.id, planId: managed.planId, upstreamSessionId: managed.upstreamSessionId }), expect.any(String));
  await click('任务、证据与取消'); expect(onTask).toHaveBeenCalledWith('original-managed-task');
});
it('preserves an unknown managed start through reload and reads the original request without another start', async () => {
  const fixture = managedMocks(); fixture.set(managed);
  vi.mocked(api.planAuthorization).mockResolvedValue({ ...blockedAuthorization, executionAllowed: true });
  vi.mocked(openresearchApi.startManaged).mockImplementation(async () => { fixture.set({ ...managed, state: 'unknown' }); throw new ApiError('lost', 0, 'OFFLINE'); });
  await nativeEntry(); await click('确认预算并执行单轮文本探测');
  const requestId = vi.mocked(openresearchApi.startManaged).mock.calls[0][2];
  expect(localStorage.getItem('factory-or-pending:alice')).toBe(requestId);
  await act(async () => root.unmount()); root = createRoot(host);
  vi.mocked(openresearchApi.recover).mockResolvedValue({ session: { ...managed, state: 'unknown' } }); await mount(); await click('核对原请求');
  expect(openresearchApi.recover).toHaveBeenCalledWith(requestId); expect(openresearchApi.startManaged).toHaveBeenCalledTimes(1);
  expect(find('确认预算并执行单轮文本探测')).toBeUndefined(); expect(host.textContent).toContain('不会重发探测');
});
it('fresh authorization revocation prevents a managed start even after the button was ready', async () => {
  const fixture = managedMocks(); fixture.set(managed);
  vi.mocked(api.planAuthorization).mockResolvedValue({ ...blockedAuthorization, executionAllowed: true });
  await nativeEntry(); expect(find('确认预算并执行单轮文本探测').disabled).toBe(false);
  vi.mocked(api.planAuthorization).mockResolvedValue(blockedAuthorization); await click('确认预算并执行单轮文本探测');
  expect(openresearchApi.startManaged).not.toHaveBeenCalled(); expect(host.textContent).toContain('PLAN_AUTHORIZATION_REQUIRED');
});
it('checks managed session original plan/session and rejects increased provider or native tool capability', () => {
  expect(researchSession(managed, project.id)).toMatchObject({ executionContract: 'managed-native-attachment-v1' });
  for (const patch of [{ sessionId: 'replacement' }, { modelRequests: 2 }, { nativeTools: 'enabled' }]) {
    const changed = structuredClone(managed); Object.assign(changed.plan.inputValues!.managedAttachment!, patch);
    expect(() => researchSession(changed, project.id)).toThrow();
  }
});

it('does not admit a prepared probe whose owner binding or budget cannot be verified', async () => {
  const fixture = managedMocks(); const changed = structuredClone(managed);
  Object.assign(changed.plan.inputValues!.managedAttachment!, { ownerId: 'bob' }); changed.plan.usageBudget = undefined;
  fixture.set(changed); vi.mocked(api.planAuthorization).mockResolvedValue({ ...blockedAuthorization, executionAllowed: true });
  await nativeEntry(); expect(find('确认预算并执行单轮文本探测').disabled).toBe(true);
  expect(host.textContent).toContain('原项目与方案绑定不匹配'); expect(host.textContent).toContain('缺少可核对的提供商预算');
  expect(openresearchApi.startManaged).not.toHaveBeenCalled();
});
it('defaults to ordinary actual OpenResearch sessions and keeps managed setup opt-in', async () => {
  await act(async () => root.render(createElement(OpenResearchWorkspace, { ownerId: owner.id, onTask, onResources: vi.fn(), onCatalog: vi.fn() })));
  expect(host.textContent).toContain('普通模式 · 选择运行位置，使用自己的模型'); expect(host.textContent).not.toContain('OpenCode'); expect(openresearchApi.projects).not.toHaveBeenCalled(); expect(openresearchApi.managedProfiles).not.toHaveBeenCalled();
  await click('切换受管模式（可选）'); expect(openresearchApi.projects).toHaveBeenCalledTimes(1);
  await click('切换普通模式'); expect(host.textContent).toContain('普通模式 · 选择运行位置，使用自己的模型'); expect(openresearchApi.start).not.toHaveBeenCalled();
});
