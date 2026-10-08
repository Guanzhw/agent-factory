import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { checkedAuthorization, checkedReview, recoverPlanReviews, requestReviewOnce } from '../web/planReviewState.js';
import { PlanReviewGate, PlanReviews } from '../web/PlanReviews.js';
import type { Plan, PlanAuthorization } from '../web/models.js';

const h = (letter: string) => letter.repeat(64);
const plan = { id: 'plan-a', fingerprint: h('a'), status: 'ready' } as Plan;
const authorization: PlanAuthorization = { executionAllowed: false, reviewRequired: true, nativeToolConfirmationRequired: false,
  policy: { name: 'admin-review', revision: 'r1', fingerprint: h('b'), review_ttl_seconds: 300, nativeToolConfirmationSeparate: true } };
const review = { id: 'review-a', ownerId: 'alice', planId: plan.id, planFingerprint: plan.fingerprint, planDigest: h('c'), policyDigest: h('b'),
  policyRevision: 'r1', requestId: 'request-a', createdAt: '2026-10-04T00:00:00Z', expiresAt: '2026-10-05T00:00:00Z', expired: false,
  currentPolicy: true, planIntegrityMatches: true, decision: 'pending', approvalEffective: false, reviewerId: null, planSummary: {} };
const recover = (values: unknown) => recoverPlanReviews(values, 'alice', plan, authorization);
describe('exact plan review recovery', () => {
  it('accepts the backend status shape with separation inside policy, not at the top level', () => {
    const response = { ...authorization, ownerId: 'alice', planId: plan.id, planDigest: h('c'), planFingerprint: plan.fingerprint, reviewRequestSupported: true, reason: 'PLAN_REVIEW_REQUIRED', approval: null };
    expect(checkedAuthorization(response)).toBe(response);
    expect(recoverPlanReviews([review], 'alice', plan, response).pending).toBe(true);
    const misplaced = { ...response, policy: { ...response.policy, nativeToolConfirmationSeparate: undefined }, nativeToolConfirmationSeparate: true };
    expect(() => checkedAuthorization(misplaced as unknown as PlanAuthorization)).toThrow();
    expect(() => checkedAuthorization({ ...response, nativeToolConfirmationRequired: undefined } as unknown as PlanAuthorization)).toThrow();
    expect(checkedAuthorization({ ...response, nativeToolConfirmationRequired: true }).nativeToolConfirmationRequired).toBe(true);
  });
  it('accepts mapped email and Unicode owners while rejecting control characters', () => {
    for (const ownerId of ['alice@example.com', '研究部门用户']) expect(recoverPlanReviews([{ ...review, ownerId, reviewerId: ownerId }], ownerId, plan, authorization).pending).toBe(true);
    for (const ownerId of ['bad\nowner', '', 'a'.repeat(201)]) expect(() => checkedReview({ ...review, ownerId })).toThrow();
  });
  it('restores a pending request without enabling another POST', () => {
    expect(recover([review])).toMatchObject({ review, pending: true, canRequest: false });
    expect(recover([])).toMatchObject({ pending: false, canRequest: true });
  });
  it('offers a new explicit request for denied, expired or replaced-policy records', () => {
    for (const update of [{ decision: 'denied' }, { expired: true }, { currentPolicy: false, policyDigest: h('d'), policyRevision: 'old' }]) {
      expect(recover([{ ...review, ...update }])).toMatchObject({ pending: false, canRequest: true });
    }
  });
  it('does not allow an old denied record to hide a currently pending request', () => {
    expect(recover([review, { ...review, id: 'newer-denied', requestId: 'request-b', decision: 'denied', createdAt: '2026-10-04T01:00:00Z' }]).pending).toBe(true);
  });
  it('rejects foreign owner, changed fingerprint/digest, corruption and policy mismatch', () => {
    for (const patch of [{ ownerId: 'bob' }, { planFingerprint: h('d') }, { planIntegrityMatches: false }, { policyDigest: h('d') }, { policyRevision: 'wrong' }, { planDigest: 'not-a-hash' }]) expect(() => recover([{ ...review, ...patch }])).toThrow();
    expect(() => recover([review, { ...review, id: 'other', planDigest: h('d') }])).toThrow();
    expect(() => recover([review, review])).toThrow();
  });
  it('does not confuse another plan with the current review and fails closed at the list bound', () => {
    expect(recover([{ ...review, planId: 'other-plan' }]).review).toBeUndefined();
    const rows = Array.from({ length: 100 }, (_, i) => ({ ...review, id: `review-${i}`, decision: 'denied' }));
    expect(recover(rows)).toMatchObject({ truncated: true, canRequest: false });
    expect(() => recover([...rows, review])).toThrow();
  });
  it('uses current authorization, never a list approval, as execution authority', () => {
    expect(recover([{ ...review, decision: 'approved', reviewerId: 'manager', approvalEffective: true }]).canRequest).toBe(false);
    expect(recoverPlanReviews([], 'alice', plan, { ...authorization, executionAllowed: true }).canRequest).toBe(false);
    expect(() => checkedAuthorization({ ...authorization, executionAllowed: 'true' } as unknown as PlanAuthorization)).toThrow();
    expect(() => checkedReview({ ...review, approvalEffective: true })).toThrow();
    expect(recover([{ ...review, decision: 'approved', reviewerId: 'manager' }, { ...review, id: 'later-denial', decision: 'denied', createdAt: '2026-10-04T01:00:00Z' }]).canRequest).toBe(true);
  });
  it('reconciles a lost reply by GET with original request id and no second POST', async () => {
    const post = vi.fn().mockRejectedValue(new Error('offline'));
    const get = vi.fn().mockResolvedValue([{ ...review, requestId: 'unrelated' }, review]);
    expect(await requestReviewOnce(post, get, checkedReview, review.requestId)).toEqual(review);
    expect(post).toHaveBeenCalledTimes(1); expect(get).toHaveBeenCalledTimes(1);
  });
  it('retains uncertainty for missing, malformed or foreign-scope receipts', async () => {
    const original = new Error('reply lost');
    for (const rows of [[], [{ ...review, planDigest: 'invalid' }], [{ ...review, ownerId: 'bob' }]]) {
      const post = vi.fn().mockRejectedValue(original);
      const check = (value: unknown) => { const r = checkedReview(value); recover([r]); return r; };
      await expect(requestReviewOnce(post, async () => rows, check, review.requestId)).rejects.toBe(original);
      expect(post).toHaveBeenCalledTimes(1);
    }
  });
  it('renders fail closed before current identity and server state have been checked', () => {
    const act = vi.fn(); const onAllowed = vi.fn();
    const html = renderToStaticMarkup(createElement(PlanReviewGate, { ownerId: 'alice', plan, busy: '', act, onAllowed }));
    expect(html).toContain('当前不允许执行'); expect(html).not.toContain('提交方案审查');
    const admin = renderToStaticMarkup(createElement(PlanReviews, { ownerId: 'manager', busy: '', act }));
    expect(admin).not.toContain('同意方案'); expect(act).not.toHaveBeenCalled();
  });
});
