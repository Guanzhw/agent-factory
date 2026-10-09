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
  executionAllowed: false, ownerSubmissionSupported: true, reviewRequired: false, reviewRequestSupported: false,
  nativeToolConfirmationRequired: false, policy: { name: 'admin-review', revision: 'fixture-policy', fingerprint: 'b'.repeat(64), review_ttl_seconds: 300, nativeToolConfirmationSeparate: true } };
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
  expect(host.textContent).not.toContain('需要管理员审查'); expect(api.requestPlanReview).not.toHaveBeenCalled();
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
