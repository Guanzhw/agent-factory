export interface IterationCaps { rounds: number; toolCalls: number; tokenLimit: number | null; amountMicros: number | null; currency: string | null }
export interface IterationPreset { id: string; name: string; ready: boolean; blockers: string[]; roundCaps: IterationCaps; roundSeconds: number; defaultTotalSeconds: number; baseline: { metric: string; value: number; kind: string } }
export interface IterationStart { presetId: string; goal: string; requestId: string; caps: IterationCaps; deadline: number }
interface Baseline { kind: string; metricValue: number; sha256: string; taskId?: string; artifactId?: string }
export interface IterationSnapshot {
  activity: { id: string; ownerId: string; requestId: string; goal: string; status: string; stopReason: string | null; currentRoundId: string; cancelRequested: boolean; caps: IterationCaps; deadline: number; baselineSource: Baseline; advanceRequests?: Record<string, string> };
  rounds: { id: string; ordinal: number; previousRoundId: string | null; state: string; taskId: string; baselineSource: Baseline; decision?: string; observation: { approvalRequired?: boolean; evaluation?: { candidateValue: number } } | null }[];
  budget: { allocatedRounds: number; heldToolCalls: number; settledToolCalls: number; metering: string; usage: { held_tokens: number; settled_tokens: number; held_amount: number; settled_amount: number } | null; allocations: { state: string }[] };
}
export type IterationPending = { owner: string; kind: 'start'; body: IterationStart } | { owner: string; kind: 'advance'; activityId: string; body: { previousRoundId: string; requestId: string } };
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const number = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value) && value >= 0;
export function iterationCaps(value: unknown): value is IterationCaps {
  return record(value) && Object.keys(value).length === 5 && Number.isSafeInteger(value.rounds) && Number(value.rounds) > 0 && Number(value.rounds) <= 2 && Number.isSafeInteger(value.toolCalls) && Number(value.toolCalls) >= 0
    && (value.tokenLimit === null || number(value.tokenLimit)) && (value.amountMicros === null || number(value.amountMicros)) && (value.currency === null || typeof value.currency === 'string');
}
export function defaultIterationCaps(preset: IterationPreset): IterationCaps {
  return { rounds: 2, toolCalls: preset.roundCaps.toolCalls * 2, tokenLimit: preset.roundCaps.tokenLimit === null ? null : preset.roundCaps.tokenLimit * 2, amountMicros: preset.roundCaps.amountMicros === null ? null : preset.roundCaps.amountMicros * 2, currency: preset.roundCaps.currency };
}
export function iterationPresets(value: unknown): IterationPreset[] {
  if (!Array.isArray(value) || value.some(p => !record(p) || typeof p.id !== 'string' || typeof p.name !== 'string' || typeof p.ready !== 'boolean' || !Array.isArray(p.blockers) || !p.blockers.every(b => typeof b === 'string') || !iterationCaps(p.roundCaps) || !number(p.roundSeconds) || !number(p.defaultTotalSeconds) || !record(p.baseline) || !number(p.baseline.value))) throw new Error('Invalid iteration presets');
  return value as IterationPreset[];
}
export function iterationSnapshot(value: unknown, owner: string): IterationSnapshot {
  if (!record(value) || !record(value.activity) || value.activity.ownerId !== owner || typeof value.activity.id !== 'string' || typeof value.activity.requestId !== 'string' || !iterationCaps(value.activity.caps) || !record(value.activity.baselineSource) || !number(value.activity.baselineSource.metricValue) || !Array.isArray(value.rounds) || value.rounds.some(r => !record(r) || typeof r.id !== 'string' || typeof r.taskId !== 'string' || !record(r.baselineSource) || !number(r.baselineSource.metricValue)) || !record(value.budget) || !Array.isArray(value.budget.allocations) || !number(value.budget.heldToolCalls) || !number(value.budget.settledToolCalls)) throw new Error('Invalid iteration snapshot');
  return value as unknown as IterationSnapshot;
}
export function readIterationPending(raw: string | null, owner: string): IterationPending | null {
  try {
    const p = JSON.parse(raw ?? 'null');
    if (!record(p) || p.owner !== owner || !record(p.body) || typeof p.body.requestId !== 'string' || !p.body.requestId) return null;
    if (p.kind === 'start' && typeof p.body.presetId === 'string' && typeof p.body.goal === 'string' && iterationCaps(p.body.caps) && number(p.body.deadline)) return p as unknown as IterationPending;
    if (p.kind === 'advance' && typeof p.activityId === 'string' && typeof p.body.previousRoundId === 'string') return p as unknown as IterationPending;
  } catch { /* An invalid stored request must never be submitted. */ }
  return null;
}
