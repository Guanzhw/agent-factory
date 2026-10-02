import type { JobDetail, MaterialReference } from './models.js';

export interface RemoteBindingEvidence {
  kind: 'model' | 'environment' | 'tool' | 'knowledge'; materialRef: MaterialReference;
  sourceAdapter: string; sourceRevision: string; receiverAdapter: string; receiverRevision: string;
  mappingReference: string | null; mappingRevision: string | null; mappingSha256: string | null;
}
export interface RemoteHandoffEvidence {
  receiptId: string; originRef: string; originTaskId: string; sourceOwner: string; receiverOwner: string;
  receiverPlanId: string; sourcePlanId?: string; requestId: string; manifestHash: string;
  receiverTaskId: string | null; receiverRunId: string | null; state: string;
  proofHash: string; sourceConfiguration: { revision: string; sha256: string };
  receiverConfiguration: { revision: string; sha256: string }; bindings: RemoteBindingEvidence[];
}
export type RemoteHandoffState = { kind: 'none' } | { kind: 'invalid'; message: string }
  | { kind: 'pending' | 'execution'; evidence: RemoteHandoffEvidence };

const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const identifier = (value: unknown): value is string => typeof value === 'string' && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$/.test(value);
const ownerIdentity = (value: unknown): value is string => typeof value === 'string' && Array.from(value).length >= 1 && Array.from(value).length <= 200 && Array.from(value).every(char => char.charCodeAt(0) >= 32 && char.charCodeAt(0) !== 127);
const uuid = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(value);
const hash = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const pin = (value: unknown): value is Record<string, unknown> & MaterialReference => object(value) && identifier(value.id) && Number.isSafeInteger(value.version) && Number(value.version) > 0 && hash(value.sha256);
function configuration(value: unknown): value is { revision: string; sha256: string } {
  return object(value) && Object.keys(value).length === 2 && identifier(value.revision) && hash(value.sha256);
}
function specification(value: unknown): value is Record<string, unknown> & { materialRef: MaterialReference; adapterId: string; revision: string } {
  return object(value) && Object.keys(value).every(key => ['materialRef', 'adapterId', 'revision', 'config', 'connection', 'toolName'].includes(key))
    && pin(value.materialRef) && identifier(value.adapterId) && identifier(value.revision) && object(value.config);
}
const unavailable = (): RemoteHandoffState => ({ kind: 'invalid', message: '远端审查或绑定凭据无法核对。请核对执行状态；暂时不能继续或批准工具调用。' });

