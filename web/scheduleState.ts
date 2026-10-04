export interface ScheduleSummary { id: string; ownerId: string; requestId: string | null; lastCommandId: string | null; name: string; cron: string; timezone: string; enabled: boolean; planId: string; planFingerprint: string; planDigest: string; definitionFingerprint: string; nextRunAt: string | null; allowedActions: ('edit' | 'enable' | 'disable')[] }
export interface ScheduleMetadata { schema: 1; ownerId: string; canManage: boolean; policy: { singlePoller: true; overlap: 'allow-with-current-budget-admission'; missed: 'coalesce'; pauseCancelsRunning: false; timeSemantics: 'cron-iana-timezone'; maxUserTasks: number; maxTotalTasks: number } }
export interface SchedulePage { schema: 1; ownerId: string; items: ScheduleSummary[]; nextCursor: string | null; snapshot: false }
export interface ScheduleOccurrence { id: string; ownerId: string; scheduleId: string; status: 'reserving' | 'accepted' | 'unknown' | 'rejected'; taskId: string | null; nativeRunId: string | null; createdAt: string; taskStatus: string | null; reasonCode: null | 'ADMISSION_REJECTED' | 'ADMISSION_UNKNOWN' }
export interface ScheduleOccurrencePage { schema: 1; ownerId: string; scheduleId: string; items: ScheduleOccurrence[]; nextCursor: string | null; snapshot: false }
export interface SchedulePreview { schema: 1; cron: string; timezone: string; previewedAtUtc: string; nextRuns: { epoch: number; utc: string; local: string; utcOffsetSeconds: number }[]; semantics: { clock: string; missed: string; overlap: string; dst: string; previewOnly: true } }
export type ScheduleMutation = { kind: 'create'; requestId: string; planId: string; planFingerprint: string; name: string; cron: string; timezone: string }
  | { kind: 'edit'; requestId: string; scheduleId: string; expectedDefinitionFingerprint: string; cron: string; timezone: string }
  | { kind: 'enabled'; requestId: string; scheduleId: string; expectedDefinitionFingerprint: string; enabled: boolean };
export interface ScheduleApi {
  metadata(signal?: AbortSignal): Promise<unknown>; list(after?: string, signal?: AbortSignal): Promise<unknown>;
  recover(requestId: string, signal?: AbortSignal): Promise<unknown>;
  inspect(id: string, signal?: AbortSignal): Promise<unknown>; preview(input: { cron: string; timezone: string }, signal?: AbortSignal): Promise<unknown>;
  create(input: { planId: string; name: string; cron: string; timezone: string; requestId: string }): Promise<unknown>;
  update(id: string, input: { cron: string; timezone: string; requestId: string; expectedDefinitionFingerprint: string }): Promise<unknown>;
  setEnabled(id: string, input: { enabled: boolean; requestId: string; expectedDefinitionFingerprint: string }): Promise<unknown>;
  occurrences(id: string, after?: string, signal?: AbortSignal): Promise<unknown>;
}
const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const text = (v: unknown, n: number): v is string => typeof v === 'string' && !!v.trim() && [...v].length <= n;
const id = (v: unknown): v is string => typeof v === 'string' && /^[A-Za-z0-9_.:~-]{1,128}$/.test(v);
const hash = (v: unknown) => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);
const date = (v: unknown): v is string => typeof v === 'string' && Number.isFinite(Date.parse(v));
const optionalId = (v: unknown) => v === null || id(v);
const fail = () => new Error('计划任务身份、原方案或状态凭据无法核对。');
export function scheduleSummary(v: unknown, owner: string, identifier?: string): ScheduleSummary {
  if (!record(v) || !id(v.id) || identifier !== undefined && v.id !== identifier || v.ownerId !== owner || !optionalId(v.requestId) || !optionalId(v.lastCommandId)
      || !text(v.name, 120) || !text(v.cron, 100) || !text(v.timezone, 100) || typeof v.enabled !== 'boolean' || !id(v.planId)
      || !hash(v.planFingerprint) || !hash(v.planDigest) || !hash(v.definitionFingerprint) || !(v.nextRunAt === null || date(v.nextRunAt))
      || !Array.isArray(v.allowedActions) || v.allowedActions.some(x => !['edit', 'enable', 'disable'].includes(x)) || new Set(v.allowedActions).size !== v.allowedActions.length) throw fail();
  return v as unknown as ScheduleSummary;
}
export function scheduleMetadata(v: unknown, owner: string): ScheduleMetadata {
  if (!record(v) || v.schema !== 1 || v.ownerId !== owner || typeof v.canManage !== 'boolean' || !record(v.policy)
      || v.policy.singlePoller !== true || v.policy.overlap !== 'allow-with-current-budget-admission' || v.policy.missed !== 'coalesce'
      || v.policy.pauseCancelsRunning !== false || v.policy.timeSemantics !== 'cron-iana-timezone'
      || !Number.isSafeInteger(v.policy.maxUserTasks) || Number(v.policy.maxUserTasks) < 1 || !Number.isSafeInteger(v.policy.maxTotalTasks) || Number(v.policy.maxTotalTasks) < 1) throw fail();
  return v as unknown as ScheduleMetadata;
}
export function schedulePage(v: unknown, owner: string): SchedulePage {
  if (!record(v) || v.schema !== 1 || v.ownerId !== owner || v.snapshot !== false || !Array.isArray(v.items) || v.items.length > 20 || !optionalId(v.nextCursor)) throw fail();
  const items = v.items.map(item => scheduleSummary(item, owner));
  if (new Set(items.map(x => x.id)).size !== items.length || v.nextCursor !== null && v.nextCursor !== items.at(-1)?.id) throw fail();
  return { schema: 1, ownerId: owner, items, nextCursor: v.nextCursor as string | null, snapshot: false };
}
export function occurrencePage(v: unknown, owner: string, scheduleId: string): ScheduleOccurrencePage {
  if (!record(v) || v.schema !== 1 || v.ownerId !== owner || v.scheduleId !== scheduleId || v.snapshot !== false || !Array.isArray(v.items) || v.items.length > 20 || !optionalId(v.nextCursor)) throw fail();
  const statuses = ['queued', 'running', 'completed', 'failed', 'cancelled', 'paused'];
  for (const item of v.items) if (!record(item) || !id(item.id) || item.ownerId !== owner || item.scheduleId !== scheduleId || !['reserving', 'accepted', 'unknown', 'rejected'].includes(String(item.status))
      || !optionalId(item.taskId) || !optionalId(item.nativeRunId) || !date(item.createdAt) || !(item.taskStatus === null || statuses.includes(String(item.taskStatus)))
      || !(item.reasonCode === null || item.reasonCode === 'ADMISSION_REJECTED' || item.reasonCode === 'ADMISSION_UNKNOWN')
      || item.nativeRunId !== null && item.taskId === null || item.taskStatus !== null && item.taskId === null) throw fail();
  if (new Set(v.items.map(x => x.id)).size !== v.items.length || v.nextCursor !== null && v.nextCursor !== v.items.at(-1)?.id) throw fail();
  return v as unknown as ScheduleOccurrencePage;
}
export function schedulePreview(v: unknown, cron: string, timezone: string): SchedulePreview {
  const normalized = cron.trim().split(/\s+/).join(' ');
  if (!record(v) || v.schema !== 1 || v.cron !== normalized || v.timezone !== timezone || !date(v.previewedAtUtc) || !record(v.semantics) || v.semantics.previewOnly !== true
      || v.semantics.clock !== 'agno-3.1.0/croniter-6.2.4/pytz' || v.semantics.missed !== 'coalesce-no-catch-up'
      || v.semantics.overlap !== 'allowed-subject-to-owner-and-global-budgets' || v.semantics.dst !== 'native-croniter-pytz'
      || !Array.isArray(v.nextRuns) || v.nextRuns.length !== 3) throw fail();
  let previous = Date.parse(v.previewedAtUtc) / 1000;
  for (const run of v.nextRuns) {
    if (!record(run) || !Number.isSafeInteger(run.epoch) || Number(run.epoch) <= previous || !date(run.utc) || !date(run.local)
        || Date.parse(run.utc) !== Number(run.epoch) * 1000 || Date.parse(run.local) !== Number(run.epoch) * 1000
        || !Number.isInteger(run.utcOffsetSeconds) || Math.abs(Number(run.utcOffsetSeconds)) > 86400) throw fail();
    const offset = /([+-])(\d{2}):(\d{2})$/.exec(run.local);
    if (!offset || (Number(offset[2]) * 3600 + Number(offset[3]) * 60) * (offset[1] === '-' ? -1 : 1) !== run.utcOffsetSeconds) throw fail();
    previous = Number(run.epoch);
  }
  return v as unknown as SchedulePreview;
}

