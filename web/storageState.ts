export interface RetentionReceipt {
  id: string; ownerId: string; objectId: string; state: 'PLANNED' | 'MOVING' | 'QUARANTINED' | 'RESTORING' | 'RESTORED' | 'PURGING' | 'PURGED';
  fingerprint: string; createdAt: string; logicalBytes: number; allocatedBytes: number; quarantinedAt: string | null; reclaimedLogicalBytes: number; recovery?: string;
}
export interface StorageObject {
  id: string; task_id: string; evidence: boolean; state: string; created_at: string; availableOnThisHost: boolean;
  logicalBytes?: number; allocatedBytes?: number; complete?: boolean;
}
export interface StorageSummary {
  ownerId: string; filesystems: { filesystem: string; totalBytes: number; freeBytes: number; usedBytes: number }[];
  reservedBytes: number; lowWaterBytes: number; taskReserveBytes: number; purgeEnabled: boolean; retentionSupported: boolean;
  quarantineGraceSeconds: number; ownerHolds: { task_id: string; bytes: number; state: string }[];
  objects: StorageObject[]; plans: RetentionReceipt[]; databaseArtifacts: { bytes: number; count: number };
  protectedDirectories: { taskId: string; kind: string; retentionProtected: boolean; complete: boolean; logicalBytes?: number }[];
  protectedContainers: { taskId: string; complete: boolean; retentionProtected: boolean; writableLayerBytes?: number; rootFilesystemLogicalBytes?: number; running?: boolean }[];
  observationLimits: { objects: number; plans: number; orxDirectories: number; holdReconciliations: number }; scope: string;
}
const amount = (value: unknown) => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
const hash = (value: unknown) => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
export function retentionReceipt(value: RetentionReceipt, owner: string, id?: string): RetentionReceipt {
  if (!value || value.ownerId !== owner || typeof value.id !== 'string' || id !== undefined && value.id !== id
      || !hash(value.objectId) || !hash(value.fingerprint) || !['PLANNED', 'MOVING', 'QUARANTINED', 'RESTORING', 'RESTORED', 'PURGING', 'PURGED'].includes(value.state)
      || !amount(value.logicalBytes) || !amount(value.allocatedBytes) || !amount(value.reclaimedLogicalBytes) || typeof value.createdAt !== 'string') {
    throw new Error('回收计划身份或状态无法核对。');
  }
  return value;
}
export function storageSummary(value: StorageSummary, owner: string): StorageSummary {
  if (!value || value.ownerId !== owner || !Array.isArray(value.filesystems) || !value.filesystems.length
      || value.filesystems.some(m => !amount(m.freeBytes) || !amount(m.totalBytes) || !amount(m.usedBytes) || m.freeBytes > m.totalBytes)
      || !amount(value.reservedBytes) || !amount(value.lowWaterBytes) || !amount(value.taskReserveBytes)
      || !amount(value.quarantineGraceSeconds) || typeof value.purgeEnabled !== 'boolean' || typeof value.retentionSupported !== 'boolean'
      || !Array.isArray(value.objects) || !Array.isArray(value.plans) || !Array.isArray(value.ownerHolds)
      || !Array.isArray(value.protectedDirectories) || value.protectedDirectories.some(p => !p || typeof p.taskId !== 'string' || p.retentionProtected !== true || typeof p.complete !== 'boolean')
      || !Array.isArray(value.protectedContainers) || value.protectedContainers.some(c => !c || typeof c.taskId !== 'string' || c.retentionProtected !== true || typeof c.complete !== 'boolean')
      || !value.observationLimits || Object.values(value.observationLimits).some(n => !amount(n))
      || !value.databaseArtifacts || !amount(value.databaseArtifacts.bytes) || !amount(value.databaseArtifacts.count)
      || value.objects.some(o => !hash(o.id) || typeof o.task_id !== 'string' || typeof o.evidence !== 'boolean' || typeof o.availableOnThisHost !== 'boolean')
      || value.ownerHolds.some(h => typeof h.task_id !== 'string' || !amount(h.bytes) || !['HELD', 'RELEASED'].includes(h.state))) {
    throw new Error('磁盘观测响应不完整，请重新核对。');
  }
  value.plans.forEach(plan => retentionReceipt(plan, owner));
  return value;
}
export function storageHeadroom(value: StorageSummary): number {
  return Math.min(...value.filesystems.map(m => m.freeBytes - value.reservedBytes - value.lowWaterBytes));
}
export const retentionState = (state: string) => ({ PLANNED: '计划已记录，尚未移动', MOVING: '隔离结果待核对', QUARANTINED: '已隔离，可恢复', RESTORING: '恢复结果待核对', RESTORED: '已恢复原目录', PURGING: '永久回收待核对', PURGED: '已永久回收可重建文件' })[state] ?? '状态未确认';
