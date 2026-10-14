// @vitest-environment happy-dom
import { webcrypto } from 'node:crypto';
import { act, createElement, type ComponentProps } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ApplicationComposer } from '../web/ApplicationComposer.js';
import { api } from '../web/api.js';
import type { AssemblyCandidate, AssemblyProposal, FactoryApplication, Plan, PlanAuthorization, UserConnection } from '../web/models.js';

const owner = { id: 'alice', name: 'Alice', role: 'user' as const };
const proposalId = '11111111-1111-4111-8111-111111111111';
const applicationRef = { id: 'schedule-fixture', version: 1, sha256: 'a'.repeat(64) };
const budget = { toolCalls: 1, maxDepth: 0, maxChildren: 0, experimentSeconds: 1, outputBytes: 1024 };
const application: FactoryApplication = { ...applicationRef, name: '定时演示', description: 'Synthetic fixture', discoveryKeywords: [], defaultForDiscovery: false, defaultMode: 'fixture', modes: { fixture: { materialRefs: [], materialChoices: {}, capabilities: [], budget, config: {}, toolOrder: [], connectionRequirements: [] } } };
const connection: UserConnection = { ref: 'fixture-connection', ownerId: owner.id, version: 1, fingerprint: 'b'.repeat(64), kind: 'model', revision: 'r1', capabilities: ['text'], taskId: null, registrationRef: 'fixture-model', expiresAt: null, createdAt: '2026-10-14T00:00:00Z', revokedAt: null, status: 'active', available: true, allowedActions: ['inspect', 'revoke'] };
const candidate: AssemblyCandidate = { application: application.id, applicationRef, mode: 'fixture', normalizedGoal: '重复执行确定性演示', materialRefs: [], materials: [], tools: [], capabilities: [], budget, config: {}, instructions: 'Synthetic fixture', status: 'ready', missing: [], policy: {}, syntheticFixture: true, executionBindings: null, bindingManifest: {}, fingerprint: 'c'.repeat(64) };
const basePlan: Plan = { id: 'schedule-plan', fingerprint: 'd'.repeat(64), normalizedGoal: candidate.normalizedGoal, applicationRef, materialRefs: [], capabilities: [], missing: [], status: 'ready', createdAt: '2026-10-14T00:00:00Z', bindingManifest: { connections: { model: { ref: connection.ref, fingerprint: connection.fingerprint } } } };
const proposal: AssemblyProposal = { id: proposalId, ownerId: owner.id, createdAt: basePlan.createdAt, parentId: null, input: { goal: candidate.normalizedGoal, application: application.id, connectionRefs: { model: connection.ref } }, candidate, selection: { method: 'explicit-application', matchedKeywords: [] }, fingerprint: 'e'.repeat(64), state: 'accepted', planId: basePlan.id, allowedActions: [] };
const baseAuthorization: PlanAuthorization = { ownerId: owner.id, planId: basePlan.id, planFingerprint: basePlan.fingerprint, executionAllowed: true, reviewRequired: false, reviewRequestSupported: false, nativeToolConfirmationRequired: false, policy: { name: 'member-self-service', revision: 'r1', fingerprint: 'f'.repeat(64), review_ttl_seconds: 300, nativeToolConfirmationSeparate: true } };
const scheduleLabel = '用此方案设置计划任务';
const onSchedule = vi.fn();
let host: HTMLDivElement;
let root: Root;
let plan: Plan;
let authorization: PlanAuthorization;

const findButton = (label: string) => [...host.querySelectorAll('button')].find(item => item.textContent === label);
function button(label: string) {
  const found = findButton(label);
  expect(found, `button ${label}`).toBeDefined();
  return found!;
}
async function click(label: string) { await act(async () => { button(label).click(); }); }
async function render(overrides: Partial<ComponentProps<typeof ApplicationComposer>> = {}) {
  await act(async () => {
    root.render(createElement(ApplicationComposer, { user: owner, busy: '', materials: [], targets: [], onCreated: vi.fn(), onSchedule,
      act: async (_name, work) => { await work(); }, ...overrides }));
  });
}
async function restore(overrides: Partial<ComponentProps<typeof ApplicationComposer>> = {}) {
  await render(overrides);
  expect(api.recoverProposal).not.toHaveBeenCalled();
  await act(async () => { host.querySelector<HTMLDetailsElement>('.composer-history')!.open = true; });
  await click('继续上次保存的任务');
  expect(host.querySelector('[aria-label="任务提交检查"]')).not.toBeNull();
}

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); vi.stubGlobal('crypto', webcrypto);
  sessionStorage.clear(); localStorage.clear(); sessionStorage.setItem('factory-proposal-v1:alice', proposalId);
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  plan = structuredClone(basePlan); authorization = structuredClone(baseAuthorization); onSchedule.mockReset();
  vi.spyOn(api, 'session').mockResolvedValue(owner);
  vi.spyOn(api, 'applications').mockResolvedValue([application]);
  vi.spyOn(api, 'userConnections').mockResolvedValue([connection]);
  vi.spyOn(api, 'proposalInbox').mockResolvedValue({ schema: 1, ownerId: owner.id, snapshot: false, items: [], nextCursor: null });
  vi.spyOn(api, 'recoverProposal').mockImplementation(async () => ({ proposal, plan }));
  vi.spyOn(api, 'planAuthorization').mockImplementation(async () => authorization);
  vi.spyOn(api, 'instantiate').mockRejectedValue(new Error('This flow must not start a task'));
  vi.spyOn(api, 'requestPlanReview').mockRejectedValue(new Error('This flow must not request review'));
});
afterEach(async () => {
  await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals();
});

