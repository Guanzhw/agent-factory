import { describe, expect, it, vi } from 'vitest';
import { recoverComposerProposal } from '../web/ApplicationComposer.js';
import type { AssemblyCandidate, AssemblyProposal, Plan } from '../web/models.js';

const first = '11111111-1111-4111-8111-111111111111';
const second = '22222222-2222-4222-8222-222222222222';
const applicationRef = { id: 'public-fixture', version: 1, sha256: 'a'.repeat(64) };
function candidate(): AssemblyCandidate {
  return { application: applicationRef.id, applicationRef, mode: 'literature', normalizedGoal: '比较公开证据',
    materialRefs: [], materials: [], tools: ['read_source'], capabilities: ['read:public'],
    budget: { toolCalls: 8, maxDepth: 2, maxChildren: 4, experimentSeconds: 8, outputBytes: 65536 },
    config: { internalOption: 'fixture-only' }, instructions: 'Bounded fixture', status: 'blocked', missing: ['请选择必需的模型连接'],
    policy: {}, syntheticFixture: true, executionBindings: { model: { adapterId: 'fixture-model', revision: 'r1' } },
    bindingManifest: {}, fingerprint: 'b'.repeat(64) };
}
function proposal(id = first): AssemblyProposal {
  return { id, ownerId: 'alice', createdAt: '2026-10-08T00:00:00Z', parentId: null, input: { goal: '比较公开证据' },
    candidate: candidate(), selection: { method: 'explicit-application', matchedKeywords: [] }, fingerprint: 'c'.repeat(64),
    state: 'pending', planId: null, allowedActions: ['revise', 'accept', 'reject'] };
}
describe('explicit proposal recovery', () => {
  it('follows an owner-matched revision chain and returns the original accepted plan', async () => {
    const parent = { ...proposal(), state: 'revised' as const, revisedBy: second };
    const plan: Plan = { id: 'plan-fixture', fingerprint: 'd'.repeat(64), normalizedGoal: '比较公开证据', materialRefs: [], capabilities: [], missing: [], status: 'ready', createdAt: '2026-10-08T00:00:00Z' };
    const child = { ...proposal(second), parentId: first, state: 'accepted' as const, planId: plan.id };
    const result = { proposal: child, plan };
    const load = vi.fn().mockResolvedValueOnce({ proposal: parent, plan: null }).mockResolvedValueOnce(result);
    expect(await recoverComposerProposal('alice', first, load)).toBe(result);
    expect(load.mock.calls).toEqual([[first], [second]]);
  });
  it('rejects owner, record-id and predecessor mismatches before accepting a recovered record', async () => {
    for (const change of [{ ownerId: 'bob' }, { id: second }]) {
      const load = vi.fn().mockResolvedValue({ proposal: { ...proposal(), ...change }, plan: null });
      await expect(recoverComposerProposal('alice', first, load)).rejects.toThrow('无法核对');
      expect(load).toHaveBeenCalledTimes(1);
    }
    const load = vi.fn().mockResolvedValueOnce({ proposal: { ...proposal(), state: 'revised', revisedBy: second }, plan: null })
      .mockResolvedValueOnce({ proposal: { ...proposal(second), parentId: 'foreign-parent' }, plan: null });
    await expect(recoverComposerProposal('alice', first, load)).rejects.toThrow('无法核对');
  });
  it('does not follow malformed, absent or cyclic revision pointers', async () => {
    for (const revisedBy of [undefined, '../foreign', first]) {
      const load = vi.fn().mockResolvedValue({ proposal: { ...proposal(), state: 'revised', revisedBy }, plan: null });
      await expect(recoverComposerProposal('alice', first, load)).rejects.toThrow('无法核对');
      expect(load).toHaveBeenCalledTimes(1);
    }
    const load = vi.fn();
    await expect(recoverComposerProposal('alice', 'not-a-pointer', load)).rejects.toThrow('无法核对');
    expect(load).not.toHaveBeenCalled();
  });
  it('bounds revision traversal and reports a recoverable history choice instead of accepting an unresolved revision', async () => {
    const ids = Array.from({ length: 11 }, (_, i) => `${String(i).padStart(8, '0')}-1111-4111-8111-111111111111`);
    const load = vi.fn(async (id: string) => { const index = ids.indexOf(id); return { proposal: { ...proposal(id), state: 'revised' as const, parentId: index ? ids[index - 1] : null, revisedBy: ids[index + 1] }, plan: null }; });
    await expect(recoverComposerProposal('alice', ids[0], load)).rejects.toThrow('选择较新的提案');
    expect(load).toHaveBeenCalledTimes(9);
  });
});
