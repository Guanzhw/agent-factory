import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, validateControlReceipt } from '../web/api.js';
import { adoptCommandPointer, decisionFingerprint, forgetCommandPointer, pendingCommandPointers, persistCommandPointer } from '../web/controlCommandStorage.js';
import type { ControlReceipt } from '../web/models.js';

class MemoryStorage implements Storage {
  private values = new Map<string, string>();
  get length() { return this.values.size; }
  clear() { this.values.clear(); }
  getItem(k: string) { return this.values.get(k) ?? null; }
  key(i: number) { return [...this.values.keys()][i] ?? null; }
  removeItem(k: string) { this.values.delete(k); }
  setItem(k: string, v: string) { this.values.set(k, v); }
}
afterEach(() => vi.unstubAllGlobals());
const decision = { action: 'answer' as const, requirementId: 'question', version: 12, answer: 'Private answer body' };
async function receipt(): Promise<ControlReceipt> {
  return { commandId: 'original-command', ownerId: 'alice', taskId: 'task', action: 'answer', fingerprint: 'a'.repeat(64),
    decisionSha256: await decisionFingerprint(decision), binding: { ownerId: 'alice', taskId: 'task', kind: 'native', runId: 'run' },
    requirementId: 'question', version: 12, approved: null, state: 'DECISION_RECORDED', intentRecorded: true,
    decisionRecorded: true, executionContinuing: false, stopConfirmed: false, canDispatch: false, acknowledged: false,
    createdAt: '2026-10-02T00:00:00Z', updatedAt: '2026-10-02T00:00:01Z', evidence: { kind: 'native-continuation' }, error: null };
}
describe('durable control references', () => {
  it('survives a fresh caller and identity switch without persisting the answer or credentials', async () => {
    const storage = new MemoryStorage();
    const first = await persistCommandPointer('alice', 'task', decision, storage);
    const restarted = await persistCommandPointer('alice', 'task', decision, storage);
    expect(restarted.commandId).toBe(first.commandId);
    expect(pendingCommandPointers('bob', storage)).toEqual([]);
    expect(pendingCommandPointers('alice', storage)).toEqual([first]);
    const raw = storage.getItem(storage.key(0)!);
    expect(raw).not.toContain(decision.answer);
    expect(raw).not.toContain('"answer":');
    expect(raw).not.toMatch(/authorization|credential|token|cookie/i);
    await expect(persistCommandPointer('alice', 'task', { ...decision, answer: 'changed' }, storage)).rejects.toThrow('不能用新内容覆盖');
    forgetCommandPointer({ ...first, ownerId: 'bob' }, storage);
    expect(pendingCommandPointers('alice', storage)).toEqual([first]);
    forgetCommandPointer(first, storage);
    expect(pendingCommandPointers('alice', storage)).toEqual([]);
  });
  it('adopts only an exact owner/task/decision receipt when concurrent tabs chose different IDs', async () => {
    const storage = new MemoryStorage();
    const original = await persistCommandPointer('alice', 'task', decision, storage);
    const proof = await receipt();
    adoptCommandPointer({ ...proof, decisionSha256: 'b'.repeat(64) }, storage);
    expect(pendingCommandPointers('alice', storage)[0].commandId).toBe(original.commandId);
    adoptCommandPointer(proof, storage);
    expect(pendingCommandPointers('alice', storage)[0].commandId).toBe(proof.commandId);
  });
  it('refuses a new submit if the reference cannot be durably stored', async () => {
    const storage = new MemoryStorage();
    vi.spyOn(storage, 'setItem').mockImplementation(() => { throw new Error('storage unavailable'); });
    await expect(persistCommandPointer('alice', 'task', decision, storage)).rejects.toThrow('storage unavailable');
  });
});
describe('command acknowledgement recovery', () => {
  it('uses one POST then only the original receipt GET after response loss', async () => {
    const proof = await receipt();
    const fetch = vi.fn().mockRejectedValueOnce(new TypeError('lost reply'))
      .mockResolvedValueOnce(new Response(JSON.stringify(proof)));
    vi.stubGlobal('fetch', fetch);
    await expect(api.submitControl('alice', 'task', { ...decision, commandId: proof.commandId })).resolves.toEqual(proof);
    expect(fetch.mock.calls.map(c => c[1].method)).toEqual(['POST', 'GET']);
    expect(fetch.mock.calls[1][0]).toBe('/api/factory/jobs/task/commands/original-command');
  });
  it('keeps missing or mismatched native proof unknown instead of guessing from a job result', async () => {
    const proof = await receipt();
    for (const response of [new Response('{}', { status: 404 }), new Response(JSON.stringify({ ...proof, decisionSha256: 'b'.repeat(64) }))]) {
      const fetch = vi.fn().mockRejectedValueOnce(new TypeError('lost')).mockResolvedValueOnce(response);
      vi.stubGlobal('fetch', fetch);
      await expect(api.submitControl('alice', 'task', { ...decision, commandId: proof.commandId })).rejects.toMatchObject({ code: 'OFFLINE' });
      expect(fetch.mock.calls.filter(c => c[1].method === 'POST')).toHaveLength(1);
    }
  });
  it('rejects foreign identity, child target, command and contradictory outcome flags', async () => {
    const proof = await receipt();
    for (const delta of [{ ownerId: 'bob' }, { taskId: 'task~other-child' }, { commandId: 'different-command' },
      { stopConfirmed: true }, { executionContinuing: true }, { decisionRecorded: false }, { canDispatch: true }]) {
      expect(() => validateControlReceipt({ ...proof, ...delta }, 'alice', 'task', 'original-command')).toThrow();
    }
    expect(validateControlReceipt({ ...proof, state: 'UNKNOWN', decisionRecorded: false }, 'alice', 'task')).toMatchObject({ state: 'UNKNOWN' });
  });
});
