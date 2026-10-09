// @vitest-environment happy-dom
import { webcrypto } from 'node:crypto';
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { PersonalAgentSessions } from '../web/PersonalAgentSessions.js';
import { NativeCommandResult } from '../web/NativeCommandResult.js';
import { api, ApiError } from '../web/api.js';
import { personalAgentApi, checkResearchContinuation, PERSONAL_CONTRACT, ORX_PERSONAL_PROVIDER, type PersonalSession, type PersonalRecovery } from '../web/personalAgentApi.js';
import { personalRemoteApi, type PersonalRemote } from '../web/personalRemoteApi.js';
import type { FactoryJob, Plan, UserConnection, JobDetail } from '../web/models.js';
vi.mock('../web/PersonalRemotes.js', () => ({ PersonalRemotes: () => createElement('p', {}, 'Saved service configuration') }));
const owner = { id: 'native-owner', name: 'Owner', role: 'user' as const };
const pin = { ref: 'owner-binding', ownerId: owner.id, registrationRef: 'owner-registration', kind: 'orx', taskId: null, available: true, status: 'active', fingerprint: 'a'.repeat(64), capabilities: ['session:read', 'session:prompt', 'session:interrupt'] } as UserConnection;
const session: PersonalSession = { id: 'factory-session', namespace: 'native-openresearch', executionContract: PERSONAL_CONTRACT, connectionRef: pin.ref, connectionPin: pin, bindingStatus: 'active', nativeProjectId: 'original-project', nativeSessionId: 'original-session', upstreamOrxProjectId: 'original-project', factoryIdentity: null, activeRequestId: null, state: 'ready', observation: null, modelCredentialCustody: 'remote', budgetEnforcement: 'advisory', stopVerified: false, liveEndToEndVerified: false };
const plan = { id: 'original-plan', fingerprint: 'p'.repeat(64), status: 'ready', inputValues: { executionContract: PERSONAL_CONTRACT, action: 'prompt', factorySessionId: session.id, nativeSessionId: session.nativeSessionId!, nativeProjectId: session.nativeProjectId, connectionPin: JSON.stringify(pin) } } as unknown as Plan;
const job = { id: 'original-task', planId: plan.id, ownerId: owner.id, status: 'completed', input: { mode: 'personal-command', topic: 'Controlled goal' } } as FactoryJob;
const identity = { planId: plan.id, taskId: job.id, nativeRunId: 'original-run', executionContract: PERSONAL_CONTRACT } as const;
const storage = `factory-personal-command:${owner.id}:native-openresearch`;
const observed: PersonalSession = { ...session, state: 'result_observed', observation: { messages: [{ id: 'answer', role: 'assistant', completed: true, usageProvenance: 'unavailable', events: [{ type: 'text', text: '<script>Only a controlled protocol result</script>' }] }], sessionId: session.nativeSessionId!, projectId: session.nativeProjectId, observedAt: '', provenance: 'remote-reported', trustedMetering: false } };
function recovery(requestId: string, extra: Partial<PersonalRecovery> = {}): PersonalRecovery { return { requestId, plan, authorization: {} as PersonalRecovery['authorization'], job, nativeRunId: identity.nativeRunId, receipt: { requestId, action: 'prompt', state: 'acknowledged', session, factoryIdentity: identity }, ...extra }; }
let host: HTMLDivElement; let root: Root;
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); vi.stubGlobal('crypto', webcrypto); localStorage.clear(); sessionStorage.clear();
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  vi.spyOn(api, 'session').mockResolvedValue(owner); vi.spyOn(api, 'userConnections').mockResolvedValue([pin]);
  vi.spyOn(personalRemoteApi, 'list').mockResolvedValue([{ registrationRef: pin.registrationRef, providerId: ORX_PERSONAL_PROVIDER } as PersonalRemote]);
  vi.spyOn(personalAgentApi, 'capabilities').mockResolvedValue({ executionContract: PERSONAL_CONTRACT, nativeQueue: true, ownerSubmit: '/api/factory/personal-agent/commands/submit', modelConfiguration: 'remote-configured-model', factoryBYOKForwarded: false });
  vi.spyOn(personalAgentApi, 'project').mockResolvedValue({ namespace: session.namespace, executionContract: PERSONAL_CONTRACT, nativeProjectId: session.nativeProjectId, connectionPin: { ref: pin.ref }, upstreamOrxProjectId: session.nativeProjectId, budgetEnforcement: 'advisory', modelCredentialCustody: 'remote', stopGuarantee: 'unverified' });
  vi.spyOn(personalAgentApi, 'sessions').mockResolvedValue([]); vi.spyOn(personalAgentApi, 'session').mockResolvedValue(session);
  vi.spyOn(personalAgentApi, 'nativeSessions').mockResolvedValue({ nativeProjectId: session.nativeProjectId, namespace: session.namespace, executionContract: PERSONAL_CONTRACT, connectionPin: { ref: pin.ref }, sessions: [{ nativeProjectId: session.nativeProjectId, nativeSessionId: session.nativeSessionId!, title: 'Existing project session' }] });
  vi.spyOn(personalAgentApi, 'attach').mockImplementation(async input => ({ requestId: input.requestId, action: 'attach', state: 'acknowledged', factoryIdentity: null, result: { nativeProjectId: session.nativeProjectId, nativeSessionId: session.nativeSessionId!, status: 'attached_read_only' }, session }));
  vi.spyOn(personalAgentApi, 'submit').mockResolvedValue(job); vi.spyOn(personalAgentApi, 'prepare'); vi.spyOn(personalAgentApi, 'start');
  vi.spyOn(personalAgentApi, 'recover').mockImplementation(async id => recovery(id));
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const button = (text: string) => [...host.querySelectorAll('button')].find(b => b.textContent === text)!;
async function mount() { await act(async () => root.render(createElement(PersonalAgentSessions, { ownerId: owner.id, namespace: session.namespace }))); }
async function choose() { await act(async () => button('选择会话 original-session').click()); }
async function fill(text = 'Controlled research goal') { await act(async () => { const field = host.querySelector('textarea')!; Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(field, text); field.dispatchEvent(new Event('input', { bubbles: true })); }); }
it('selects an existing native session read-only and submits the owner goal once without admin, prepare or separate start', async () => {
  await mount(); expect(personalAgentApi.nativeSessions).toHaveBeenCalledTimes(1); await choose(); await fill();
  await act(async () => { button('提交研究目标').click(); button('提交研究目标').click(); });
  expect(personalAgentApi.submit).toHaveBeenCalledTimes(1); expect(personalAgentApi.submit).toHaveBeenCalledWith(expect.objectContaining({ action: 'prompt', sessionId: session.id, text: 'Controlled research goal' }));
  expect(personalAgentApi.prepare).not.toHaveBeenCalled(); expect(personalAgentApi.start).not.toHaveBeenCalled(); expect(host.querySelector('dialog,input[type=checkbox]')).toBeNull();
  expect(localStorage.getItem(storage)).not.toContain('Controlled research goal'); expect(localStorage.getItem(storage)).toContain('submitAttempt');
});
it('lost submit survives remount; a prepared plan without a job only allows original GET, never replay', async () => {
  vi.mocked(personalAgentApi.submit).mockRejectedValue(new Error('sensitive server error')); await mount(); await choose(); await fill(); await act(async () => button('提交研究目标').click());
  const original = vi.mocked(personalAgentApi.submit).mock.calls[0][0].requestId;
  await act(async () => root.render(createElement('p'))); vi.mocked(personalAgentApi.recover).mockResolvedValue(recovery(original, { job: null, receipt: null, nativeRunId: null })); await mount(); await act(async () => button('核对原会话命令').click());
  expect(personalAgentApi.recover).toHaveBeenCalledWith(original); expect(host.textContent).toContain('尚未找到任务不代表没有启动'); expect(host.querySelector('dialog')).toBeNull(); expect(personalAgentApi.submit).toHaveBeenCalledTimes(1); expect(personalAgentApi.start).not.toHaveBeenCalled(); expect(host.textContent).not.toContain('sensitive server error');
});
it('UNKNOWN remains frozen even when a similar transcript and completed local task exist', async () => {
  localStorage.setItem(storage, JSON.stringify({ requestId: 'original-request', submitAttempt: true })); vi.mocked(personalAgentApi.recover).mockResolvedValue(recovery('original-request', { receipt: { requestId: 'original-request', action: 'prompt', state: 'ack_unknown', session: { ...observed, activeRequestId: 'original-request' }, factoryIdentity: identity } }));
  await mount(); await act(async () => button('核对原会话命令').click());
  expect(host.textContent).toContain('原远程命令确认未知'); expect(localStorage.getItem(storage)).toContain('original-request'); expect(personalAgentApi.submit).not.toHaveBeenCalled(); expect(button('提交研究目标').disabled).toBe(true);
});
it('interrupt is an explicit owner command and never claims confirmed process stop', async () => {
  await mount(); await choose(); await act(async () => button('请求中断').click());
  expect(personalAgentApi.submit).toHaveBeenCalledWith(expect.objectContaining({ action: 'interrupt', sessionId: session.id })); expect(host.textContent).toContain('停止状态以服务端记录为准'); expect(personalAgentApi.start).not.toHaveBeenCalled();
});
it('restores the authorized selected native session after refresh without attach or command side effects', async () => {
  vi.mocked(personalAgentApi.sessions).mockResolvedValue([observed]); localStorage.setItem(`factory-personal-session:${owner.id}:native-openresearch`, session.id); await mount();
  expect(host.textContent).toContain('原生会话 ID：original-session'); expect(personalAgentApi.attach).not.toHaveBeenCalled(); expect(personalAgentApi.submit).not.toHaveBeenCalled();
});
it('job results read only the exact original receipt/session and render remote text safely', async () => {
  vi.mocked(personalAgentApi.session).mockResolvedValue(observed);
  const detail = { job, events: [], artifacts: [], snapshot: { content: JSON.stringify({ requestId: 'original-request', executionContract: PERSONAL_CONTRACT, action: 'prompt', factoryIdentity: identity }) } } as JobDetail;
  await act(async () => root.render(createElement(NativeCommandResult, { detail })));
  expect(host.textContent).toContain('<script>Only a controlled protocol result</script>'); expect(host.querySelector('script')).toBeNull(); expect(personalAgentApi.submit).not.toHaveBeenCalled(); expect(personalAgentApi.recover).toHaveBeenCalledWith('original-request', expect.any(AbortSignal));
  vi.mocked(personalAgentApi.recover).mockResolvedValue(recovery('changed-request', { job: { ...job, id: 'foreign-task' } }));
  const next = { ...detail, job: { ...job, id: 'changed-task' }, snapshot: { content: JSON.stringify({ requestId: 'changed-request', executionContract: PERSONAL_CONTRACT, action: 'prompt', factoryIdentity: { ...identity, taskId: 'changed-task' } }) } };
  await act(async () => root.render(createElement(NativeCommandResult, { detail: next })));
  expect(host.textContent).not.toContain('Only a controlled protocol result'); expect(host.textContent).toContain('暂时无法读取原生会话结果');
});
it('new-session journey waits for its acknowledged native ID, then submits the authorized goal once with a distinct stable request', async () => {
  vi.mocked(api.userConnections).mockResolvedValue([{ ...pin, capabilities: [...pin.capabilities, 'session:create'] }]);
  vi.mocked(personalAgentApi.project).mockResolvedValue({ namespace: session.namespace, executionContract: PERSONAL_CONTRACT, nativeProjectId: session.nativeProjectId, connectionPin: { ref: pin.ref }, upstreamOrxProjectId: session.nativeProjectId, budgetEnforcement: 'advisory', modelCredentialCustody: 'remote', stopGuarantee: 'unverified', sessionCreationSupported: true });
  const createPlan = { ...plan, inputValues: { ...plan.inputValues!, action: 'create' } };
  vi.mocked(personalAgentApi.recover).mockImplementation(async id => ({ ...recovery(id), plan: createPlan, receipt: { requestId: id, action: 'create', state: 'acknowledged', session: { ...session, factoryIdentity: identity }, factoryIdentity: identity } }));
  await mount(); await act(async () => { const field = host.querySelector<HTMLTextAreaElement>('[aria-label="新会话研究目标"]')!; Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(field, 'New bounded goal'); field.dispatchEvent(new Event('input', { bubbles: true })); });
  await act(async () => { button('创建会话并提交研究目标').click(); button('创建会话并提交研究目标').click(); });
  expect(personalAgentApi.submit).toHaveBeenCalledTimes(1); expect(personalAgentApi.submit).toHaveBeenNthCalledWith(1, expect.objectContaining({ action: 'create', nativeProjectId: session.nativeProjectId }));
  await act(async () => button('核对原会话命令').click());
  expect(personalAgentApi.submit).toHaveBeenCalledTimes(2); expect(personalAgentApi.submit).toHaveBeenNthCalledWith(2, expect.objectContaining({ action: 'prompt', sessionId: session.id, text: 'New bounded goal' }));
  const first = vi.mocked(personalAgentApi.submit).mock.calls[0][0].requestId; const second = vi.mocked(personalAgentApi.submit).mock.calls[1][0].requestId;
  expect(first).toMatch(/:create$/); expect(second).toBe(first.replace(/:create$/, ':prompt')); expect(localStorage.getItem(storage)).not.toContain('New bounded goal');
});
it('reload after session creation recovers the original session without inventing or automatically sending a missing goal', async () => {
  const createPlan = { ...plan, inputValues: { ...plan.inputValues!, action: 'create' } };
  localStorage.setItem(storage, JSON.stringify({ requestId: 'original-create', planId: plan.id, submitAttempt: true }));
  vi.mocked(personalAgentApi.recover).mockResolvedValue({ ...recovery('original-create'), plan: createPlan, receipt: { requestId: 'original-create', action: 'create', state: 'acknowledged', session: { ...session, factoryIdentity: identity }, factoryIdentity: identity } });
  await mount(); await act(async () => button('核对原会话命令').click());
  expect(host.textContent).toContain('研究目标尚未发送'); expect(personalAgentApi.submit).not.toHaveBeenCalled(); expect(localStorage.getItem(storage)).toBeNull();
});

