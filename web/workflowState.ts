/** Display and command transport for native Agno workflow projections. No DAG engine. */
export type WorkflowAction = 'reconcile' | 'decide' | 'cancel';
export interface WorkflowCommand { commandId: string; action: WorkflowAction; version?: string; requirementId?: string; operationId?: string; approved?: boolean; values?: Record<string, unknown> }
export interface WorkflowAllowedAction { action: WorkflowAction; requirementId?: string; operationId?: string }
export interface WorkflowRequirement { id: string; stepName: string; kind: 'confirmation' | 'input' | 'external'; fields?: { name: string; type: string; required: boolean }[] }
export interface WorkflowSnapshot {
  schema: 2; id: string; ownerId: string; taskId: string; nativeRunId: string; planId: string; planSha256: string;
  status: string; version: string; steps: { id: string; name: string; status: string }[];
  requirements: WorkflowRequirement[]; operations: { id: string; stepId: string; state: string; allStopped: boolean }[];
}
export type WorkflowView = { available: false } | { available: true; workflow: WorkflowSnapshot; allowedActions: WorkflowAllowedAction[] };
export interface WorkflowApi {
  get(taskId: string, signal?: AbortSignal): Promise<unknown>;
  commandStatus(taskId: string, commandId: string, signal?: AbortSignal): Promise<unknown>;
  command(taskId: string, command: WorkflowCommand): Promise<unknown>;
}
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const identifier = (value: unknown): value is string => typeof value === 'string' && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$/.test(value);
const text = (value: unknown): value is string => typeof value === 'string' && value.length > 0 && value.length <= 2000;
const hash = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const actions: WorkflowAction[] = ['reconcile', 'decide', 'cancel'];
const invalid = () => { throw new Error('工作流记录无法核对，请重新读取原任务。'); };
const list = (value: unknown): value is Record<string, unknown>[] => Array.isArray(value) && value.length <= 256 && value.every(object);
function uniqueIds(items: { id: string }[]) { if (new Set(items.map(item => item.id)).size !== items.length) invalid(); }
export function workflowStateLabel(status: string): string {
  return ({ pending: '尚未开始', running: '运行中', paused: '已暂停', completed: '已完成', failed: '失败', error: '错误', cancelled: '已取消', canceled: '已取消', unknown: '状态待核对', waiting: '等待中' } as Record<string, string>)[status.toLowerCase()] ?? status;
}
export function workflowSnapshot(raw: unknown, ownerId: string, taskId: string): WorkflowSnapshot {
  if (!object(raw) || raw.schema !== 2 || !identifier(raw.id) || raw.ownerId !== ownerId || raw.taskId !== taskId
    || !identifier(raw.nativeRunId) || !identifier(raw.planId) || !hash(raw.planSha256) || !hash(raw.version) || !text(raw.status)
    || !list(raw.steps) || !list(raw.requirements) || !list(raw.operations)) invalid();
  const value = raw as unknown as WorkflowSnapshot;
  for (const step of value.steps) if (!identifier(step.id) || !text(step.name) || !text(step.status)) invalid();
  for (const requirement of value.requirements) {
    if (!identifier(requirement.id) || !text(requirement.stepName) || !['confirmation', 'input', 'external'].includes(requirement.kind)) invalid();
    if (requirement.fields !== undefined && (!list(requirement.fields) || requirement.fields.some(field => !text(field.name) || !text(field.type) || typeof field.required !== 'boolean'))) invalid();
  }
  for (const operation of value.operations) if (!identifier(operation.id) || !identifier(operation.stepId) || !text(operation.state) || typeof operation.allStopped !== 'boolean') invalid();
  uniqueIds(value.requirements); uniqueIds(value.operations);
  return structuredClone(value);
}
export function workflowView(raw: unknown, ownerId: string, taskId: string): WorkflowView {
  if (!object(raw)) invalid();
  const value = raw as Record<string, unknown>;
  if (value.available === false) return { available: false };
  if (value.available !== true || !list(value.allowedActions)) invalid();
  const workflow = workflowSnapshot(value.workflow, ownerId, taskId);
  const allowed = value.allowedActions as unknown as WorkflowAllowedAction[];
  for (const item of allowed) {
    if (!actions.includes(item.action) || Object.keys(item).some(key => !['action', 'requirementId', 'operationId'].includes(key))) invalid();
    if (item.action === 'decide' ? !workflow.requirements.some(req => req.id === item.requirementId) || item.operationId !== undefined
      : item.action === 'reconcile' ? !workflow.operations.some(op => op.id === item.operationId) || item.requirementId !== undefined
      : item.requirementId !== undefined || item.operationId !== undefined) invalid();
  }
  if (new Set(allowed.map(item => `${item.action}:${item.requirementId ?? item.operationId ?? ''}`)).size !== allowed.length) invalid();
  return { available: true, workflow, allowedActions: structuredClone(allowed) };
}
function inputObject(value: unknown): value is Record<string, unknown> {
  if (!object(value)) return false;
  try { return JSON.stringify(value).length <= 32768; } catch { return false; }
}
export function workflowCommand(raw: unknown): WorkflowCommand {
  if (!object(raw) || typeof raw.commandId !== 'string' || !/^[a-zA-Z0-9_.:-]{8,100}$/.test(raw.commandId) || !actions.includes(raw.action as WorkflowAction)
    || Object.keys(raw).some(key => !['commandId', 'action', 'requirementId', 'operationId', 'approved', 'values', 'version'].includes(key))) invalid();
  const value = raw as unknown as WorkflowCommand;
  if (value.action === 'cancel') {
    if (Object.keys(value).some(key => !['commandId', 'action'].includes(key))) invalid();
  } else {
    if (!hash(value.version)) invalid();
    if (value.action === 'reconcile') {
      if (!identifier(value.operationId) || value.requirementId !== undefined || value.approved !== undefined || value.values !== undefined) invalid();
    } else if (!identifier(value.requirementId) || value.operationId !== undefined
      || !((typeof value.approved === 'boolean' && value.values === undefined) || (value.approved === undefined && inputObject(value.values)))) invalid();
  }
  return structuredClone(value);
}
export function workflowCommandReceipt(raw: unknown, ownerId: string, taskId: string, command: WorkflowCommand): { status: 'completed' | 'unknown' | 'recorded' | 'rejected'; workflow?: WorkflowSnapshot } {
  if (!object(raw) || raw.commandId !== command.commandId || !['completed', 'unknown', 'recorded', 'rejected'].includes(String(raw.status))) invalid();
  const value = raw as Record<string, unknown>;
  return { status: value.status as 'completed' | 'unknown' | 'recorded' | 'rejected', ...(value.workflow === undefined ? {} : { workflow: workflowSnapshot(value.workflow, ownerId, taskId) }) };
}
export function workflowCommandSettled(status: string): boolean { return status === 'completed' || status === 'rejected'; }
export function sameWorkflowLineage(previous: WorkflowSnapshot, next: WorkflowSnapshot): boolean {
  return ['id', 'nativeRunId', 'taskId', 'ownerId', 'planId', 'planSha256'].every(key => previous[key as keyof WorkflowSnapshot] === next[key as keyof WorkflowSnapshot]);
}
/** Digests have no ordering. A historical receipt cannot replace an existing GET projection. */
export function currentWorkflowAfterReceipt(current: WorkflowSnapshot | undefined, receipt: WorkflowSnapshot): WorkflowSnapshot {
  if (!current) return receipt;
  if (!sameWorkflowLineage(current, receipt)) invalid();
  return current;
}
export function workflowPointer(text: string | null): WorkflowCommand | undefined {
  try { if (!text || text.length > 40000) return undefined; return workflowCommand(JSON.parse(text)); } catch { return undefined; }
}
export class WorkflowResponses {
  private epoch = 0;
  invalidate() { this.epoch++; }
  async read<T>(fetch: () => Promise<T>, signal?: AbortSignal): Promise<T | undefined> {
    const epoch = ++this.epoch;
    try { const result = await fetch(); return epoch === this.epoch && !signal?.aborted ? result : undefined; }
    catch (error) { if (epoch === this.epoch && !signal?.aborted) throw error; return undefined; }
  }
}
