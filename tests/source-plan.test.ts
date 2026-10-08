import { expect, it } from 'vitest';
import { sameSourceSnapshot, sourceSnapshotReference } from '../web/sourcePlanState.js';
const ref = { id: '12345678-1234-1234-1234-123456789012', fingerprint: 'a'.repeat(64) };
it('compares immutable source custody without depending on JSON key ordering', () => {
  expect(sameSourceSnapshot(ref, { fingerprint: ref.fingerprint, id: ref.id })).toBe(true);
  expect(sameSourceSnapshot(undefined, undefined)).toBe(true);
  expect(sameSourceSnapshot(ref, undefined)).toBe(false);
  expect(sameSourceSnapshot(undefined, ref)).toBe(false);
});
it('rejects substituted, malformed or expanded source receipts', () => {
  for (const value of [null, {}, { ...ref, fingerprint: 'b'.repeat(64) }, { ...ref, extra: true }, { ...ref, id: 'other' }]) expect(sameSourceSnapshot(ref, value)).toBe(false);
  expect(sourceSnapshotReference({ ...ref, fingerprint: 'bad' })).toBe(false);
});
