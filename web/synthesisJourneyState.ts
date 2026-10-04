import { literatureEvidenceState, type LiteratureEvidence } from './literatureEvidenceState.js';
export interface SynthesisPreview {
  schema: 1; sourceTaskId: string; sourcePlanId: string; sourcePlanFingerprint: string; sourceRunId: string;
  artifacts: { id: string; sha256: string; size: number }[]; projection: LiteratureEvidence; fingerprint: string;
}
export interface SynthesisSnapshot extends Omit<SynthesisPreview, 'fingerprint'> {
  id: string; ownerId: string; createdAt: string; requestId: string; question: string; sourceIds: string[];
  sourceFingerprint: string; contextFingerprint: string; fingerprint: string;
}
export interface SynthesisCreate { sourceTaskId: string; sourceIds: string[]; question: string; expectedFingerprint: string; requestId: string }
export interface SynthesisPage { schema: 1; ownerId: string; items: SynthesisSnapshot[]; nextCursor: string | null; snapshot: false }
export interface SynthesisJourneyApi {
  preview: (taskId: string, signal?: AbortSignal) => Promise<unknown>;
  list: (taskId: string, after?: string, signal?: AbortSignal) => Promise<unknown>;
  inspect: (id: string, signal?: AbortSignal) => Promise<unknown>;
  current: (id: string, signal?: AbortSignal) => Promise<unknown>;
  create: (input: SynthesisCreate) => Promise<unknown>;
}
const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const id = (v: unknown): v is string => typeof v === 'string' && /^[A-Za-z0-9_.:~-]{1,128}$/.test(v);
const hash = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);
const invalid = () => new Error('来源、快照身份或不可变指纹无法核对。');
export function synthesisPreview(value: unknown, taskId: string, owner?: string): SynthesisPreview {
  if (!record(value) || value.schema !== 1 || owner !== undefined && value.ownerId !== owner || value.sourceTaskId !== taskId || !id(value.sourceTaskId) || !id(value.sourcePlanId) || !id(value.sourceRunId)
      || !hash(value.sourcePlanFingerprint) || !hash(value.fingerprint) || !Array.isArray(value.artifacts) || value.artifacts.length !== 2
      || value.artifacts.some(a => !record(a) || !id(a.id) || !hash(a.sha256) || !Number.isSafeInteger(a.size) || Number(a.size) <= 0)
      || new Set(value.artifacts.map(a => a.id)).size !== 2) throw invalid();
  const artifacts = value.artifacts;
  const projection = literatureEvidenceState(value.projection);
  if (projection.kind !== 'verified' || projection.evidence.status !== 'ready'
      || ![projection.evidence.reportArtifactId, projection.evidence.bundleArtifactId].every(key => artifacts.some(a => a.id === key))) throw invalid();
  return { ...value, projection: projection.evidence } as unknown as SynthesisPreview;
}
export function synthesisSnapshot(value: unknown, owner: string, taskId: string, snapshotId?: string): SynthesisSnapshot {
  const base = synthesisPreview(value, taskId, owner);
  if (!record(value) || !id(value.id) || snapshotId !== undefined && value.id !== snapshotId || value.ownerId !== owner || !id(value.requestId)
      || typeof value.createdAt !== 'string' || !Number.isFinite(Date.parse(value.createdAt)) || typeof value.question !== 'string'
      || !value.question.trim() || [...value.question].length > 1000 || !hash(value.sourceFingerprint) || !hash(value.contextFingerprint)
      || !Array.isArray(value.sourceIds) || value.sourceIds.length !== base.projection.sourceCount
      || value.sourceIds.some((v, i) => v !== base.projection.sources[i].sourceId)) throw invalid();
  return { ...value, ...base } as unknown as SynthesisSnapshot;
}
export function synthesisPage(value: unknown, owner: string, taskId: string): SynthesisPage {
  if (!record(value) || value.schema !== 1 || value.ownerId !== owner || value.snapshot !== false
      || !Array.isArray(value.items) || value.items.length > 20 || !(value.nextCursor === null || id(value.nextCursor))) throw invalid();
  const items = value.items.map(item => synthesisSnapshot(item, owner, taskId));
  if (new Set(items.map(item => item.id)).size !== items.length || value.nextCursor !== null && value.nextCursor !== items.at(-1)?.id) throw invalid();
  return { schema: 1, ownerId: owner, items, nextCursor: value.nextCursor, snapshot: false };
}
export function validateSnapshotReply(value: unknown, owner: string, input: SynthesisCreate): SynthesisSnapshot {
  const result = synthesisSnapshot(value, owner, input.sourceTaskId);
  if (result.requestId !== input.requestId || result.question !== input.question.trim() || result.sourceFingerprint !== input.expectedFingerprint
      || result.sourceIds.length !== input.sourceIds.length || !result.sourceIds.every(id => input.sourceIds.includes(id))) throw invalid();
  return result;
}
/** Serializes mutation entry and invalidates all old-owner asynchronous responses. */
export class SynthesisJourneyGuard {
  private scope = ''; private epoch = 0; private claimed = false;
  enter(owner: string, task: string) { const scope = JSON.stringify([owner, task]); if (scope !== this.scope) { this.scope = scope; this.epoch++; this.claimed = false; } return this.epoch; }
  current(epoch: number) { return this.epoch === epoch; }
  claim(epoch: number) { if (!this.current(epoch) || this.claimed) return false; this.claimed = true; return true; }
  release(epoch: number) { if (this.current(epoch)) this.claimed = false; }
}
export function synthesisPointerKey(owner: string, taskId: string) { return `factory-synthesis-request-v1:${encodeURIComponent(owner)}:${encodeURIComponent(taskId)}`; }
export function pendingSynthesisRequest(value: string | null): string | undefined { return value && id(value) ? value : undefined; }

/** A lost create reply permits a scoped history read, never an automatic retry. */
export async function saveSynthesisOnce(api: Pick<SynthesisJourneyApi, 'create' | 'list'>, owner: string, input: SynthesisCreate): Promise<SynthesisSnapshot> {
  try { return validateSnapshotReply(await api.create(input), owner, input); }
  catch (error) {
    try {
      const page = synthesisPage(await api.list(input.sourceTaskId), owner, input.sourceTaskId);
      const found = page.items.find(item => item.requestId === input.requestId);
      if (found) return validateSnapshotReply(found, owner, input);
    } catch { /* Keep the original uncertainty and original request pointer. */ }
    throw error;
  }
}
