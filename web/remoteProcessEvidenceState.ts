import type { JobDetail } from './models.js';
import { processLeaseView, type ProcessLease } from './processLeaseView.js';
import { remoteHandoffState } from './remoteHandoffState.js';

export interface RemoteProcessLease extends ProcessLease {
  poolId: string; poolFingerprint: string;
  limits: { cpu: number; memoryMb: number; diskMb: number; seconds: number };
}
export type RemoteProcessEvidenceState = { kind: 'missing' } | { kind: 'invalid' } | {
  kind: 'verified'; receiverOwner: string; receiverTaskId: string; receiverRunId: string; receiverPlanId: string;
  leases: RemoteProcessLease[];
};
const record = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value);
const identifier = (value: unknown): value is string => typeof value === 'string' && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$/.test(value);
const hash = (value: unknown) => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const positive = (value: unknown) => typeof value === 'number' && Number.isSafeInteger(value) && value > 0 && value <= 2 ** 31;

export function remoteProcessEvidenceState(detail: JobDetail): RemoteProcessEvidenceState {
  const receipt = detail.snapshot?.remoteHandoff;
  const raw = record(receipt) ? receipt.processLeases : undefined;
  if (raw === undefined || raw === null) return { kind: 'missing' };
  const handoff = remoteHandoffState(detail);
  if (handoff.kind !== 'execution') return { kind: 'invalid' };
  const evidence = handoff.evidence;
  if (!record(receipt) || receipt.state !== 'ACCEPTED' || evidence.state !== 'ACCEPTED' || !evidence.receiverTaskId || !evidence.receiverRunId
      || detail.job.id !== evidence.originTaskId
      || detail.job.executionPlacement?.remoteTaskId !== evidence.receiverTaskId
      || detail.job.executionPlacement.remoteRunId !== evidence.receiverRunId
      || !record(raw) || Object.keys(raw).length !== 3 || raw.schema !== 1 || raw.complete !== true
      || !Array.isArray(raw.leases) || raw.leases.length > 1) return { kind: 'invalid' };
  const leases: RemoteProcessLease[] = [];
  for (const item of raw.leases) {
    if (!record(item)) return { kind: 'invalid' };
    const view = processLeaseView(item, evidence.receiverOwner);
    if (view.kind !== 'verified' || view.lease.localTaskId !== evidence.receiverTaskId
        || view.lease.nativeRunId !== evidence.receiverRunId || view.lease.planId !== evidence.receiverPlanId
        || !identifier(item.poolId) || !hash(item.poolFingerprint) || !record(item.limits)
        || Object.keys(item.limits).length !== 4
        || !['cpu', 'memoryMb', 'diskMb', 'seconds'].every(key => positive(item.limits && (item.limits as Record<string, unknown>)[key]))) return { kind: 'invalid' };
    leases.push({ ...view.lease, poolId: item.poolId, poolFingerprint: item.poolFingerprint as string,
      limits: { cpu: Number(item.limits.cpu), memoryMb: Number(item.limits.memoryMb), diskMb: Number(item.limits.diskMb), seconds: Number(item.limits.seconds) } });
  }
  if (new Set(leases.map(lease => lease.id)).size !== leases.length) return { kind: 'invalid' };
  return { kind: 'verified', receiverOwner: evidence.receiverOwner, receiverTaskId: evidence.receiverTaskId,
    receiverRunId: evidence.receiverRunId, receiverPlanId: evidence.receiverPlanId, leases };
}