export function remoteHandoffState(detail: JobDetail): RemoteHandoffState {
  const raw = detail.snapshot?.remoteHandoff;
  const placement = detail.job.executionPlacement;
  const signaled = detail.snapshot?.receiverReviewRequired === true || placement?.state === 'PREPARING' || object(raw) && raw.state === 'PREPARING';
  if (!raw && !signaled && placement?.kind !== 'remote-factory') return { kind: 'none' };
  if (!object(raw) || placement?.kind !== 'remote-factory' || !identifier(placement.targetRef) || !uuid(placement.originTaskId)
      || !(detail.job.id === placement.originTaskId || detail.job.id.startsWith(`${placement.originTaskId}~`))
      || !uuid(raw.id) || !identifier(raw.originRef) || raw.originTaskId !== placement.originTaskId || !ownerIdentity(raw.originOwnerId) || raw.originOwnerId !== detail.job.ownerId
      || !ownerIdentity(raw.remoteOwnerId) || !identifier(raw.requestId) || !uuid(raw.remotePlanId) || !hash(raw.manifestHash)
      || !(raw.remoteTaskId === null || uuid(raw.remoteTaskId)) || !(raw.remoteRunId === null || uuid(raw.remoteRunId))
      || !['PREPARING', 'PREPARED', 'UNKNOWN', 'ACCEPTED', 'CANCELLED_NO_DISPATCH'].includes(String(raw.state))) return unavailable();
  const proof = raw.receiverBindingProof;
  const expected = ['schema', 'originRef', 'receiptId', 'originTaskId', 'originOwner', 'receiverOwner', 'receiverPlanId', 'manifestHash', 'sourceConfiguration', 'receiverConfiguration', 'entries', 'sha256'];
  if (!object(proof) || Object.keys(proof).length !== expected.length || !Object.keys(proof).every(key => expected.includes(key))
      || proof.schema !== 1 || proof.originRef !== raw.originRef || proof.receiptId !== raw.id || proof.originTaskId !== raw.originTaskId
      || proof.originOwner !== raw.originOwnerId || proof.receiverOwner !== raw.remoteOwnerId || proof.receiverPlanId !== raw.remotePlanId
      || proof.manifestHash !== raw.manifestHash || !hash(proof.sha256) || !configuration(proof.sourceConfiguration) || !configuration(proof.receiverConfiguration)
      || !Array.isArray(proof.entries) || proof.entries.length < 2 || proof.entries.length > 30) return unavailable();
  const bindings: RemoteBindingEvidence[] = [];
  for (const entry of proof.entries) {
    if (!object(entry) || !['model', 'environment', 'tool', 'knowledge'].includes(String(entry.kind)) || !specification(entry.sourceSpec) || !specification(entry.effectiveSpec)
        || entry.sourceSpec.materialRef.id !== entry.effectiveSpec.materialRef.id || entry.sourceSpec.materialRef.version !== entry.effectiveSpec.materialRef.version
        || entry.sourceSpec.materialRef.sha256 !== entry.effectiveSpec.materialRef.sha256
        || !(entry.mappingReference === null && entry.mappingRevision === null && entry.mappingSha256 === null
          || identifier(entry.mappingReference) && identifier(entry.mappingRevision) && hash(entry.mappingSha256))) return unavailable();
    bindings.push({ kind: entry.kind as RemoteBindingEvidence['kind'], materialRef: { id: entry.sourceSpec.materialRef.id, version: entry.sourceSpec.materialRef.version, sha256: entry.sourceSpec.materialRef.sha256 },
      sourceAdapter: entry.sourceSpec.adapterId, sourceRevision: entry.sourceSpec.revision,
      receiverAdapter: entry.effectiveSpec.adapterId, receiverRevision: entry.effectiveSpec.revision,
      mappingReference: entry.mappingReference as string | null, mappingRevision: entry.mappingRevision as string | null, mappingSha256: entry.mappingSha256 as string | null });
  }
  if (bindings.filter(item => item.kind === 'model').length !== 1 || bindings.filter(item => item.kind === 'environment').length !== 1) return unavailable();
  if (signaled && (detail.snapshot?.receiverReviewRequired !== true || raw.state !== 'PREPARING' || detail.job.status !== 'waiting_approval'
      || detail.job.id !== raw.originTaskId || raw.remoteTaskId !== null || raw.remoteRunId !== null || placement.remoteTaskId)) return unavailable();
  return { kind: signaled ? 'pending' : 'execution', evidence: { receiptId: raw.id, originRef: raw.originRef, originTaskId: placement.originTaskId,
    sourceOwner: String(raw.originOwnerId), receiverOwner: raw.remoteOwnerId, sourcePlanId: detail.job.planId, receiverPlanId: raw.remotePlanId,
    requestId: raw.requestId, manifestHash: raw.manifestHash, receiverTaskId: raw.remoteTaskId, receiverRunId: raw.remoteRunId, state: String(raw.state),
    proofHash: proof.sha256, sourceConfiguration: proof.sourceConfiguration, receiverConfiguration: proof.receiverConfiguration, bindings } };
}

export function nativeInteractionAvailable(detail: JobDetail): boolean {
  const state = remoteHandoffState(detail);
  return state.kind === 'none' || state.kind === 'execution' && state.evidence.receiverTaskId !== null;
}
