import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { checkedAuthorization, checkedPlanAuthorization, checkedReview } from '../web/planReviewState.js';
import { PlanReviewGate, PlanReviews } from '../web/PlanReviews.js';
import type { Plan, PlanAuthorization } from '../web/models.js';

const h = (letter: string) => letter.repeat(64);
const plan = { id: 'plan-a', fingerprint: h('a'), status: 'ready' } as Plan;
const authorization: PlanAuthorization = { ownerId: 'alice', planId: plan.id, planFingerprint: plan.fingerprint, executionAllowed: true, reviewRequired: false, reviewRequestSupported: false, nativeToolConfirmationRequired: false,
  policy: { name: 'member-self-service', revision: 'r1', fingerprint: h('b'), review_ttl_seconds: 300, nativeToolConfirmationSeparate: true } };
const review = { id: 'review-a', ownerId: 'alice', planId: plan.id, planFingerprint: plan.fingerprint, planDigest: h('c'), policyDigest: h('b'),
  policyRevision: 'r1', requestId: 'request-a', createdAt: '2026-10-04T00:00:00Z', expiresAt: '2026-10-05T00:00:00Z', expired: false,
  currentPolicy: true, planIntegrityMatches: true, decision: 'pending', approvalEffective: false, reviewerId: null, planSummary: {} };

describe('self-service authorization and read-only history validation', () => {
  it('accepts exact current identity and scope without any review record', () => {
    expect(checkedPlanAuthorization(authorization, 'alice', plan)).toBe(authorization);
    for (const patch of [{ ownerId: 'bob' }, { planId: 'another-plan' }, { planFingerprint: h('d') }, { ownerId: undefined }]) {
      expect(() => checkedPlanAuthorization({ ...authorization, ...patch }, 'alice', plan)).toThrow();
    }
  });
  it('still verifies native confirmation separation and rejects malformed authorization', () => {
    const misplaced = { ...authorization, policy: { ...authorization.policy, nativeToolConfirmationSeparate: undefined }, nativeToolConfirmationSeparate: true };
    expect(() => checkedAuthorization(misplaced as unknown as PlanAuthorization)).toThrow();
    expect(() => checkedAuthorization({ ...authorization, executionAllowed: 'true' } as unknown as PlanAuthorization)).toThrow();
    expect(() => checkedAuthorization({ ...authorization, nativeToolConfirmationRequired: undefined } as unknown as PlanAuthorization)).toThrow();
    expect(checkedAuthorization({ ...authorization, nativeToolConfirmationRequired: true }).nativeToolConfirmationRequired).toBe(true);
  });
  it('preserves valid historical decisions and owner identities as evidence', () => {
    for (const decision of ['pending', 'approved', 'denied']) expect(checkedReview({ ...review, decision }).decision).toBe(decision);
    for (const ownerId of ['alice@example.com', '研究部门用户']) expect(checkedReview({ ...review, ownerId, reviewerId: ownerId }).ownerId).toBe(ownerId);
    for (const ownerId of ['bad\nowner', '', 'a'.repeat(201)]) expect(() => checkedReview({ ...review, ownerId })).toThrow();
    expect(() => checkedReview({ ...review, approvalEffective: true })).toThrow();
    expect(() => checkedReview({ ...review, planDigest: 'not-a-hash' })).toThrow();
  });
  it('renders no approval controls before current identity has been checked', () => {
    const act = vi.fn(); const onAllowed = vi.fn();
    const html = renderToStaticMarkup(createElement(PlanReviewGate, { ownerId: 'alice', plan, busy: '', act, onAllowed }));
    expect(html).toContain('正在核对当前身份与方案'); expect(html).not.toContain('提交方案审查');
    const history = renderToStaticMarkup(createElement(PlanReviews, { ownerId: 'manager', busy: '', act }));
    expect(history).toContain('历史方案审查'); expect(history).not.toContain('同意方案'); expect(history).not.toContain('拒绝方案'); expect(act).not.toHaveBeenCalled();
  });
});
