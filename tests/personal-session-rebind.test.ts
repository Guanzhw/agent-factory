// @vitest-environment happy-dom
import { webcrypto } from 'node:crypto';
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '../web/api.js';
import { PersonalSessionRebind } from '../web/PersonalSessionRebind.js';
import { PERSONAL_CONTRACT, checkAttachment, checkPersonalRecovery, historicalConnectionMatches, type PersonalSession, type PersonalRecovery } from '../web/personalAgentApi.js';
import { checkRebindPreview, checkRebindReceipt, personalRebindApi, rebindRecovery, type RebindPreview, type RebindReceipt } from '../web/personalRebindApi.js';
import type { UserConnection, Plan, FactoryJob, PlanAuthorization } from '../web/models.js';
const owner = { id: 'fixture-owner', name: 'Fixture', role: 'user' as const };
const old: UserConnection = { ref: 'old-binding', registrationRef: 'old-registration', ownerId: owner.id, kind: 'environment', status: 'active', available: true, taskId: null, capabilities: ['project:read', 'session:read', 'session:prompt', 'session:interrupt'], fingerprint: 'a'.repeat(64), revision: 'old-revision', version: 1, expiresAt: '2025-01-01T00:00:00Z', revokedAt: null, createdAt: '', allowedActions: ['inspect'] };
const next: UserConnection = { ...old, ref: 'new-binding', registrationRef: 'new-registration', fingerprint: 'b'.repeat(64), revision: 'new-revision', expiresAt: '2099-01-01T00:00:00Z' };
const original: PersonalSession = { id: 'original-session', namespace: 'opencode', executionContract: PERSONAL_CONTRACT, nativeProjectId: 'original-project', nativeSessionId: 'original-native-session', connectionRef: old.ref, connectionPin: old, bindingStatus: 'expired', bindingHistory: [], activeRequestId: null, state: 'result_observed', upstreamOrxProjectId: null, factoryIdentity: { planId: 'original-plan', taskId: 'original-task', nativeRunId: 'original-run', executionContract: PERSONAL_CONTRACT }, observation: null, modelCredentialCustody: 'remote', budgetEnforcement: 'advisory', stopVerified: false, liveEndToEndVerified: false };
const preview: RebindPreview = { sessionId: original.id, oldConnectionPin: old, newConnectionPin: next, nativeProjectId: original.nativeProjectId, nativeSessionId: original.nativeSessionId!, namespace: original.namespace, activeRequestId: null, canRebind: true, blocker: null, observation: null, bindingHistory: [] };
function receipt(requestId: string): RebindReceipt { const entry = { requestId, changedAt: '2026-10-08T00:00:00Z', oldConnectionPin: old, newConnectionPin: next }; return { requestId, action: 'rebind', state: 'acknowledged', factoryIdentity: null, result: { status: 'rebound', oldConnectionPin: old, newConnectionPin: next }, session: { ...original, connectionRef: next.ref, connectionPin: next, bindingStatus: 'active', bindingHistory: [entry] } }; }
let host: HTMLDivElement; let root: Root; const rebound = vi.fn(); const pending = vi.fn();
beforeEach(() => { vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); vi.stubGlobal('crypto', webcrypto); localStorage.clear(); host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host); rebound.mockReset(); pending.mockReset(); vi.spyOn(api, 'session').mockResolvedValue(owner); vi.spyOn(personalRebindApi, 'preview').mockResolvedValue(preview); vi.spyOn(personalRebindApi, 'commit').mockImplementation(async input => receipt(input.requestId)); vi.spyOn(personalRebindApi, 'recover').mockImplementation(async requestId => receipt(requestId)); });
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function mount(session = original, commandPending = false, ownerId = owner.id) { await act(async () => root.render(createElement(PersonalSessionRebind, { ownerId, namespace: session.namespace, session, candidates: [next], commandPending, disabled: false, onRebound: rebound, onPending: pending }))); }
function button(label: string) { const b = [...host.querySelectorAll('button')].find(item => item.textContent === label); if (!b) throw new Error(label); return b; }
async function click(label: string) { await act(async () => button(label).click()); }
async function choose() { await act(async () => { const select = host.querySelector<HTMLSelectElement>('select')!; Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')!.set!.call(select, next.ref); select.dispatchEvent(new Event('change', { bubbles: true })); }); }
async function showPreview() { await mount(); await choose(); await click('只读预览原会话续接'); }
const storage = `factory-personal-rebind:${owner.id}:opencode`;
it('previews expired or credential-rotated bindings, then explicitly renews the SAME native identity without expanding capabilities', async () => {
  await showPreview(); expect(personalRebindApi.preview).toHaveBeenCalledWith(original.id, next.ref, old.fingerprint); expect(personalRebindApi.commit).not.toHaveBeenCalled(); expect(host.textContent).toContain(old.fingerprint); expect(host.textContent).toContain(next.fingerprint);
  await act(async () => { button('确认续接同一原生会话').click(); button('确认续接同一原生会话').click(); });
  expect(personalRebindApi.commit).toHaveBeenCalledTimes(1); expect(personalRebindApi.commit).toHaveBeenCalledWith(expect.objectContaining({ sessionId: original.id, nativeProjectId: original.nativeProjectId, nativeSessionId: original.nativeSessionId, expectedOldFingerprint: old.fingerprint, expectedNewFingerprint: next.fingerprint }));
  expect(rebound).toHaveBeenCalledWith(expect.objectContaining({ id: original.id, nativeSessionId: original.nativeSessionId, factoryIdentity: original.factoryIdentity })); expect(localStorage.getItem(storage)).toBeNull();
});
it('blocks unresolved and UNKNOWN turns instead of rebuilding a session or bypassing the original request', async () => {
  vi.mocked(personalRebindApi.preview).mockResolvedValue({ ...preview, activeRequestId: 'unknown-original-request', canRebind: false, blocker: 'PERSONAL_PREVIOUS_TURN_UNRESOLVED' });
  await showPreview(); expect(button('确认续接同一原生会话').disabled).toBe(true); expect(host.textContent).toContain('未知确认不能通过换绑定绕过'); expect(personalRebindApi.commit).not.toHaveBeenCalled();
});
it('still requires recovery of a locally pending original command after a successful read-only preview', async () => {
  await mount(original, true); await choose(); await click('只读预览原会话续接'); expect(button('确认续接同一原生会话').disabled).toBe(true); expect(personalRebindApi.commit).not.toHaveBeenCalled();
});
it('canceling the preview and repeated preview clicks never commit renewal', async () => {
  await mount(); await choose(); await act(async () => { button('只读预览原会话续接').click(); button('只读预览原会话续接').click(); }); expect(personalRebindApi.preview).toHaveBeenCalledTimes(1);
  await click('取消续接预览'); expect(host.textContent).not.toContain('确认续接同一原生会话'); expect(personalRebindApi.commit).not.toHaveBeenCalled();
});
it('recovers a lost metadata ACK after reload only through the original request, never resubmitting', async () => {
  vi.mocked(personalRebindApi.commit).mockRejectedValue(new Error('untrusted upstream detail')); await showPreview(); await click('确认续接同一原生会话');
  const saved = JSON.parse(localStorage.getItem(storage)!); expect(saved.expectedOldFingerprint).toBe(old.fingerprint); expect(saved.expectedNewFingerprint).toBe(next.fingerprint); expect(host.textContent).not.toContain('untrusted upstream detail');
  await act(async () => root.unmount()); root = createRoot(host); await mount(); await act(async () => { button('核对原续接请求').click(); button('核对原续接请求').click(); });
  expect(personalRebindApi.recover).toHaveBeenCalledTimes(1); expect(personalRebindApi.recover).toHaveBeenCalledWith(saved.requestId); expect(personalRebindApi.commit).toHaveBeenCalledTimes(1); expect(rebound).toHaveBeenCalledWith(expect.objectContaining({ id: original.id }));
});
it('rejects changed old/new fingerprints, owner changes and expanded capabilities before confirmation', () => {
  expect(checkRebindPreview(preview, original, next, owner.id)).toEqual(preview);
  for (const changed of [{ oldConnectionPin: { ...old, fingerprint: 'c'.repeat(64) } }, { newConnectionPin: { ...next, fingerprint: 'c'.repeat(64) } }, { newConnectionPin: { ...next, ownerId: 'other-owner' } }, { newConnectionPin: { ...next, capabilities: [...old.capabilities, 'admin:all'] } }, { nativeSessionId: 'new-native-session' }, { canRebind: true, activeRequestId: 'unresolved-original' }]) expect(() => checkRebindPreview({ ...preview, ...changed }, original, next, owner.id)).toThrow();
});
it('rejects a receipt that replaces original native identity, creation task, plan or pin history', () => {
  const request = rebindRecovery(preview, original, 'original-rebind-request'); const result = receipt(request.requestId);
  expect(checkRebindReceipt(result, request, owner.id, original.namespace)).toEqual(result);
  for (const changed of [{ nativeSessionId: 'replacement' }, { id: 'replacement' }, { factoryIdentity: { ...original.factoryIdentity!, planId: 'replacement-plan' } }, { bindingHistory: [] }, { connectionPin: { ...next, fingerprint: 'c'.repeat(64) } }]) expect(() => checkRebindReceipt({ ...result, session: { ...result.session, ...changed } }, request, owner.id, original.namespace)).toThrow();
});
it('ignores a late preview after owner navigation and cannot renew as the new owner', async () => {
  let finish!: (value: RebindPreview) => void; vi.mocked(personalRebindApi.preview).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  await mount(); await choose(); await click('只读预览原会话续接'); await mount(original, false, 'different-owner'); await act(async () => finish(preview));
  expect(host.textContent).not.toContain('确认续接同一原生会话'); expect(personalRebindApi.commit).not.toHaveBeenCalled();
});
it('can recover old commands and old attachment ACKs only through an exact non-expanding historical pin chain', () => {
  const updated = receipt('original-rebind-request').session;
  const plan = { id: original.factoryIdentity!.planId, fingerprint: 'plan-fingerprint', inputValues: { executionContract: PERSONAL_CONTRACT, action: 'prompt', connectionPin: JSON.stringify(old), nativeProjectId: original.nativeProjectId, nativeSessionId: original.nativeSessionId, factorySessionId: original.id } } as unknown as Plan;
  const recovered: PersonalRecovery = { requestId: 'original-command', plan, authorization: {} as PlanAuthorization, job: { id: original.factoryIdentity!.taskId, planId: plan.id } as FactoryJob, nativeRunId: original.factoryIdentity!.nativeRunId, receipt: { requestId: 'original-command', action: 'prompt', state: 'result_observed', factoryIdentity: original.factoryIdentity!, session: updated } };
  expect(checkPersonalRecovery(recovered, recovered.requestId, plan.id)).toEqual(recovered);
  const attach = { requestId: 'original-attach', action: 'attach' as const, state: 'acknowledged' as const, factoryIdentity: null, result: { status: 'attached_read_only' as const, nativeProjectId: original.nativeProjectId, nativeSessionId: original.nativeSessionId! }, session: updated };
  expect(checkAttachment(attach, { requestId: attach.requestId, connectionRef: old.ref, nativeProjectId: original.nativeProjectId, nativeSessionId: original.nativeSessionId! }, original.namespace)).toEqual(attach);
  expect(historicalConnectionMatches(updated, old)).toBe(true);
  for (const bad of [{ ...updated, bindingHistory: [] }, { ...updated, connectionRef: 'unexplained-binding' }, { ...updated, bindingHistory: [{ ...updated.bindingHistory![0], newConnectionPin: { ...next, capabilities: [...old.capabilities, 'admin:all'] } }] }, { ...updated, bindingHistory: [{ ...updated.bindingHistory![0], oldConnectionPin: { ...old, ownerId: 'different-owner' } }] }]) expect(historicalConnectionMatches(bad, old)).toBe(false);
});
it('supports the same renewal contract for native OpenResearch without changing namespaces or promises', () => {
  const orxOld = { ...old, kind: 'orx' as const }; const orxNew = { ...next, kind: 'orx' as const }; const orx = { ...original, namespace: 'native-openresearch' as const, upstreamOrxProjectId: original.nativeProjectId, connectionPin: orxOld };
  const orxPreview = { ...preview, namespace: orx.namespace, oldConnectionPin: orxOld, newConnectionPin: orxNew };
  expect(checkRebindPreview(orxPreview, orx, orxNew, owner.id)).toEqual(orxPreview);
});

it('keeps a recovered earlier renewal pinned even after a later explicitly recorded renewal', () => {
  const intent = rebindRecovery(preview, original, 'first-rebind-request'); const result = receipt(intent.requestId); const third = { ...next, ref: 'third-binding', fingerprint: 'c'.repeat(64), revision: 'third-revision', capabilities: ['session:read'] };
  const later = { ...result, session: { ...result.session, connectionRef: third.ref, connectionPin: third, bindingHistory: [...result.session.bindingHistory!, { requestId: 'second-rebind-request', changedAt: '2026-10-08T01:00:00Z', oldConnectionPin: next, newConnectionPin: third }] } };
  expect(checkRebindReceipt(later, intent, owner.id, original.namespace)).toEqual(later);
  expect(() => checkRebindReceipt({ ...later, session: { ...later.session, bindingHistory: later.session.bindingHistory.slice(1) } }, intent, owner.id, original.namespace)).toThrow();
});
it('does not commit metadata if the original renewal identity cannot be stored', async () => {
  await showPreview(); const originalStorage = localStorage;
  vi.stubGlobal('localStorage', new Proxy(originalStorage, { get(target, key) { return key === 'setItem' ? () => { throw new Error('storage denied'); } : Reflect.get(target, key); } }));
  await click('确认续接同一原生会话'); expect(personalRebindApi.commit).not.toHaveBeenCalled(); expect(rebound).not.toHaveBeenCalled();
});

it('blocks an unknown interrupt from the durable ledger even with no active prompt', async () => {
  vi.mocked(personalRebindApi.preview).mockResolvedValue({ ...preview, canRebind: false, activeRequestId: null, blocker: 'PERSONAL_INTERRUPT_ACK_UNKNOWN', blockers: [{ requestId: 'original-unknown-interrupt', action: 'interrupt', state: 'ack_unknown', source: 'durable-command-ledger' }] });
  await showPreview(); expect(button('确认续接同一原生会话').disabled).toBe(true); expect(host.textContent).toContain('original-unknown-interrupt'); expect(host.textContent).toContain('持久命令记录'); expect(host.textContent).toContain('远程停止未经证实'); expect(personalRebindApi.commit).not.toHaveBeenCalled();
  expect(() => checkRebindPreview({ ...preview, blockers: [{ requestId: 'unresolved-interrupt', action: 'interrupt', state: 'ack_unknown', source: 'durable-command-ledger' }] }, original, next, owner.id)).toThrow();
});
