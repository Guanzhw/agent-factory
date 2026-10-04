export const diagnosticReasons = {
  CLOCK_BUSY: '执行时间变更或调度锁正在占用',
  AUTHORIZATION_DENIED: '当前执行权限未通过检查',
  CLAIM_CHANGED: '原调度领取状态已变化',
  BINDING_UNAVAILABLE: '原计划绑定无法核对',
  PAUSED: '计划已暂停',
  DEFINITION_CHANGED: '计划定义已变化',
  PLAN_UNAVAILABLE: '原不可变方案无法使用',
  CHECK_UNAVAILABLE: '前置检查暂时无法完成',
} as const;
export interface DiagnosticSchedule { id: string; createdAt: string }
export interface DiagnosticCatalog { schema: 1; ownerId: string; items: DiagnosticSchedule[]; nextCursor: string | null }
export interface ScheduleDiagnostic {
  id: string; ownerId: string; scheduleId: string; reasonCode: keyof typeof diagnosticReasons;
  source: 'native' | 'manual'; observedAt: string;
}
export interface DiagnosticPage {
  schema: 1; ownerId: string; scheduleId: string; items: ScheduleDiagnostic[]; nextCursor: string | null;
  retention: { days: 30; maxRecords: 100 }; coverage: 'retained-rejections-only'; snapshot: false;
}
export interface ScheduleDiagnosticsApi {
  list(after?: string, signal?: AbortSignal): Promise<unknown>;
  page(scheduleId: string, after?: string, signal?: AbortSignal): Promise<unknown>;
}
const record = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value);
const uuid = (value: unknown): value is string => typeof value === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value);
const timestamp = (value: unknown): value is string => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
const fail = () => new Error('拒绝诊断的身份或安全字段无法核对。');
function pageShape(value: unknown, ownerId: string): asserts value is Record<string, unknown> & { items: Record<string, unknown>[]; nextCursor: string | null } {
  if (!record(value) || value.schema !== 1 || value.ownerId !== ownerId || !Array.isArray(value.items) || value.items.length > 20
      || !(value.nextCursor === null || uuid(value.nextCursor))) throw fail();
  let previous = '';
  for (const item of value.items) {
    if (!record(item) || !uuid(item.id) || item.id <= previous) throw fail();
    previous = item.id;
  }
  if (value.nextCursor !== null && (value.items.length !== 20 || value.nextCursor !== previous)) throw fail();
}
export function diagnosticCatalog(value: unknown, ownerId: string): DiagnosticCatalog {
  pageShape(value, ownerId);
  const items = value.items.map(item => {
    if (!timestamp(item.createdAt)) throw fail();
    return { id: item.id as string, createdAt: item.createdAt };
  });
  return { schema: 1, ownerId, items, nextCursor: value.nextCursor };
}
export function diagnosticPage(value: unknown, ownerId: string, scheduleId: string): DiagnosticPage {
  pageShape(value, ownerId);
  if (!uuid(scheduleId) || value.scheduleId !== scheduleId || value.coverage !== 'retained-rejections-only' || value.snapshot !== false
      || !record(value.retention) || value.retention.days !== 30 || value.retention.maxRecords !== 100) throw fail();
  const items = value.items.map(item => {
    if (item.ownerId !== ownerId || item.scheduleId !== scheduleId || typeof item.reasonCode !== 'string'
        || !Object.hasOwn(diagnosticReasons, item.reasonCode) || !['native', 'manual'].includes(String(item.source)) || !timestamp(item.observedAt)) throw fail();
    return { id: item.id as string, ownerId, scheduleId, reasonCode: item.reasonCode as ScheduleDiagnostic['reasonCode'], source: item.source as ScheduleDiagnostic['source'], observedAt: item.observedAt };
  });
  // Only the finite projection is retained; legacy/raw audit fields are never rendered.
  return { schema: 1, ownerId, scheduleId, items, nextCursor: value.nextCursor,
    retention: { days: 30, maxRecords: 100 }, coverage: 'retained-rejections-only', snapshot: false };
}
export class DiagnosticsEpoch {
  private scope = ''; private epoch = 0;
  enter(ownerId: string, scheduleId = ''): number {
    const scope = JSON.stringify([ownerId, scheduleId]);
    if (this.scope !== scope) { this.scope = scope; this.epoch++; }
    return this.epoch;
  }
  current(epoch: number): boolean { return this.epoch === epoch; }
}