async function journey() {
  vi.mocked(api.userConnections).mockResolvedValue([{ ...pin, capabilities: [...pin.capabilities, 'session:create'] }]);
  vi.mocked(personalAgentApi.project).mockResolvedValue({ namespace: session.namespace, executionContract: PERSONAL_CONTRACT, nativeProjectId: session.nativeProjectId, connectionPin: { ref: pin.ref }, upstreamOrxProjectId: session.nativeProjectId, budgetEnforcement: 'advisory', modelCredentialCustody: 'remote', stopGuarantee: 'unverified', sessionCreationSupported: true });
  await act(async () => root.render(createElement(PersonalAgentSessions, { ownerId: owner.id, namespace: session.namespace, researchJourney: true, onTask: () => undefined })));
}
async function goal(text: string, label = '研究目标') { await act(async () => { const field = host.querySelector<HTMLTextAreaElement>(`[aria-label="${label}"]`)!; Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(field, text); field.dispatchEvent(new Event('input', { bubbles: true })); }); }
it('ordinary expired history keeps results and submits one explicit followup without technical renewal steps', async () => {
  const expired = { ...observed, bindingStatus: 'expired' };
  vi.mocked(personalAgentApi.sessions).mockResolvedValue([expired]); vi.mocked(personalAgentApi.session).mockResolvedValue(expired);
  localStorage.setItem(`factory-personal-session:${owner.id}:native-openresearch`, expired.id);
  await journey(); await goal('Explicit new followup across expiration');
  expect(button('继续研究').disabled).toBe(false);
  await act(async () => { button('继续研究').click(); button('继续研究').click(); });
  expect(personalAgentApi.submit).toHaveBeenCalledTimes(1);
  expect(personalAgentApi.submit).toHaveBeenCalledWith(expect.objectContaining({ action: 'prompt', sessionId: expired.id, text: 'Explicit new followup across expiration' }), owner.id);
  expect(host.querySelector('[aria-label="研究结果"]')!.textContent).toContain('Only a controlled protocol result');
  expect(host.querySelector('dialog')).toBeNull();
});
it.each(['ORX_LEASE_EXPLICIT_SELECTION_REQUIRED', 'REMOTE_CREDENTIAL_UNAVAILABLE', 'ORX_LEASE_PRE_ADMISSION_HEALTH_CHECK_FAILED'])('known pre-admission409 %s unlocks selection and keeps the goal without recovery or replay', async code => {
  const expired = { ...observed, bindingStatus: 'expired' };
  vi.mocked(personalAgentApi.sessions).mockResolvedValue([expired]); vi.mocked(personalAgentApi.session).mockResolvedValue(expired);
  localStorage.setItem(`factory-personal-session:${owner.id}:native-openresearch`, expired.id);
  const setupKey = `factory-orx-project-selection:${owner.id}:retained`;
  localStorage.setItem(setupKey, JSON.stringify(['original-configuration-evidence']));
  vi.mocked(personalAgentApi.submit).mockRejectedValue(new ApiError('pre-admission lease rejection', 409, code));
  await journey(); await goal('Preserve this authorized draft after lease rejection');
  await act(async () => button('继续研究').click());
  expect(personalAgentApi.submit).toHaveBeenCalledTimes(1);
  expect(personalAgentApi.recover).not.toHaveBeenCalled();
  expect(localStorage.getItem(storage)).toBeNull();
  expect(localStorage.getItem(setupKey)).toBe(JSON.stringify(['original-configuration-evidence']));
  expect(host.textContent).toContain('original-configuration-evidence');
  expect(host.querySelector<HTMLTextAreaElement>('[aria-label="研究目标"]')!.value).toBe('Preserve this authorized draft after lease rejection');
  expect(host.textContent).toContain('研究未提交');
  expect(host.querySelector('.research-setup')).not.toBeNull();
  expect(host.querySelector('[aria-label="研究结果"]')!.textContent).toContain('Only a controlled protocol result');
  expect(button('继续研究').disabled).toBe(false);
});
it('a temporary pre-admission health failure allows only an explicit new retry with the retained goal', async () => {
  const expired = { ...observed, bindingStatus: 'expired' };
  vi.mocked(personalAgentApi.sessions).mockResolvedValue([expired]); vi.mocked(personalAgentApi.session).mockResolvedValue(expired);
  localStorage.setItem(`factory-personal-session:${owner.id}:native-openresearch`, expired.id);
  vi.mocked(personalAgentApi.submit).mockRejectedValueOnce(new ApiError('temporary health failure', 409, 'ORX_LEASE_PRE_ADMISSION_HEALTH_CHECK_FAILED')).mockResolvedValue(job);
  await journey(); await goal('Retain this goal through a temporary health outage');
  await act(async () => button('继续研究').click());
  const failedRequest = vi.mocked(personalAgentApi.submit).mock.calls[0][0].requestId;
  expect(localStorage.getItem(storage)).toBeNull(); expect(button('继续研究').disabled).toBe(false);
  expect(host.textContent).toContain('连接健康检查暂时失败');
  expect(personalAgentApi.recover).not.toHaveBeenCalled(); expect(personalAgentApi.submit).toHaveBeenCalledTimes(1);
  await act(async () => button('继续研究').click());
  expect(personalAgentApi.submit).toHaveBeenCalledTimes(2);
  const next = vi.mocked(personalAgentApi.submit).mock.calls[1][0];
  expect(next.requestId).not.toBe(failedRequest);
  expect(next).toMatchObject({ action: 'prompt', sessionId: expired.id, text: 'Retain this goal through a temporary health outage' });
  expect(vi.mocked(personalAgentApi.recover).mock.calls.some(call => call[0] === failedRequest)).toBe(false);
});
it.each(['IDEMPOTENCY_CONFLICT', 'REMOTE_VERIFICATION_FAILED'])('an ambiguous409 %s retains the original pending pointer and never enables a replay', async code => {
  const expired = { ...observed, bindingStatus: 'expired' };
  vi.mocked(personalAgentApi.sessions).mockResolvedValue([expired]); vi.mocked(personalAgentApi.session).mockResolvedValue(expired);
  localStorage.setItem(`factory-personal-session:${owner.id}:native-openresearch`, expired.id);
  vi.mocked(personalAgentApi.submit).mockRejectedValue(new ApiError('ambiguous conflict', 409, code));
  await journey(); await goal('Retain the original ambiguous request');
  await act(async () => button('继续研究').click());
  expect(personalAgentApi.submit).toHaveBeenCalledTimes(1);
  expect(localStorage.getItem(storage)).toContain('submitAttempt');
  expect(button('继续研究').disabled).toBe(true);
  expect(host.querySelector('.research-setup')).toBeNull();
});
it('one continue-viewing operation preserves an unresolved original request without sending another prompt', async () => {
  const expired = { ...observed, bindingStatus: 'expired', activeRequestId: 'unknown-original', state: 'ack_unknown' };
  vi.mocked(personalAgentApi.sessions).mockResolvedValue([expired]); vi.mocked(personalAgentApi.session).mockResolvedValue(expired);
  localStorage.setItem(`factory-personal-session:${owner.id}:native-openresearch`, expired.id);
  const resume = vi.spyOn(personalAgentApi, 'continueResearch').mockResolvedValue({ state: 'waiting', session: expired });
  await journey(); await act(async () => button('继续查看研究').click());
  expect(resume).toHaveBeenCalledWith(expired); expect(personalAgentApi.submit).not.toHaveBeenCalled();
  expect(button('继续研究').disabled).toBe(true); expect(host.textContent).toContain('不会重发研究请求');
});
it('expired restored history does not vanish or perform background connection renewal', async () => {
  const expired = { ...observed, bindingStatus: 'expired' };
  const refresh = vi.spyOn(personalAgentApi, 'refreshConnection');
  vi.mocked(personalAgentApi.sessions).mockResolvedValue([expired]); vi.mocked(personalAgentApi.session).mockResolvedValue(expired);
  localStorage.setItem(`factory-personal-session:${owner.id}:native-openresearch`, expired.id);
  await journey();
  expect(host.textContent).toContain('Only a controlled protocol result'); expect(button('继续查看研究').disabled).toBe(false);
  expect(refresh).not.toHaveBeenCalled(); expect(personalAgentApi.submit).not.toHaveBeenCalled();
});
it('rejects continuation that changes native identity, original task or enlarges capabilities', () => {
  const value = { state: 'ready' as const, session: observed };
  expect(checkResearchContinuation(value, observed)).toEqual(value);
  for (const changed of [{ ...observed, nativeSessionId: 'other' }, { ...observed, factoryIdentity: identity }, { ...observed, connectionPin: { ...pin, capabilities: [...pin.capabilities, 'project:create'] } }]) expect(() => checkResearchContinuation({ ...value, session: changed }, observed)).toThrow();
});
it('ordinary journey starts from one goal action, retains material provenance and hides technical output in details', async () => {
  const createPlan = { ...plan, inputValues: { ...plan.inputValues!, action: 'create' } };
  vi.mocked(personalAgentApi.recover).mockImplementation(async id => ({ ...recovery(id), plan: createPlan, receipt: { requestId: id, action: 'create', state: 'acknowledged', session: { ...session, factoryIdentity: identity }, factoryIdentity: identity } }));
  await journey(); await goal('Compare the supplied papers'); await goal('https://synthetic.example/paper', '补充材料');
  await act(async () => { button('开始研究').click(); button('开始研究').click(); });
  expect(personalAgentApi.submit).toHaveBeenCalledTimes(1);
  expect(personalAgentApi.submit).toHaveBeenNthCalledWith(1, expect.objectContaining({ action: 'create', title: 'Compare the supplied papers' }), owner.id);
  await act(async () => button('核对研究请求').click());
  expect(personalAgentApi.submit).toHaveBeenNthCalledWith(2, expect.objectContaining({ action: 'prompt', text: 'Compare the supplied papers\n\n补充材料（用户提供）：\nhttps://synthetic.example/paper' }), owner.id);
  expect(host.querySelector('dialog')).toBeNull(); expect(personalAgentApi.prepare).not.toHaveBeenCalled();
  expect(button('查看任务详情').closest('details')?.open).toBe(false);
});
it('ordinary journey keeps owner draft on navigation/reload and unknown requests only permit original reads', async () => {
  vi.mocked(personalAgentApi.submit).mockRejectedValue(new Error('private upstream secret'));
  await journey(); await goal('Keep my unsent draft'); await act(async () => button('开始研究').click());
  const id = vi.mocked(personalAgentApi.submit).mock.calls[0][0].requestId;
  await act(async () => root.render(createElement('p')));
  vi.mocked(personalAgentApi.recover).mockResolvedValue(recovery(id, { receipt: null, job: null, nativeRunId: null }));
  await journey(); expect(host.querySelector<HTMLTextAreaElement>('[aria-label="研究目标"]')!.value).toBe('Keep my unsent draft');
  await act(async () => button('核对研究请求').click());
  expect(personalAgentApi.submit).toHaveBeenCalledTimes(1); expect(button('开始研究').disabled).toBe(true); expect(host.textContent).not.toContain('private upstream secret');
  expect(localStorage.getItem(storage)).toContain(id);
});
it('ordinary journey continues the restored original session and only displays actual remote answers', async () => {
  vi.mocked(personalAgentApi.sessions).mockResolvedValue([observed]); vi.mocked(personalAgentApi.session).mockResolvedValue(observed);
  localStorage.setItem(`factory-personal-session:${owner.id}:native-openresearch`, session.id);
  await journey(); expect(host.querySelector('[aria-label="研究结果"]')!.textContent).toContain('Only a controlled protocol result'); expect(host.querySelector('script')).toBeNull();
  await goal('Continue with limitations'); await act(async () => button('继续研究').click());
  expect(personalAgentApi.submit).toHaveBeenCalledWith(expect.objectContaining({ action: 'prompt', sessionId: session.id, text: 'Continue with limitations' }), owner.id);
  expect(vi.mocked(personalAgentApi.submit).mock.calls.some(([input]) => input.action === 'create')).toBe(false);
});
it('ordinary journey rejects stale-account and definitive failed starts while preserving only the right owner draft', async () => {
  await journey(); await goal('Private owner draft'); vi.mocked(api.session).mockResolvedValue({ ...owner, id: 'another-owner' });
  await act(async () => button('开始研究').click()); expect(personalAgentApi.submit).not.toHaveBeenCalled();
  expect(host.querySelector<HTMLTextAreaElement>('[aria-label="研究目标"]')!.value).toBe(''); expect(host.textContent).toContain('登录账户已变化');
});

