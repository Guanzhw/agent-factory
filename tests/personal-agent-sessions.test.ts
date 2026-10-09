// @vitest-environment happy-dom
import { webcrypto } from 'node:crypto';
import { act, createElement, useEffect } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { PersonalAgentSessions } from '../web/PersonalAgentSessions.js';
import { personalRebindApi } from '../web/personalRebindApi.js';
import { api, ApiError } from '../web/api.js';
import { personalRemoteApi, type PersonalRemote } from '../web/personalRemoteApi.js';
import { PERSONAL_CONTRACT, PERSONAL_PROVIDER, ORX_PERSONAL_PROVIDER, checkAttachment, checkSession, checkPersonalRecovery, personalAgentApi, type PersonalProject, type PersonalSession, type PersonalPrepared, type PersonalRecovery, type PersonalAttachment, type AttachmentReceipt } from '../web/personalAgentApi.js';
import type { FactoryJob, Plan, UserConnection } from '../web/models.js';
vi.mock('../web/PlanReviews.js', () => ({ PlanReviewGate: ({ onAllowed }: { onAllowed: (value: boolean) => void }) => { useEffect(() => { onAllowed(true); return () => onAllowed(false); }, [onAllowed]); return createElement('p', {}, 'Existing plan review gate fixture'); } }));
const owner = { id: 'fixture-owner', name: 'Fixture', role: 'user' as const };
const connection = { ref: 'binding-fixture', registrationRef: 'remote-fixture', ownerId: owner.id, kind: 'environment', status: 'active', available: true, taskId: null, capabilities: ['session:read', 'session:create', 'session:prompt', 'session:interrupt'], fingerprint: 'a'.repeat(64), revision: 'revision-one', version: 1, expiresAt: null, revokedAt: null, createdAt: '', allowedActions: ['inspect'] } as UserConnection;
const remote = { registrationRef: connection.registrationRef, providerId: PERSONAL_PROVIDER } as PersonalRemote;
const project: PersonalProject = { namespace: 'opencode', executionContract: PERSONAL_CONTRACT, nativeProjectId: 'project-fixture', connectionPin: { ref: connection.ref }, upstreamOrxProjectId: null, budgetEnforcement: 'advisory', modelCredentialCustody: 'remote', stopGuarantee: 'unverified' };
const plan = { id: 'plan-fixture', fingerprint: 'fixture-fingerprint', status: 'ready', inputValues: { executionContract: PERSONAL_CONTRACT, action: 'create', nativeProjectId: project.nativeProjectId, connectionPin: JSON.stringify(project.connectionPin), factorySessionId: '', nativeSessionId: '', text: '' }, missing: [] } as unknown as Plan;
const prepared = { executionContract: PERSONAL_CONTRACT, plan, authorization: {}, commandSuccessMeans: 'remote-command-acceptance-only', remoteStopVerified: false, remoteBudgetEnforcement: 'advisory' } as PersonalPrepared;
const job = { id: 'task-fixture', planId: plan.id, ownerId: owner.id, status: 'running' } as FactoryJob;
const session = { connectionPin: connection, bindingStatus: 'active', bindingHistory: [], id: 'session-fixture', namespace: 'opencode', executionContract: PERSONAL_CONTRACT, connectionRef: connection.ref, nativeProjectId: project.nativeProjectId, nativeSessionId: 'native-session-fixture', activeRequestId: null, state: 'ready', upstreamOrxProjectId: null, factoryIdentity: { planId: plan.id, taskId: job.id, nativeRunId: 'run-fixture', executionContract: PERSONAL_CONTRACT }, observation: null, modelCredentialCustody: 'remote', budgetEnforcement: 'advisory', stopVerified: false, liveEndToEndVerified: false } satisfies PersonalSession;
let host: HTMLDivElement; let root: Root;
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); vi.stubGlobal('crypto', webcrypto); localStorage.clear();
  host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host);
  vi.spyOn(api, 'session').mockResolvedValue(owner); vi.spyOn(api, 'userConnections').mockResolvedValue([connection]);
  vi.spyOn(personalRemoteApi, 'list').mockResolvedValue([remote]); vi.spyOn(personalAgentApi, 'capabilities').mockResolvedValue({ executionContract: PERSONAL_CONTRACT, nativeQueue: true });
  vi.spyOn(personalAgentApi, 'project').mockResolvedValue(project); vi.spyOn(personalAgentApi, 'sessions').mockResolvedValue([session]); vi.spyOn(personalAgentApi, 'session').mockResolvedValue(session);
  vi.spyOn(personalAgentApi, 'prepare').mockResolvedValue(prepared); vi.spyOn(personalAgentApi, 'start').mockResolvedValue(job);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function mount(ownerId = owner.id) { await act(async () => root.render(createElement(PersonalAgentSessions, { ownerId, connectionRef: connection.ref }))); }
