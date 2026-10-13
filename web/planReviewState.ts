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
/** Authorization must refer to this owner and this exact immutable plan, never a name exemption. */
export function checkedPlanAuthorization(value: PlanAuthorization, ownerId: string, plan: Pick<Plan, 'id' | 'fingerprint'>): PlanAuthorization {
  const state = checkedAuthorization(value);
  if (state.ownerId !== ownerId || state.planId !== plan.id || state.planFingerprint !== plan.fingerprint) throw new Error('当前身份或方案范围无法核对。');
  return state;
}