it('an expired stale-tab login clears the visible research draft before any intent is dispatched', async () => {
  await journey(); await goal('Private unsent text'); vi.mocked(api.session).mockRejectedValue(new ApiError('Expired', 401));
  await act(async () => button('开始研究').click()); expect(personalAgentApi.submit).not.toHaveBeenCalled();
  expect(host.querySelector<HTMLTextAreaElement>('[aria-label="研究目标"]')!.value).toBe('');
  expect(host.textContent).toContain('登录账户已变化');
});
it('keeps the authorized goal while native creation is still running with a provisional unknown receipt', async () => {
  const createPlan = { ...plan, inputValues: { ...plan.inputValues!, action: 'create' } };
  let done = false;
  vi.mocked(personalAgentApi.recover).mockImplementation(async id => ({ ...recovery(id), plan: createPlan, job: { ...job, status: done ? 'completed' : 'running' }, receipt: { requestId: id, action: 'create', state: done ? 'acknowledged' : 'ack_unknown', session: { ...session, nativeSessionId: done ? session.nativeSessionId : null, factoryIdentity: identity }, factoryIdentity: identity } }));
  await journey(); await goal('Authorized goal after creation'); await act(async () => button('开始研究').click());
  await act(async () => button('核对研究请求').click()); expect(personalAgentApi.submit).toHaveBeenCalledTimes(1);
  expect(host.textContent).toContain('正在等待原命令的明确回执'); done = true;
  await act(async () => button('核对研究请求').click());
  expect(personalAgentApi.submit).toHaveBeenNthCalledWith(2, expect.objectContaining({ action: 'prompt', text: 'Authorized goal after creation' }), owner.id);
});
it('terminal native execution with an unresolved Factory effect stops follow-up and never invents an acknowledgement', async () => {
  const createPlan = { ...plan, inputValues: { ...plan.inputValues!, action: 'create' } };
  let acknowledged = false;
  vi.mocked(personalAgentApi.recover).mockImplementation(async id => ({ ...recovery(id), plan: createPlan, nativeStatus: 'completed', job: { ...job, status: 'unknown' } as unknown as FactoryJob, receipt: { requestId: id, action: 'create', state: acknowledged ? 'acknowledged' : 'ack_unknown', session: { ...session, nativeSessionId: acknowledged ? session.nativeSessionId : null, factoryIdentity: identity }, factoryIdentity: identity } }));
  await journey(); await goal('Original authorized goal'); await act(async () => button('开始研究').click()); await act(async () => button('核对研究请求').click());
  expect(host.textContent).toContain('原远程命令确认未知'); acknowledged = true; await act(async () => button('核对研究请求').click());
  expect(personalAgentApi.submit).toHaveBeenCalledTimes(1); expect(host.textContent).toContain('研究目标尚未发送');
});
