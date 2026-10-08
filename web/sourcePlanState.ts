export interface SourceSnapshotReference { id: string; fingerprint: string }
export function sourceSnapshotReference(value: unknown): value is SourceSnapshotReference {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const ref = value as Record<string, unknown>;
  return Object.keys(ref).length === 2 && typeof ref.id === 'string' && /^[a-f0-9-]{36}$/.test(ref.id)
    && typeof ref.fingerprint === 'string' && /^[a-f0-9]{64}$/.test(ref.fingerprint);
}
export function sameSourceSnapshot(a: unknown, b: unknown): boolean {
  if (a === undefined || b === undefined) return a === b;
  return sourceSnapshotReference(a) && sourceSnapshotReference(b) && a.id === b.id && a.fingerprint === b.fingerprint;
}
