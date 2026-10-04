import { describe, expect, it } from 'vitest';
import { savedApplicationMatches } from '../web/applicationGovernanceState.js';
import type { FactoryApplication } from '../web/models.js';
const saved = { id: 'new-id', version: 1, sha256: 'a'.repeat(64), name: '应用', modes: { literature: { budget: { toolCalls: 8, maxDepth: 2 }, capabilities: ['read'], materialRefs: [{ id: 'tool', version: 1, sha256: 'b'.repeat(64) }] } } } as unknown as FactoryApplication;
const body = { name: '应用', modes: { literature: { budget: { toolCalls: 8 }, capabilities: ['read'], materialRefs: [{ id: 'tool', version: 1, sha256: 'b'.repeat(64) }] } } };
describe('application draft receipt matches original intent', () => {
  it('allows only omitted service defaults and a new generated lineage', () => {
    expect(savedApplicationMatches(body, undefined, saved)).toBe(true);
    expect(savedApplicationMatches({ ...body, id: null }, undefined, saved)).toBe(true);
    expect(savedApplicationMatches(body, undefined, { ...saved, sha256: 'bad' })).toBe(false);
    expect(savedApplicationMatches(body, saved, { ...saved, version: NaN })).toBe(false);
    expect(savedApplicationMatches(body, undefined, { ...saved, version: 2 })).toBe(false);
    expect(savedApplicationMatches(body, undefined, { ...saved, name: '其他' })).toBe(false);
  });
  it('rejects additional modes, changed pins, and enlarged submitted capabilities', () => {
    const alternatives: FactoryApplication['modes'][] = [{ ...saved.modes, other: saved.modes.literature }, { literature: { ...saved.modes.literature, capabilities: ['read', 'write'] } }, { literature: { ...saved.modes.literature, materialRefs: [{ id: 'tool', version: 2, sha256: 'b'.repeat(64) }] } }];
    for (const modes of alternatives) expect(savedApplicationMatches(body, undefined, { ...saved, modes })).toBe(false);
  });
  it('requires the revision original lineage and a later version', () => {
    expect(savedApplicationMatches(body, saved, saved)).toBe(false);
    expect(savedApplicationMatches(body, saved, { ...saved, version: 2 })).toBe(true);
    expect(savedApplicationMatches(body, saved, { ...saved, id: 'wrong', version: 2 })).toBe(false);
  });
});
