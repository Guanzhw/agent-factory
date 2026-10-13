// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { PlanReviewGate } from '../web/PlanReviews.js';
import { api } from '../web/api.js';
import { checkedAuthorization } from '../web/planReviewState.js';
import type { Plan, PlanAuthorization } from '../web/models.js';
const plan = { id: 'owner-plan-fixture', fingerprint: 'a'.repeat(64), status: 'ready' } as Plan;
const state: PlanAuthorization = { ownerId: 'alice', planId: plan.id, planFingerprint: plan.fingerprint,
  executionAllowed: true, ownerSubmissionSupported: true, reviewRequired: false, reviewRequestSupported: false,
  nativeToolConfirmationRequired: false, policy: { name: 'member-self-service', revision: 'fixture-policy', fingerprint: 'b'.repeat(64), review_ttl_seconds: 300, nativeToolConfirmationSeparate: true } };
let host: HTMLDivElement; let root: Root; const allowed = vi.fn();
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); host = document.createElement('div'); document.body.append(host); root = createRoot(host); allowed.mockClear();
  vi.spyOn(api, 'session').mockResolvedValue({ id: 'alice', name: 'Alice', role: 'user' });
  vi.spyOn(api, 'planAuthorization').mockResolvedValue(state); vi.spyOn(api, 'planReviews').mockResolvedValue([]); vi.spyOn(api, 'requestPlanReview');
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function mount() { await act(async () => root.render(createElement(PlanReviewGate, { ownerId: 'alice', plan, busy: '', act: async (_name, work) => work(), onAllowed: allowed }))); }
it('allows the original owner business submit only when the server verifies that exact eligible plan', async () => {
  await mount(); expect(allowed).toHaveBeenLastCalledWith(true); expect(host.textContent).toContain('提交即确认此次业务范围');
  expect(host.textContent).not.toContain('需要管理员审查'); expect(api.requestPlanReview).not.toHaveBeenCalled(); expect(api.planReviews).not.toHaveBeenCalled();
});
it('fails closed for foreign owner or changed plan authorization', async () => {
  for (const override of [{ ownerId: 'bob' }, { planId: 'other-plan' }, { planFingerprint: 'c'.repeat(64) }]) {
    vi.mocked(api.planAuthorization).mockResolvedValue({ ...state, ...override }); await mount();
    expect(allowed).toHaveBeenLastCalledWith(false); expect(host.textContent).not.toContain('提交即确认此次业务范围');
    await act(async () => root.unmount()); root = createRoot(host);
  }
});
it('rejects contradictory or malformed owner-submission capabilities', () => {
  expect(() => checkedAuthorization({ ...state, reviewRequired: true })).toThrow();
  expect(() => checkedAuthorization({ ...state, reviewRequestSupported: true })).toThrow();
  expect(() => checkedAuthorization({ ...state, ownerSubmissionSupported: 'true' } as unknown as PlanAuthorization)).toThrow();
});

it('does not poll or read historical reviews when a new member plan can run', async () => {
  vi.useFakeTimers();
  try {
    vi.mocked(api.planAuthorization).mockResolvedValue({ ...state, executionAllowed: true, ownerSubmissionSupported: false });
    vi.mocked(api.planReviews).mockRejectedValue(new Error('Historical records unavailable'));
    await mount(); expect(allowed).toHaveBeenLastCalledWith(true);
    await act(async () => vi.advanceTimersByTimeAsync(15000));
    expect(api.planAuthorization).toHaveBeenCalledTimes(1); expect(api.session).toHaveBeenCalledTimes(1);
    expect(api.planReviews).not.toHaveBeenCalled(); expect(api.requestPlanReview).not.toHaveBeenCalled();
  } finally { vi.useRealTimers(); }
});
it('keeps old pending, denied and unknown plans read-only without issuing mutations', async () => {
  for (const code of ['LEGACY_PLAN_READ_ONLY', 'PLAN_REVIEW_DENIED', 'ADMISSION_UNKNOWN']) {
    vi.mocked(api.planAuthorization).mockResolvedValue({ ...state, executionAllowed: false, ownerSubmissionSupported: false, code, message: '历史方案只读，请重新生成。' });
    await mount(); expect(allowed).toHaveBeenLastCalledWith(false);
    expect(host.textContent).toContain('历史方案只读'); expect(host.textContent).not.toContain('提交方案审查');
    expect(api.requestPlanReview).not.toHaveBeenCalled();
    await act(async () => root.unmount()); root = createRoot(host);
  }
});

it.each(['arbitrary-department-app', 'workflow-v3', 'new-tool-app', 'future-app-without-exemption'])('accepts current member authorization for %s without an application allowlist', async applicationId => {
  const ordinaryPlan = { ...plan, applicationRef: { id: applicationId, version: 1, sha256: 'd'.repeat(64) } };
  vi.mocked(api.planAuthorization).mockResolvedValue({ ...state, executionAllowed: true, ownerSubmissionSupported: false });
  await act(async () => root.render(createElement(PlanReviewGate, { ownerId: 'alice', plan: ordinaryPlan, busy: '', act: async (_name, work) => work(), onAllowed: allowed })));
  expect(allowed).toHaveBeenLastCalledWith(true); expect(api.planReviews).not.toHaveBeenCalled(); expect(api.requestPlanReview).not.toHaveBeenCalled();
});

it('does not use the old owner-submission capability as a second execution authority', async () => {
  vi.mocked(api.planAuthorization).mockResolvedValue({ ...state, executionAllowed: false, ownerSubmissionSupported: true });
  await mount(); expect(allowed).toHaveBeenLastCalledWith(false);
  expect(host.textContent).not.toContain('提交即确认此次业务范围'); expect(api.requestPlanReview).not.toHaveBeenCalled();
});
