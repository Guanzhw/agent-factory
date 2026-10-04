export interface CompositionInboxItem {
  id: string; ownerId: string; createdAt: string; state: 'pending' | 'revised' | 'rejected' | 'accepted';
  fingerprint: string; parentId: string | null; planId: string | null;
  applicationRef: { id: string; version: number; sha256: string };
  mode: string; goalPreview: string; preflightStatus: 'ready' | 'blocked';
}
export interface CompositionInboxPage { schema: 1; ownerId: string; items: CompositionInboxItem[]; nextCursor: string | null; snapshot: false }
const uuid = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(v);
const hash = (v: unknown) => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);
const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const denied = () => new Error('装配提案列表无法核对，请重新读取。');
export function compositionInboxPage(value: unknown, owner: string): CompositionInboxPage {
  if (!record(value) || value.schema !== 1 || value.ownerId !== owner || value.snapshot !== false
      || !Array.isArray(value.items) || value.items.length > 50
      || value.nextCursor !== null && (typeof value.nextCursor !== 'string' || !/^[A-Za-z0-9_-]{1,2048}$/.test(value.nextCursor))
      || value.items.length === 0 && value.nextCursor !== null) throw denied();
  const seen = new Set<string>(); let previous = '';
  for (const item of value.items) {
    if (!record(item) || !uuid(item.id) || seen.has(item.id) || item.ownerId !== owner || !hash(item.fingerprint)
        || typeof item.createdAt !== 'string' || !/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(item.createdAt) || !Number.isFinite(Date.parse(item.createdAt))
        || typeof item.state !== 'string' || !['pending', 'revised', 'rejected', 'accepted'].includes(item.state)
        || item.parentId !== null && !uuid(item.parentId) || item.planId !== null && !uuid(item.planId)
        || (item.state === 'accepted') !== (item.planId !== null)
        || !record(item.applicationRef) || typeof item.applicationRef.id !== 'string' || !/^[A-Za-z0-9_.:-]{1,120}$/.test(item.applicationRef.id)
        || !Number.isSafeInteger(item.applicationRef.version) || Number(item.applicationRef.version) < 1 || !hash(item.applicationRef.sha256)
        || typeof item.mode !== 'string' || !/^[A-Za-z0-9_.:-]{1,100}$/.test(item.mode)
        || typeof item.goalPreview !== 'string' || item.goalPreview.length < 1 || [...item.goalPreview].length > 160
        || !['ready', 'blocked'].includes(String(item.preflightStatus))) throw denied();
    const key = item.createdAt + '/' + item.id;
    if (previous && key <= previous) throw denied();
    previous = key; seen.add(item.id);
  }
  return structuredClone(value) as unknown as CompositionInboxPage;
}

/** Cancellation and owner epochs fence results even if a fetch ignores AbortSignal. */
export class CompositionInboxRequests {
  private epoch = 0;
  invalidate() { this.epoch++; }
  async load(owner: string, after: string | undefined, fetchPage: (after?: string, signal?: AbortSignal) => Promise<unknown>, signal?: AbortSignal): Promise<CompositionInboxPage | undefined> {
    const epoch = ++this.epoch;
    try {
      const raw = await fetchPage(after, signal);
      if (epoch !== this.epoch || signal?.aborted) return undefined;
      const page = compositionInboxPage(raw, owner);
      if (after && page.nextCursor === after) throw denied();
      return page;
    } catch (error) {
      if (epoch !== this.epoch || signal?.aborted) return undefined;
      throw error;
    }
  }
}
