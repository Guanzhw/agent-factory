import type { DelegationScope } from './models.js';

export interface DelegationModes { modes: string[]; selected: string; available: boolean; legacy: boolean }
const valid = (value: unknown): value is string => typeof value === 'string' && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$/.test(value);
export function delegationModes(scope: DelegationScope | undefined, draftMode: string, retainedRequest: boolean): DelegationModes {
  const legacy = !!scope && !Object.hasOwn(scope, 'modes');
  const raw = legacy ? ['literature', 'experiment'] : scope?.modes;
  if (!Array.isArray(raw) || raw.length > 30 || raw.some(mode => !valid(mode)) || new Set(raw).size !== raw.length
    || scope?.defaultMode != null && (!valid(scope.defaultMode) || !raw.includes(scope.defaultMode))) {
    return { modes: [], selected: retainedRequest ? draftMode : '', available: false, legacy };
  }
  const selected = retainedRequest || raw.includes(draftMode) ? draftMode : scope?.defaultMode ?? raw[0] ?? '';
  return { modes: raw, selected, available: raw.includes(selected), legacy };
}
export const delegationModeName = (mode: string): string => ({ literature: '文献与证据', experiment: '实验探索' } as Record<string, string>)[mode] ?? mode;
