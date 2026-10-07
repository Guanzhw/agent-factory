/** Read-only browser projection. Server remains authoritative for execution. */
export type ResearchPreset = { id: string; name: string; defaultGoal: string; ready: boolean; blockers: string[]; limits: Record<string, number> };
export type ResearchStep = { id: string; kind: 'model-instructions' | 'action' | 'experiment' | 'assessment' | 'next-decision'; status: string; text: string };
export type ResearchAcceptance = { modelExecuted: boolean; instructionsRead: boolean; agentDecision: boolean; managedExperiment: boolean; independentResult: boolean; nextDecision: boolean; scientificConclusionVerified: false };
export type ResearchRun = { acceptance: ResearchAcceptance; id: string; ownerId: string; presetId: string; requestId: string; goal: string; status: string; steps: ResearchStep[]; evidence: { label: string; url?: string }[]; allowedActions: string[] };
export type StartResearch = { presetId: string; goal?: string; requestId: string };
export type AutoResearchApi = {
  presets(signal?: AbortSignal): Promise<unknown>;
  start(input: StartResearch, signal?: AbortSignal): Promise<unknown>;
  get(id: string, signal?: AbortSignal): Promise<unknown>;
  recover(requestId: string, signal?: AbortSignal): Promise<unknown | null>;
  cancel(id: string, input: { requestId: string }, signal?: AbortSignal): Promise<unknown>;
};
const fail = () => { throw new Error('研究状态无法核对，请重新读取原请求。'); };
function object(value: unknown): Record<string, unknown> { if (!value || typeof value !== 'object' || Array.isArray(value)) return fail(); return value as Record<string, unknown>; }
function text(value: unknown, limit = 4000): string { if (typeof value !== 'string' || !value.length || value.length > limit || Array.from(value).some(char => { const code = char.charCodeAt(0); return code < 32 && code !== 9 && code !== 10 && code !== 13 || code === 127; })) return fail(); return value; }
function id(value: unknown) { const result = text(value, 200); if (!/^[A-Za-z0-9][A-Za-z0-9_.:-]*$/.test(result)) return fail(); return result; }
function list(value: unknown, limit: number): unknown[] { if (!Array.isArray(value) || value.length > limit) return fail(); return value; }
export function researchPresets(raw: unknown): ResearchPreset[] {
  const result = list(raw, 32).map(value => {
    const row = object(value); if (typeof row.ready !== 'boolean') return fail();
    const limits = Object.fromEntries(Object.entries(object(row.limits)).map(([key, number]) => {
      if (!/^[A-Za-z][A-Za-z0-9]{0,63}$/.test(key) || typeof number !== 'number' || !Number.isFinite(number) || number < 0) return fail();
      return [key, number];
    }));
    return { id: id(row.id), name: text(row.name, 160), defaultGoal: text(row.defaultGoal), ready: row.ready, blockers: list(row.blockers, 32).map(item => text(item, 500)), limits };
  });
  if (new Set(result.map(row => row.id)).size !== result.length) return fail();
  return result;
}
export function researchRun(raw: unknown, ownerId: string, expected?: { id?: string; requestId?: string; presetId?: string }): ResearchRun {
  const row = object(raw);
  if (row.ownerId !== ownerId) return fail();
  const acceptance = object(row.acceptance);
  for (const key of ['modelExecuted', 'instructionsRead', 'agentDecision', 'managedExperiment', 'independentResult', 'nextDecision']) if (typeof acceptance[key] !== 'boolean') return fail();
  if (acceptance.scientificConclusionVerified !== false) return fail();
  const result: ResearchRun = { acceptance: { ...acceptance } as ResearchAcceptance, id: id(row.id), ownerId, presetId: id(row.presetId), requestId: id(row.requestId), goal: text(row.goal), status: text(row.status, 64),
    steps: list(row.steps, 256).map(value => {
      const step = object(value); const kind = text(step.kind, 64) as ResearchStep['kind'];
      if (!['model-instructions', 'action', 'experiment', 'assessment', 'next-decision'].includes(kind)) return fail();
      return { id: id(step.id), kind, status: text(step.status, 64), text: text(step.text, 16000) };
    }),
    evidence: list(row.evidence, 128).map(value => {
      const item = object(value); const label = text(item.label, 200);
      if (item.url === undefined) return { label };
      const url = text(item.url, 2048);
      // Only server-owned same-origin artifact routes; no provider links or auth URLs.
      const match = /^\/api\/factory\/jobs\/([A-Za-z0-9][A-Za-z0-9_.:-]*)\/artifacts\/([A-Za-z0-9][A-Za-z0-9_.:-]*)$/.exec(url);
      if (!match || match[1] !== row.id || match[1].includes('..') || match[2].includes('..')) return fail();
      return { label, url };
    }), allowedActions: list(row.allowedActions, 8).map(value => { if (value !== 'cancel') return fail(); return value; }) };
  if (expected?.id && result.id !== expected.id || expected?.requestId && result.requestId !== expected.requestId || expected?.presetId && result.presetId !== expected.presetId) return fail();
  if (new Set(result.steps.map(step => step.id)).size !== result.steps.length) return fail();
  return result;
}
export const stepLabels: Record<ResearchStep['kind'], string> = { 'model-instructions': '模型执行指令', action: '实际行动', experiment: '实验', assessment: '结果评估', 'next-decision': '下一步决定' };
export function researchStatus(value: string): string { return ({ STARTING: '正在启动', STOPPING: '正在停止', CREATED: '已创建', PENDING: '等待执行', RUNNING: '研究中', WAITING: '等待确认', CANCELLING: '正在取消', CANCELLED: '已取消', COMPLETED: '执行结束', FAILED: '执行失败', UNKNOWN: '状态待核对', BLOCKED: '暂不能开始' } as Record<string, string>)[value.toUpperCase()] ?? '等待服务器状态确认'; }
export type ResearchPointer = { requestId: string; runId?: string };
export function researchPointer(raw: string | null): ResearchPointer | undefined {
  if (!raw) return undefined;
  try { const row = object(JSON.parse(raw)); return { requestId: id(row.requestId), ...(row.runId === undefined ? {} : { runId: id(row.runId) }) }; } catch { return undefined; }
}
/** Responses from an earlier owner/request generation cannot update current UI. */
export class ResearchResponses {
  private version = 0;
  invalidate() { this.version++; }
  async read<T>(work: () => Promise<T>, signal?: AbortSignal): Promise<T | undefined> {
    const version = ++this.version;
    try { const result = await work(); return version === this.version && !signal?.aborted ? result : undefined; }
    catch (error) { if (version === this.version && !signal?.aborted) throw error; return undefined; }
  }
}
