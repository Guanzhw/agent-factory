// @vitest-environment happy-dom
import { webcrypto } from 'node:crypto';
import { act, createElement, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApplicationComposer } from '../web/ApplicationComposer.js';
import { api } from '../web/api.js';
import type { AssemblyCandidate, AssemblyProposal, FactoryApplication, FactoryMaterial, Plan, PlanAuthorization, PlanReview, UserConnection } from '../web/models.js';

const owner = { id: 'alice', name: 'Alice', role: 'user' as const };
const proposalId = '11111111-1111-4111-8111-111111111111';
const applicationRef = { id: 'approved-fixture', version: 1, sha256: 'a'.repeat(64) };
const tool: FactoryMaterial = { id: 'tool-read', version: 1, sha256: 'b'.repeat(64), kind: 'tool', name: '公开来源读取', description: '合成演示', content: 'read_source', license: 'MIT', origin: 'fixture', dependencies: [], compatibility: [], permissions: ['read:public'], inputSchema: {}, outputSchema: {}, archived: false, published: true, createdAt: '2026-10-08T00:00:00Z' };
const toolRef = { id: tool.id, version: tool.version, sha256: tool.sha256 };
const budget = { toolCalls: 8, maxDepth: 2, maxChildren: 4, experimentSeconds: 8, outputBytes: 65536 };
const application: FactoryApplication = { ...applicationRef, name: '公开证据比较', description: '比较来源与差异', discoveryKeywords: ['比较'], defaultForDiscovery: true, defaultMode: 'literature', modes: { literature: { materialRefs: [toolRef], materialChoices: { reader: { kind: 'tool', defaultRef: toolRef, allowedRefs: [toolRef] } }, capabilities: ['read:public'], budget, config: {}, toolOrder: ['read_source'], connectionRequirements: [{ name: 'model', kind: 'model', requiredCapabilities: ['text'], required: true }] } } };
const connection: UserConnection = { ref: 'fixture-connection', ownerId: owner.id, version: 1, fingerprint: 'c'.repeat(64), kind: 'model', revision: 'r1', capabilities: ['text'], taskId: null, registrationRef: 'fixture-model', expiresAt: null, createdAt: '2026-10-08T00:00:00Z', revokedAt: null, status: 'active', available: true, allowedActions: ['inspect', 'revoke'] };
const candidate: AssemblyCandidate = { application: application.id, applicationRef, mode: 'literature', normalizedGoal: '比较两种公开方法', materialRefs: [toolRef], materials: [tool], tools: ['read_source'], capabilities: ['read:public'], budget, config: {}, instructions: 'Bounded fixture', status: 'ready', missing: [], policy: {}, syntheticFixture: true, executionBindings: null, bindingManifest: {}, fingerprint: 'd'.repeat(64) };
const plan: Plan = { id: 'plan-fixture', fingerprint: 'e'.repeat(64), normalizedGoal: candidate.normalizedGoal, applicationRef, materialRefs: [toolRef], capabilities: candidate.capabilities, missing: [], status: 'ready', createdAt: '2026-10-08T00:00:00Z', bindingManifest: { connections: { model: { ref: connection.ref, fingerprint: connection.fingerprint } } } };
const baseAuthorization: PlanAuthorization = { executionAllowed: false, reviewRequired: true, nativeToolConfirmationRequired: false, policy: { name: 'admin-review', revision: 'r1', fingerprint: 'f'.repeat(64), review_ttl_seconds: 300, nativeToolConfirmationSeparate: true } };
let host: HTMLDivElement; let root: Root; let saved: AssemblyProposal | undefined; let savedPlan: Plan | null;
let authorization: PlanAuthorization; let reviews: PlanReview[];
const onCreated = vi.fn();
function Harness() {
  const [busy, setBusy] = useState(''); const [error, setError] = useState('');
  return createElement('div', null, error && createElement('p', { role: 'alert' }, error), createElement(ApplicationComposer, {
    user: owner, busy, materials: [tool], targets: [], onCreated,
    act: async (name, work) => { setBusy(name); setError(''); try { await work(); } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(''); } },
  }));
}
const button = (text: string) => {
  const found = [...host.querySelectorAll('button')].find(item => item.textContent === text);
  expect(found, `button ${text}`).toBeDefined(); return found!;
};
async function click(text: string) { await act(async () => { button(text).click(); }); }
async function settle(assert: () => void) { await vi.waitFor(async () => { await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); }); assert(); }); }
async function mount() { await act(async () => { root.render(createElement(Harness)); }); await settle(() => expect(host.querySelector<HTMLSelectElement>('#application-selector')?.disabled).toBe(false)); }
async function fillTask() {
  await act(async () => {
    const select = host.querySelector<HTMLSelectElement>('#application-selector')!; select.value = application.id; select.dispatchEvent(new Event('change', { bubbles: true }));
  });
  await act(async () => {
    const goal = host.querySelector<HTMLTextAreaElement>('#research-topic')!;
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(goal, candidate.normalizedGoal);
    goal.dispatchEvent(new Event('input', { bubbles: true }));
    const select = host.querySelector<HTMLSelectElement>('[aria-label="资源连接 model"]')!; select.value = connection.ref; select.dispatchEvent(new Event('change', { bubbles: true }));
  });
  expect(button('预览任务方案').disabled).toBe(false);
}
async function previewAndAccept() {
  await fillTask(); await click('预览任务方案'); await settle(() => expect(button('确认范围并保存方案').disabled).toBe(false));
  await click('确认范围并保存方案'); await settle(() => expect(host.textContent).toContain('方案执行授权'));
}
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); vi.stubGlobal('crypto', webcrypto);
  window.sessionStorage.clear(); window.localStorage.clear();
  host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host);
  saved = undefined; savedPlan = null; authorization = structuredClone(baseAuthorization); reviews = []; onCreated.mockReset();
  vi.spyOn(api, 'session').mockResolvedValue(owner); vi.spyOn(api, 'applications').mockResolvedValue([application]);
  vi.spyOn(api, 'userConnections').mockResolvedValue([connection]);
  vi.spyOn(api, 'proposalInbox').mockResolvedValue({ schema: 1, ownerId: owner.id, snapshot: false, items: [], nextCursor: null });
  vi.spyOn(api, 'propose').mockImplementation(async input => {
    saved = { id: proposalId, ownerId: owner.id, createdAt: '2026-10-08T00:00:00Z', parentId: null, input, candidate: { ...candidate, normalizedGoal: input.goal }, selection: { method: 'explicit-application', matchedKeywords: [] }, fingerprint: '1'.repeat(64), state: 'pending', planId: null, allowedActions: ['revise', 'accept', 'reject'] }; return saved;
  });
  vi.spyOn(api, 'recoverProposal').mockImplementation(async () => { if (!saved) throw new Error('No saved record'); return { proposal: saved, plan: savedPlan }; });
  vi.spyOn(api, 'acceptProposal').mockImplementation(async () => { saved = { ...saved!, state: 'accepted', planId: plan.id, allowedActions: [] }; savedPlan = plan; return plan; });
  vi.spyOn(api, 'planAuthorization').mockImplementation(async () => authorization);
  vi.spyOn(api, 'planReviews').mockImplementation(async () => reviews);
  vi.spyOn(api, 'instantiate').mockResolvedValue({ id: 'created-task' } as Awaited<ReturnType<typeof api.instantiate>>);
});
afterEach(async () => { await act(async () => { root.unmount(); }); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('mounted task creation flow', () => {
  it('selects an application, previews scope, preserves approval gating, and only starts after current authorization', async () => {
    await mount(); expect(api.recoverProposal).not.toHaveBeenCalled();
    await fillTask();
    const resource = host.querySelector('[aria-label="资源连接 model"]')!;
    expect(resource.closest('details')).toBeNull();
    expect(host.querySelector('[aria-label="材料选择 reader"]')?.closest('details')?.open).toBe(false);
    await click('预览任务方案'); await settle(() => expect(button('确认范围并保存方案').disabled).toBe(false));
    expect(api.propose).toHaveBeenCalledTimes(1);
    expect(vi.mocked(api.propose).mock.calls[0][0]).toMatchObject({ application: application.id, goal: candidate.normalizedGoal, connectionRefs: { model: connection.ref } });
    expect(api.instantiate).not.toHaveBeenCalled();
    await click('确认范围并保存方案'); await settle(() => expect(host.textContent).toContain('需要管理员审查'));
    expect(button('开始任务').disabled).toBe(true); await click('开始任务'); expect(api.instantiate).not.toHaveBeenCalled();
    authorization = { ...authorization, executionAllowed: true };
    await click('刷新授权与审查状态'); await settle(() => expect(button('开始任务').disabled).toBe(false));
    expect(api.instantiate).not.toHaveBeenCalled();
    await click('开始任务'); await settle(() => expect(onCreated).toHaveBeenCalledWith('created-task'));
    expect(api.instantiate).toHaveBeenCalledTimes(1);
    expect(vi.mocked(api.instantiate).mock.calls[0][0]).toBe(plan.id);
  });
  it('keeps an unset policy and a denied review disabled without instantiation', async () => {
    authorization = { ...baseAuthorization, reviewRequired: false, policy: { ...baseAuthorization.policy, name: 'unset' } };
    await mount(); await previewAndAccept(); await settle(() => expect(host.textContent).toContain('执行已停用'));
    expect(button('开始任务').disabled).toBe(true);
    authorization = structuredClone(baseAuthorization);
    reviews = [{ id: 'review-fixture', ownerId: owner.id, planId: plan.id, planFingerprint: plan.fingerprint, planDigest: '2'.repeat(64), policyDigest: authorization.policy.fingerprint, policyRevision: authorization.policy.revision, requestId: 'review-request', createdAt: '2026-10-08T00:00:00Z', expiresAt: '2026-10-09T00:00:00Z', expired: false, currentPolicy: true, planIntegrityMatches: true, decision: 'denied', approvalEffective: false, reviewerId: 'manager', planSummary: {} } as PlanReview];
    await click('刷新授权与审查状态'); await settle(() => expect(host.textContent).toContain('已拒绝'));
    expect(button('开始任务').disabled).toBe(true); await click('开始任务'); expect(api.instantiate).not.toHaveBeenCalled();
  });
  it('explains an empty application catalog and cannot submit a task', async () => {
    vi.mocked(api.applications).mockResolvedValue([]); await mount();
    expect(host.textContent).toContain('当前没有可用的已批准应用');
    expect(button('预览任务方案').disabled).toBe(true); await click('预览任务方案');
    expect(api.propose).not.toHaveBeenCalled(); expect(api.instantiate).not.toHaveBeenCalled();
  });
  it('requires explicit historical recovery and refuses a foreign owner while preserving fresh input', async () => {
    window.sessionStorage.setItem('factory-proposal-v1:alice', proposalId);
    vi.mocked(api.recoverProposal).mockResolvedValue({ proposal: { id: proposalId, ownerId: 'bob' } as AssemblyProposal, plan });
    await mount(); await fillTask(); expect(api.recoverProposal).not.toHaveBeenCalled();
    expect(host.querySelector<HTMLDetailsElement>('.composer-history')?.open).toBe(false);
    await act(async () => { host.querySelector<HTMLDetailsElement>('.composer-history')!.open = true; });
    await click('继续上次保存的任务'); await settle(() => expect(host.textContent).toContain('提案归属或修订范围无法核对'));
    expect(host.querySelector<HTMLTextAreaElement>('#research-topic')!.value).toBe(candidate.normalizedGoal);
    expect(host.textContent).not.toContain('方案执行授权');
    expect(window.sessionStorage.getItem('factory-proposal-v1:alice')).toBe(proposalId);
    expect(api.acceptProposal).not.toHaveBeenCalled(); expect(api.instantiate).not.toHaveBeenCalled();
  });
  it('locks an uncertain proposal request and retries with the same input and idempotency key', async () => {
    vi.mocked(api.propose).mockRejectedValueOnce(new Error('Synthetic lost acknowledgement'));
    window.sessionStorage.setItem('factory-proposal-v1:alice', proposalId);
    await mount(); await fillTask(); await click('预览任务方案');
    await settle(() => expect(host.textContent).toContain('原装配请求未确认'));
    expect(host.querySelector<HTMLTextAreaElement>('#research-topic')!.disabled).toBe(true);
    expect(button('继续上次保存的任务').disabled).toBe(true);
    const firstCall = vi.mocked(api.propose).mock.calls[0];
    await click('核对原装配请求'); await settle(() => expect(button('确认范围并保存方案').disabled).toBe(false));
    expect(vi.mocked(api.propose).mock.calls[1]).toEqual(firstCall);
    expect(api.instantiate).not.toHaveBeenCalled();
  });
  it('can reconcile an uncertain request after the application catalog becomes empty using the original body and key', async () => {
    vi.mocked(api.propose).mockRejectedValueOnce(new Error('Synthetic lost acknowledgement'));
    await mount(); await fillTask(); await click('预览任务方案');
    await settle(() => expect(host.textContent).toContain('原装配请求未确认'));
    const originalCall = structuredClone(vi.mocked(api.propose).mock.calls[0]);
    vi.mocked(api.applications).mockResolvedValue([]);
    // Let the existing read-only refresh observe the now-empty catalog.
    await vi.waitFor(async () => {
      await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); });
      expect(host.textContent).toContain('当前没有可用的已批准应用');
    }, { timeout: 7000, interval: 50 });
    expect(host.querySelector<HTMLTextAreaElement>('#research-topic')!.disabled).toBe(true);
    expect(button('核对原装配请求').disabled).toBe(false);
    await click('核对原装配请求'); await settle(() => expect(button('确认范围并保存方案').disabled).toBe(false));
    expect(api.propose).toHaveBeenCalledTimes(2);
    expect(vi.mocked(api.propose).mock.calls[1]).toEqual(originalCall);
    expect(api.instantiate).not.toHaveBeenCalled();
  });

});