it('lets an ordinary member open scheduling with the exact authorized saved plan without starting a task or requesting review', async () => {
  await restore();
  expect(api.planAuthorization).toHaveBeenCalledWith(plan.id, expect.any(AbortSignal));
  expect(button(scheduleLabel).disabled).toBe(false);
  await click(scheduleLabel);
  expect(onSchedule).toHaveBeenCalledExactlyOnceWith(plan);
  expect(api.instantiate).not.toHaveBeenCalled(); expect(api.requestPlanReview).not.toHaveBeenCalled();
});

it('keeps scheduling locked until the server authorization is resolved', async () => {
  let resolve!: (value: PlanAuthorization) => void;
  vi.mocked(api.planAuthorization).mockReturnValue(new Promise<PlanAuthorization>(done => { resolve = done; }));
  await restore();
  expect(button(scheduleLabel).disabled).toBe(true); await click(scheduleLabel); expect(onSchedule).not.toHaveBeenCalled();
  await act(async () => { resolve(authorization); });
  expect(button(scheduleLabel).disabled).toBe(false);
});

it.each(['denied', 'foreign owner'])('keeps scheduling locked for %s authorization', async reason => {
  authorization = reason === 'denied' ? { ...authorization, executionAllowed: false, code: 'ADMISSION_UNKNOWN' } : { ...authorization, ownerId: 'bob' };
  await restore();
  expect(button(scheduleLabel).disabled).toBe(true); await click(scheduleLabel);
  expect(onSchedule).not.toHaveBeenCalled(); expect(api.instantiate).not.toHaveBeenCalled();
});

it('locks scheduling for a remote execution target and re-enables it only after returning to this Factory', async () => {
  await restore({ targets: [{ id: 'remote-fixture', name: 'Remote fixture', kind: 'remote-factory', connectivityVerified: true }] });
  expect(button(scheduleLabel).disabled).toBe(false);
  const select = host.querySelector<HTMLSelectElement>('[aria-label="执行位置"]')!;
  await act(async () => { select.value = 'remote-fixture'; select.dispatchEvent(new Event('change', { bubbles: true })); });
  expect(button(scheduleLabel).disabled).toBe(true); await click(scheduleLabel); expect(onSchedule).not.toHaveBeenCalled();
  await act(async () => { select.value = ''; select.dispatchEvent(new Event('change', { bubbles: true })); });
  expect(button(scheduleLabel).disabled).toBe(false); await click(scheduleLabel);
  expect(onSchedule).toHaveBeenCalledExactlyOnceWith(plan);
});

it.each(['blocked plan', 'unavailable binding', 'unverified usage'])('preserves the scheduling gate for %s', async condition => {
  if (condition === 'blocked plan') plan = { ...plan, status: 'blocked', missing: ['Synthetic missing resource'] };
  if (condition === 'unavailable binding') vi.mocked(api.userConnections).mockResolvedValue([{ ...connection, available: false, status: 'revoked' }]);
  if (condition === 'unverified usage') plan = { ...plan, usageBudget: { schema: 1 } };
  await restore();
  expect(button(scheduleLabel).disabled).toBe(true); await click(scheduleLabel);
  expect(onSchedule).not.toHaveBeenCalled(); expect(api.instantiate).not.toHaveBeenCalled();
});

it('keeps scheduling disabled while another action is busy', async () => {
  await restore(); await render({ busy: 'other-action' });
  expect(button(scheduleLabel).disabled).toBe(true); await click(scheduleLabel); expect(onSchedule).not.toHaveBeenCalled();
});

it('does not render the scheduling entry when no handler is supplied', async () => {
  await restore({ onSchedule: undefined });
  expect(findButton(scheduleLabel)).toBeUndefined(); expect(onSchedule).not.toHaveBeenCalled();
});
