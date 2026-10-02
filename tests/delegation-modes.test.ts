import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '../web/api.js';
import { delegationModes } from '../web/delegationModes.js';
import type { DelegationScope } from '../web/models.js';

afterEach(() => vi.unstubAllGlobals());
const scope = (modes?: string[], defaultMode?: string | null): DelegationScope => ({ allowed: true, parentTaskId: 'parent', rootTaskId: 'parent', depth: 0, capabilities: ['checksum:read'], tools: ['checksum'], budget: {}, sharedBudget: { toolCallsUsed: 0, toolCallsLimit: 8, childrenUsed: 0, childrenLimit: 4, maxDepth: 2 }, ...(modes === undefined ? {} : { modes, defaultMode }) });

describe('immutable parent application delegation choices', () => {
  it('selects only server-projected exact parent modes and never adds legacy choices', () => {
    expect(delegationModes(scope(['direct', 'paused'], 'paused'), 'literature', false)).toEqual({ modes: ['direct', 'paused'], selected: 'paused', available: true, legacy: false });
    expect(delegationModes(scope(['direct', 'paused'], 'paused'), 'direct', false).selected).toBe('direct');
  });
  it('fails closed on explicitly empty, malformed or contradictory current choices', () => {
    for (const current of [scope([], null), scope(['direct', 'direct'], 'direct'), scope(['direct'], 'foreign'), scope(['direct', '../unsafe'], 'direct')]) {
      expect(delegationModes(current, 'literature', false).available).toBe(false);
    }
    expect(delegationModes(undefined, 'literature', false).available).toBe(false);
    expect(delegationModes(scope(), 'literature', false)).toMatchObject({ modes: ['literature', 'experiment'], available: true, legacy: true });
  });
  it('does not silently replace the mode of an uncertain retained request after scope changes', () => {
    expect(delegationModes(scope(['direct'], 'direct'), 'paused', true)).toEqual({ modes: ['direct'], selected: 'paused', available: false, legacy: false });
    expect(delegationModes(scope(['direct'], 'direct'), 'paused', false).selected).toBe('direct');
  });
  it('preserves the selected custom mode and original request key on explicit child retry', async () => {
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ duplicate: true, job: { id: 'parent~child' } }), { status: 202 })));
    vi.stubGlobal('fetch', fetch);
    await api.createChild('parent', 'Bounded controlled child', 'paused', 'original-child-key');
    await api.createChild('parent', 'Bounded controlled child', 'paused', 'original-child-key');
    expect(fetch.mock.calls.map(call => JSON.parse(call[1].body))).toEqual([{ goal: 'Bounded controlled child', mode: 'paused', requestId: 'original-child-key' }, { goal: 'Bounded controlled child', mode: 'paused', requestId: 'original-child-key' }]);
  });
});