function button(text: string) { const b = [...host.querySelectorAll('button')].find(b => b.textContent === text); if (!b) throw new Error(`Missing button ${text}`); return b; }
async function click(text: string) { await act(async () => button(text).click()); }
async function fill(label: string, value: string) { await act(async () => { const el = host.querySelector<HTMLInputElement | HTMLTextAreaElement>(`[aria-label="${label}"]`)!; const prototype = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype; Object.getOwnPropertyDescriptor(prototype, 'value')!.set!.call(el, value); el.dispatchEvent(new Event('input', { bubbles: true })); }); }
async function prepareCreate() { await mount(); await fill('新会话标题', 'Private session name'); await click('准备创建会话'); }
async function approveStart() { await act(async () => host.querySelector<HTMLInputElement>('input[type=checkbox]')!.click()); await click('确认启动此命令任务'); }
const key = `factory-personal-command:${owner.id}`;
it('uses separate binding, preparation, review and explicit billing consent; does not start on double prepare', async () => {
  await mount(); await act(async () => { button('准备创建会话').click(); button('准备创建会话').click(); });
  expect(personalAgentApi.prepare).toHaveBeenCalledTimes(1); expect(personalAgentApi.start).not.toHaveBeenCalled();
  expect(button('确认启动此命令任务').disabled).toBe(true); expect(host.textContent).toContain('模型费用由你与远程服务商结算');
  await act(async () => host.querySelector<HTMLInputElement>('input[type=checkbox]')!.click());
  await act(async () => { button('确认启动此命令任务').click(); button('确认启动此命令任务').click(); });
  expect(personalAgentApi.start).toHaveBeenCalledTimes(1); expect(personalAgentApi.start).toHaveBeenCalledWith(plan.id);
  expect(host.textContent).toContain('不证明远程已停止'); expect(localStorage.getItem(key)).not.toContain('private fixture prompt');
});
it('closing review and refreshing never starts or replays a command', async () => {
  await prepareCreate(); await click('关闭审阅'); expect(host.querySelector('[role=dialog]')).toBeNull();
  await click('刷新个人资源'); expect(personalAgentApi.start).not.toHaveBeenCalled(); expect(personalAgentApi.prepare).toHaveBeenCalledTimes(1);
  expect(localStorage.getItem(key)).not.toContain('Private session name'); expect(button('准备创建会话').disabled).toBe(true);
});
it('recovers a lost prepare response read-only with the original request, then requires fresh review', async () => {
  vi.mocked(personalAgentApi.prepare).mockRejectedValue(new Error('private upstream secret'));
  const recover = vi.spyOn(personalAgentApi, 'recover').mockImplementation(async requestId => ({ requestId, plan, authorization: prepared.authorization, job: null, nativeRunId: null, receipt: null }));
  await mount(); await click('准备创建会话'); const original = vi.mocked(personalAgentApi.prepare).mock.calls[0][0].requestId;
  expect(host.textContent).not.toContain('private upstream secret'); await click('核对原会话命令');
  expect(recover).toHaveBeenCalledWith(original); expect(personalAgentApi.prepare).toHaveBeenCalledTimes(1); expect(personalAgentApi.start).not.toHaveBeenCalled(); expect(button('确认启动此命令任务').disabled).toBe(true);
});
it('lost start remains unknown after reload and a missing task never permits replay', async () => {
  localStorage.setItem(key, JSON.stringify({ requestId: 'original-request', planId: plan.id, startPlanId: plan.id }));
  vi.spyOn(personalAgentApi, 'recover').mockResolvedValue({ requestId: 'original-request', plan, authorization: prepared.authorization, job: null, nativeRunId: null, receipt: null });
  await mount(); await click('核对原会话命令'); expect(host.textContent).toContain('尚未找到任务不代表没有启动');
  expect(host.querySelector('[role=dialog]')).toBeNull(); expect(personalAgentApi.start).not.toHaveBeenCalled(); expect(personalAgentApi.prepare).not.toHaveBeenCalled();
});
it('a late prepared response cannot reopen a dismissed or navigated view', async () => {
  let finish!: (value: PersonalPrepared) => void;
  vi.mocked(personalAgentApi.prepare).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  await mount(); await click('准备创建会话');
  await act(async () => root.render(createElement('p', {}, 'Another page'))); await act(async () => finish(prepared));
  expect(host.textContent).toBe('Another page'); expect(personalAgentApi.start).not.toHaveBeenCalled(); expect(localStorage.getItem(key)).toContain('requestId');
});
it('owner changes clear private text and ignore a prior owner’s in-flight preparation', async () => {
  let finish!: (value: PersonalPrepared) => void; vi.mocked(personalAgentApi.prepare).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  await mount(); await fill('新会话标题', 'Private session name'); await click('准备创建会话');
  await mount('other-owner'); await act(async () => finish(prepared));
  expect(host.textContent).not.toContain('Private session name'); expect(host.querySelector('[role=dialog]')).toBeNull(); expect(personalAgentApi.start).not.toHaveBeenCalled(); expect(localStorage.getItem('factory-personal-command:other-owner')).toBeNull();
});
it('renders multi-turn text/tool events escaped and advisory usage while blocking unresolved next turns', async () => {
  const observed: PersonalSession = { ...session, activeRequestId: 'original-prompt', observation: { observedAt: '2026-10-08T00:00:00Z', provenance: 'remote-reported', trustedMetering: false, sessionId: session.nativeSessionId!, projectId: session.nativeProjectId, messages: [{ id: 'message-fixture', role: 'assistant', completed: false, usageProvenance: 'remote-reported', usage: { tokens: { input: 12 }, cost: 0.03 }, events: [{ type: 'text', text: '<script>bad()</script>' }, { type: 'tool', tool: 'synthetic', status: 'running', output: '<img src=x onerror=bad()>' }] }] } };
  vi.mocked(personalAgentApi.session).mockResolvedValue(observed); await mount(); await click(`打开 OpenCode 会话 ${session.nativeSessionId}`);
  expect(host.querySelector('script,img')).toBeNull(); expect(host.textContent).toContain('<script>bad()</script>'); expect(host.textContent).toContain('不是共享账本发票');
  expect(button('准备发送消息').disabled).toBe(true); expect(button('准备尽力中断').disabled).toBe(false);
  await click('准备尽力中断'); expect(personalAgentApi.prepare).toHaveBeenCalledWith(expect.objectContaining({ action: 'interrupt', sessionId: session.id })); expect(personalAgentApi.start).not.toHaveBeenCalled();
});
it('continues an existing native session through a new explicitly prepared prompt', async () => {
  await mount(); await click(`打开 OpenCode 会话 ${session.nativeSessionId}`); await fill('下一轮消息', 'private fixture prompt'); await click('准备发送消息');
  expect(personalAgentApi.prepare).toHaveBeenCalledWith(expect.objectContaining({ action: 'prompt', sessionId: session.id, text: 'private fixture prompt' }));
  expect(localStorage.getItem(key)).not.toContain('private fixture prompt'); await approveStart(); expect(personalAgentApi.start).toHaveBeenCalledTimes(1);
});
it('keeps remote unknown receipt frozen even when the local task completed', async () => {
  localStorage.setItem(key, JSON.stringify({ requestId: 'original-request', planId: plan.id, startPlanId: plan.id }));
  const result: PersonalRecovery = { requestId: 'original-request', plan, authorization: prepared.authorization, job: { ...job, status: 'completed' }, nativeRunId: session.factoryIdentity.nativeRunId, receipt: { requestId: 'original-request', action: 'create', state: 'ack_unknown', session: { ...session, nativeSessionId: null }, factoryIdentity: session.factoryIdentity } };
  vi.spyOn(personalAgentApi, 'recover').mockResolvedValue(result); await mount(); await click('核对原会话命令');
  expect(localStorage.getItem(key)).toContain('original-request'); expect(host.textContent).toContain('原远程命令确认未知'); expect(personalAgentApi.start).not.toHaveBeenCalled();
});
it('does not silently upgrade old read-only registrations', async () => {
  vi.mocked(personalRemoteApi.list).mockResolvedValue([{ ...remote, providerId: 'opencode-serve-v1' }]); await mount();
  expect(personalAgentApi.project).not.toHaveBeenCalled(); expect(host.textContent).toContain('旧只读绑定不会获得执行能力');
});
it('clears a definitively rejected prepare without storing private data', async () => {
  vi.mocked(personalAgentApi.prepare).mockRejectedValue(new ApiError('untrusted detail', 403)); await mount(); await click('准备创建会话');
  expect(localStorage.getItem(key)).toBeNull(); expect(host.textContent).toContain('已明确拒绝'); expect(host.textContent).not.toContain('untrusted detail');
});
it('rejects projections that claim trusted usage or conflate ORX identity', () => {
  expect(checkSession(session)).toEqual(session); expect(() => checkSession({ ...session, upstreamOrxProjectId: 'pretend-orx' } as unknown as PersonalSession)).toThrow();
  expect(() => checkSession({ ...session, stopVerified: true } as unknown as PersonalSession)).toThrow();
});
it('refuses dispatch when durable original-request storage is unavailable', async () => {
  await mount(); const original = localStorage; vi.stubGlobal('localStorage', new Proxy(original, { get(target, key) { return key === 'setItem' ? () => { throw new Error('storage denied'); } : Reflect.get(target, key); } }));
  await click('准备创建会话'); expect(personalAgentApi.prepare).not.toHaveBeenCalled(); expect(personalAgentApi.start).not.toHaveBeenCalled();
});
it('closing during an in-flight start keeps the original recovery identity and cannot reopen review', async () => {
  let finish!: (value: FactoryJob) => void; vi.mocked(personalAgentApi.start).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  await prepareCreate(); await approveStart(); await click('关闭审阅'); await act(async () => finish(job));
  expect(host.querySelector('[role=dialog]')).toBeNull(); expect(JSON.parse(localStorage.getItem(key)!)).toEqual(expect.objectContaining({ planId: plan.id, startPlanId: plan.id })); expect(personalAgentApi.start).toHaveBeenCalledTimes(1);
});

