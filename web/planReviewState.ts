import type { Plan, PlanAuthorization, PlanReview } from './models.js';

export type CheckedPlanReview = PlanReview & { policyDigest: string; requestId: string; createdAt: string };
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const hash = (value: unknown) => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const id = (value: unknown) => typeof value === 'string' && /^[A-Za-z0-9_.:-]{1,128}$/.test(value);
const owner = (value: unknown) => typeof value === 'string' && [...value].length >= 1 && [...value].length <= 200 && [...value].every(char => char.codePointAt(0)! >= 32 && char.codePointAt(0) !== 127);
const date = (value: unknown) => typeof value === 'string' && Number.isFinite(Date.parse(value));
export function checkedReview(value: unknown): CheckedPlanReview {
  if (!record(value) || !['id', 'planId', 'requestId'].every(key => id(value[key])) || !owner(value.ownerId)
      || !['planDigest', 'planFingerprint', 'policyDigest'].every(key => hash(value[key]))
      || typeof value.policyRevision !== 'string' || !value.policyRevision
      || !date(value.createdAt) || !date(value.expiresAt)
      || !['expired', 'currentPolicy', 'approvalEffective', 'planIntegrityMatches'].every(key => typeof value[key] === 'boolean')
      || !['pending', 'approved', 'denied'].includes(String(value.decision))
      || !(value.reviewerId === null || owner(value.reviewerId))
      || value.planIntegrityMatches === true && !record(value.planSummary)
      || value.approvalEffective === true && (value.decision !== 'approved' || value.expired || !value.currentPolicy || !value.planIntegrityMatches)) {
    throw new Error('审查记录的身份、方案或策略凭据无法核对。');
  }
  return value as unknown as CheckedPlanReview;
}
export function checkedAuthorization(value: PlanAuthorization): PlanAuthorization {
  if (!record(value) || typeof value.executionAllowed !== 'boolean' || typeof value.reviewRequired !== 'boolean'
      || !record(value.policy) || typeof value.policy.name !== 'string' || typeof value.policy.revision !== 'string'
      || !hash(value.policy.fingerprint) || value.policy.nativeToolConfirmationSeparate !== true
      || typeof value.nativeToolConfirmationRequired !== 'boolean'
      || value.ownerSubmissionSupported !== undefined && typeof value.ownerSubmissionSupported !== 'boolean'
      || value.ownerSubmissionSupported === true && (value.reviewRequired || value.reviewRequestSupported !== false)) throw new Error('当前方案授权无法核对。');
  return value;
}
export function recoverPlanReviews(values: unknown, ownerId: string, plan: Pick<Plan, 'id' | 'fingerprint'>, authorization: PlanAuthorization) {
  checkedAuthorization(authorization);
  if (!Array.isArray(values) || values.length > 100) throw new Error('审查列表无法核对。');
  const reviews = values.map(checkedReview);
  if (reviews.some(item => item.ownerId !== ownerId) || new Set(reviews.map(item => item.id)).size !== reviews.length) throw new Error('审查列表归属或标识不一致。');
  const matching = reviews.filter(item => item.planId === plan.id);
  if (matching.some(item => item.planFingerprint !== plan.fingerprint || !item.planIntegrityMatches)
      || new Set(matching.map(item => item.planDigest)).size > 1) throw new Error('审查与当前不可变方案不一致。');
  const current = matching.filter(item => item.currentPolicy && item.policyRevision === authorization.policy.revision && item.policyDigest === authorization.policy.fingerprint);
  if (matching.some(item => item.currentPolicy && !current.includes(item))) throw new Error('审查与当前策略指纹不一致。');
  const pending = current.filter(item => item.decision === 'pending' && !item.expired);
  const latest = (items: CheckedPlanReview[]) => [...items].sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt) || a.id.localeCompare(b.id))[0];
  const review = latest(pending) ?? latest(current.filter(item => item.approvalEffective)) ?? latest(current) ?? latest(matching);
  // A bounded list cannot prove absence of an older pending request.
  const canRequest = !pending.length && !current.some(item => item.approvalEffective) && values.length < 100 && !authorization.executionAllowed && authorization.reviewRequired;
  return { review, pending: pending.length > 0, canRequest, truncated: values.length === 100 };
}

/** One explicit request; an uncertain reply is reconciled by GET, never another POST. */
export async function requestReviewOnce(request: () => Promise<unknown>, list: () => Promise<unknown>, check: (value: unknown) => CheckedPlanReview, requestId: string) {
  try { const result = check(await request()); if (result.requestId !== requestId) throw new Error('审查请求标识不一致。'); return result; }
  catch (error) {
    try {
      const values = await list();
      if (Array.isArray(values)) {
        const raw = values.find(item => record(item) && item.requestId === requestId);
        const found = raw === undefined ? undefined : check(raw);
        if (found) return found;
      }
    } catch { /* Preserve the uncertain original request. */ }
    throw error;
  }
}
