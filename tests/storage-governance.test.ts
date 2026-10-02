import { describe, expect, it } from 'vitest';
import { retentionReceipt, storageHeadroom, storageSummary, type StorageSummary } from '../web/storageState.js';
const hash = 'a'.repeat(64);
function summary(): StorageSummary {
  return { ownerId: 'alice', filesystems: [{ filesystem: 'fixture', freeBytes: 200, totalBytes: 1000, usedBytes: 800 }], reservedBytes: 150, lowWaterBytes: 100, taskReserveBytes: 64,
    purgeEnabled: false, retentionSupported: true, quarantineGraceSeconds: 86400, ownerHolds: [{ task_id: 'unknown', bytes: 150, state: 'HELD' }], objects: [], plans: [],
    databaseArtifacts: { count: 1, bytes: 20 }, protectedDirectories: [], protectedContainers: [], observationLimits: { objects: 100, plans: 100, orxDirectories: 10, holdReconciliations: 20 }, scope: 'synthetic' };
}
describe('owner-scoped storage observations', () => {
  it('subtracts UNKNOWN holds and preserves negative admission headroom', () => {
    const value = storageSummary(summary(), 'alice');
    expect(storageHeadroom(value)).toBe(-50);
    expect(value.ownerHolds[0].state).toBe('HELD');
  });
  it('rejects another owner and incomplete protected inventory', () => {
    expect(() => storageSummary(summary(), 'bob')).toThrow();
    const value = summary();
    Object.assign(value, { protectedDirectories: null });
    expect(() => storageSummary(value, 'alice')).toThrow();
  });
  it('never accepts a substituted plan identity or treats quarantine as reclaimed bytes', () => {
    const value = { id: 'original', ownerId: 'alice', objectId: hash, state: 'QUARANTINED' as const, fingerprint: hash,
      createdAt: '2026-10-02T00:00:00Z', logicalBytes: 20, allocatedBytes: 4096, quarantinedAt: '2026-10-02T00:00:00Z', reclaimedLogicalBytes: 0 };
    expect(retentionReceipt(value, 'alice', 'original').reclaimedLogicalBytes).toBe(0);
    expect(() => retentionReceipt(value, 'bob')).toThrow();
    expect(() => retentionReceipt(value, 'alice', 'other')).toThrow();
  });
});