export function scheduleReply(value: unknown, owner: string, intent: ScheduleMutation): ScheduleSummary {
  const row = scheduleSummary(value, owner, intent.kind === 'create' ? undefined : intent.scheduleId);
  if (row.lastCommandId !== intent.requestId || intent.kind === 'create' && (row.requestId !== intent.requestId || row.enabled || row.planId !== intent.planId || row.planFingerprint !== intent.planFingerprint || row.name !== intent.name)
      || (intent.kind === 'create' || intent.kind === 'edit') && (row.cron !== intent.cron || row.timezone !== intent.timezone)
      || intent.kind === 'enabled' && row.enabled !== intent.enabled) throw fail();
  return row;
}
export async function sendScheduleOnce(api: ScheduleApi, owner: string, intent: ScheduleMutation): Promise<ScheduleSummary> {
  try {
    let result: unknown;
    if (intent.kind === 'create') { const { planId, name, cron, timezone, requestId } = intent; result = await api.create({ planId, name, cron, timezone, requestId }); }
    else if (intent.kind === 'edit') { const { cron, timezone, requestId, expectedDefinitionFingerprint } = intent; result = await api.update(intent.scheduleId, { cron, timezone, requestId, expectedDefinitionFingerprint }); }
    else { const { enabled, requestId, expectedDefinitionFingerprint } = intent; result = await api.setEnabled(intent.scheduleId, { enabled, requestId, expectedDefinitionFingerprint }); }
    return scheduleReply(result, owner, intent);
  } catch (error) {
    try { const value = intent.kind === 'create' ? await api.recover(intent.requestId) : await api.inspect(intent.scheduleId);
      if (intent.kind === 'create') {
        const row = scheduleSummary(value, owner);
        if (row.requestId !== intent.requestId || row.planId !== intent.planId || row.planFingerprint !== intent.planFingerprint || row.name !== intent.name) throw fail();
        return row; // Later edits may have changed time/enabled/lastCommandId.
      }
      return scheduleReply(value, owner, intent); } catch { /* Retain original operation; never repeat a mutation automatically. */ }
    throw error;
  }
}
export class ScheduleGuard {
  private owner = ''; private epoch = 0; private held = false;
  enter(owner: string) { if (owner !== this.owner) { this.owner = owner; this.epoch++; this.held = false; } return this.epoch; }
  current(epoch: number) { return this.epoch === epoch; }
  claim(epoch: number) { if (!this.current(epoch) || this.held) return false; this.held = true; return true; }
  release(epoch: number) { if (this.current(epoch)) this.held = false; }
}