it('Escape dismisses the native review dialog without execution', async () => { await prepareCreate(); await act(async () => host.querySelector('dialog')!.dispatchEvent(new Event('cancel', { bubbles: true, cancelable: true }))); expect(host.querySelector('dialog')).toBeNull(); expect(personalAgentApi.start).not.toHaveBeenCalled(); });

it('rejects recovery that changes the fixed original plan', async () => { localStorage.setItem(key, JSON.stringify({ requestId: 'original-request', planId: plan.id })); vi.spyOn(personalAgentApi, 'recover').mockResolvedValue({ requestId: 'original-request', plan: { ...plan, id: 'different-plan' }, authorization: prepared.authorization, job: null, nativeRunId: null, receipt: null }); await mount(); await click('核对原会话命令'); expect(host.querySelector('dialog')).toBeNull(); expect(JSON.parse(localStorage.getItem(key)!).planId).toBe(plan.id); expect(personalAgentApi.start).not.toHaveBeenCalled(); });
it('rejects mismatched command action, task, native run, project and session during original-request recovery', () => {
  const values = { ...plan.inputValues, action: 'prompt', factorySessionId: session.id, nativeSessionId: session.nativeSessionId! };
  const recovery: PersonalRecovery = { requestId: 'original-request', plan: { ...plan, inputValues: values }, authorization: prepared.authorization, job, nativeRunId: session.factoryIdentity.nativeRunId, receipt: { requestId: 'original-request', action: 'prompt', state: 'acknowledged', session, factoryIdentity: session.factoryIdentity } };
  expect(checkPersonalRecovery(recovery, recovery.requestId, plan.id, plan.id)).toEqual(recovery);
  for (const patch of [{ action: 'interrupt' }, { factoryIdentity: { ...session.factoryIdentity, taskId: 'different-task' } }, { factoryIdentity: { ...session.factoryIdentity, nativeRunId: 'different-run' } }, { session: { ...session, nativeProjectId: 'different-project' } }, { session: { ...session, id: 'different-session' } }, { session: { ...session, nativeSessionId: 'different-native-session' } }]) {
    expect(() => checkPersonalRecovery({ ...recovery, receipt: { ...recovery.receipt, ...patch } } as PersonalRecovery, recovery.requestId, plan.id, plan.id)).toThrow();
  }
  expect(() => checkPersonalRecovery(recovery, recovery.requestId, undefined, 'different-start-plan')).toThrow();
});
it('attaches an existing original native session without creating or prompting it', async () => {
  const attachedSession: PersonalSession = { ...session, factoryIdentity: null };
  vi.spyOn(personalAgentApi, 'nativeSessions').mockResolvedValue({ ...project, sessions: [{ nativeProjectId: project.nativeProjectId, nativeSessionId: session.nativeSessionId!, title: '<img src=x>' }] });
  const attach = vi.spyOn(personalAgentApi, 'attach').mockImplementation(async input => ({ requestId: input.requestId, action: 'attach', state: 'acknowledged', factoryIdentity: null, result: { nativeProjectId: input.nativeProjectId, nativeSessionId: input.nativeSessionId, status: 'attached_read_only' }, session: attachedSession }));
  vi.mocked(personalAgentApi.session).mockResolvedValue(attachedSession);
  await mount(); await click('读取已有原生会话'); expect(host.querySelector('img')).toBeNull();
  await act(async () => { button(`关联原生会话 ${session.nativeSessionId}`).click(); button(`关联原生会话 ${session.nativeSessionId}`).click(); });
  expect(attach).toHaveBeenCalledTimes(1); expect(personalAgentApi.prepare).not.toHaveBeenCalled(); expect(personalAgentApi.start).not.toHaveBeenCalled();
  expect(host.textContent).toContain('只读关联'); expect(host.textContent).toContain(session.nativeSessionId); expect(localStorage.getItem(`factory-personal-attach:${owner.id}:opencode`)).toBeNull();
});
it('recovers a lost native attachment ACK only by its original request and pins', async () => {
  const attachment: PersonalAttachment = { requestId: 'original-attach-request', connectionRef: connection.ref, nativeProjectId: project.nativeProjectId, nativeSessionId: session.nativeSessionId! };
  localStorage.setItem(`factory-personal-attach:${owner.id}:opencode`, JSON.stringify(attachment));
  const recover = vi.spyOn(personalAgentApi, 'recoverAttachment').mockResolvedValue({ requestId: attachment.requestId, action: 'attach', state: 'acknowledged', factoryIdentity: null, result: { nativeProjectId: attachment.nativeProjectId, nativeSessionId: attachment.nativeSessionId, status: 'attached_read_only' }, session: { ...session, factoryIdentity: null } });
  const attach = vi.spyOn(personalAgentApi, 'attach'); await mount(); await click('核对原会话关联');
  expect(recover).toHaveBeenCalledWith(attachment.requestId); expect(attach).not.toHaveBeenCalled(); expect(personalAgentApi.prepare).not.toHaveBeenCalled(); expect(personalAgentApi.start).not.toHaveBeenCalled(); expect(localStorage.getItem(`factory-personal-attach:${owner.id}:opencode`)).toBeNull();
});
it('rejects attachment recovery with any changed namespace, resource, project or original native session', () => {
  const expected: PersonalAttachment = { requestId: 'original-attach-request', connectionRef: connection.ref, nativeProjectId: project.nativeProjectId, nativeSessionId: session.nativeSessionId! };
  const receipt: AttachmentReceipt = { requestId: expected.requestId, action: 'attach', state: 'acknowledged', factoryIdentity: null, result: { nativeProjectId: expected.nativeProjectId, nativeSessionId: expected.nativeSessionId, status: 'attached_read_only' }, session: { ...session, factoryIdentity: null } };
  expect(checkAttachment(receipt, expected, 'opencode')).toEqual(receipt);
  for (const patch of [{ connectionRef: 'different-binding' }, { nativeProjectId: 'different-project' }, { nativeSessionId: 'different-native' }, { namespace: 'native-openresearch', upstreamOrxProjectId: project.nativeProjectId }]) expect(() => checkAttachment({ ...receipt, session: { ...receipt.session, ...patch } } as AttachmentReceipt, expected, 'opencode')).toThrow();
});
it('shows only actual OpenResearch bindings and native IDs; no-template mode cannot create a remote session', async () => {
  const orxConnection = { ...connection, ref: 'orx-binding', registrationRef: 'orx-registration', kind: 'orx' as const };
  const orxProject: PersonalProject = { ...project, namespace: 'native-openresearch', connectionPin: { ref: orxConnection.ref }, upstreamOrxProjectId: project.nativeProjectId, sessionCreationSupported: false };
  const orxSession: PersonalSession = { ...session, namespace: 'native-openresearch', connectionRef: orxConnection.ref, connectionPin: orxConnection, nativeSessionId: 'original-orx-session', upstreamOrxProjectId: project.nativeProjectId, factoryIdentity: null };
  vi.mocked(api.userConnections).mockResolvedValue([connection, orxConnection]); vi.mocked(personalRemoteApi.list).mockResolvedValue([remote, { ...remote, registrationRef: orxConnection.registrationRef, providerId: ORX_PERSONAL_PROVIDER }]);
  vi.mocked(personalAgentApi.project).mockResolvedValue(orxProject); vi.mocked(personalAgentApi.sessions).mockResolvedValue([orxSession]); vi.mocked(personalAgentApi.session).mockResolvedValue(orxSession);
  await act(async () => root.render(createElement(PersonalAgentSessions, { ownerId: owner.id, namespace: 'native-openresearch', connectionRef: orxConnection.ref })));
  expect(host.textContent).not.toContain('OpenCode'); expect(host.querySelector('[aria-label="新会话标题"]')).toBeNull();
  expect([...host.querySelectorAll('option')].map(item => item.value)).toEqual(['', orxConnection.ref]); await click('打开 OpenResearch 会话 original-orx-session');
  expect(host.textContent).toContain('OpenResearch 原生会话 ID：original-orx-session'); expect(personalAgentApi.prepare).not.toHaveBeenCalled();
  expect(checkSession(orxSession)).toEqual(orxSession); expect(() => checkSession({ ...orxSession, upstreamOrxProjectId: null })).toThrow();
});
it('keeps pending commands and private content isolated when changing runtime namespaces', async () => {
  await prepareCreate(); const original = localStorage.getItem(key);
  await act(async () => root.render(createElement(PersonalAgentSessions, { ownerId: owner.id, namespace: 'native-openresearch' })));
  expect(host.querySelector('dialog')).toBeNull(); expect(host.textContent).not.toContain('Private session name'); expect(localStorage.getItem(key)).toBe(original); expect(personalAgentApi.start).not.toHaveBeenCalled();
});
it('retains expired-session history and original results, then continues the same native session after explicit credential-rotation renewal', async () => {
  const rotated = { ...connection, ref: 'rotated-binding', fingerprint: 'b'.repeat(64), revision: 'rotated-revision' };
  const expired: PersonalSession = { ...session, bindingStatus: 'changed' };
  let renewed: PersonalSession | undefined; let finishOldRead!: (value: PersonalSession) => void;
  vi.mocked(api.userConnections).mockResolvedValue([{ ...connection, available: false, status: 'changed' }, rotated]);
  vi.mocked(personalAgentApi.sessions).mockImplementation(async () => [renewed ?? expired]);
  vi.mocked(personalAgentApi.project).mockResolvedValue({ ...project, connectionPin: rotated });
  vi.mocked(personalAgentApi.session).mockImplementation(async () => renewed ?? await new Promise(resolve => { finishOldRead = resolve; }));
  vi.spyOn(personalRebindApi, 'preview').mockResolvedValue({ sessionId: session.id, oldConnectionPin: connection, newConnectionPin: rotated, nativeProjectId: session.nativeProjectId, nativeSessionId: session.nativeSessionId, namespace: session.namespace, activeRequestId: null, canRebind: true, blocker: null, bindingHistory: [] });
  vi.spyOn(personalRebindApi, 'commit').mockImplementation(async input => { renewed = { ...session, connectionRef: rotated.ref, connectionPin: rotated, bindingStatus: 'active', bindingHistory: [{ requestId: input.requestId, changedAt: '2026-10-08T00:00:00Z', oldConnectionPin: connection, newConnectionPin: rotated }] }; return { requestId: input.requestId, action: 'rebind', state: 'acknowledged', factoryIdentity: null, result: { status: 'rebound', oldConnectionPin: connection, newConnectionPin: rotated }, session: renewed }; });
  const attach = vi.spyOn(personalAgentApi, 'attach');
  await mount(); await click(`打开 OpenCode 会话 ${session.nativeSessionId}`);
  expect(host.textContent).toContain('原绑定已到期、撤销或变更'); expect(button('准备发送消息').disabled).toBe(true);
  await act(async () => { const select = host.querySelector<HTMLSelectElement>('[aria-label="新的已验证本人绑定"]')!; Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')!.set!.call(select, rotated.ref); select.dispatchEvent(new Event('change', { bubbles: true })); });
  await click('只读预览原会话续接'); expect(personalRebindApi.commit).not.toHaveBeenCalled(); await click('确认续接同一原生会话');
  await act(async () => finishOldRead(expired));
  expect(host.querySelector('[aria-label="续接原生会话"]')!.textContent).toContain(`原绑定：${rotated.ref}`); expect(host.textContent).not.toContain('原绑定已到期、撤销或变更');
  expect(attach).not.toHaveBeenCalled(); expect(personalAgentApi.prepare).not.toHaveBeenCalled(); expect(personalAgentApi.start).not.toHaveBeenCalled();
  await fill('下一轮消息', 'Continue the original work'); await click('准备发送消息'); expect(personalAgentApi.prepare).toHaveBeenCalledWith(expect.objectContaining({ action: 'prompt', sessionId: session.id }));
});
