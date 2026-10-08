export type WorkflowAction = 'reconcile' | 'decide' | 'resume' | 'cancel';
export type WorkflowStageState = 'PENDING' | 'HUMAN_WAIT' | 'SKIPPED' | 'RUNNING' | 'WAITING' | 'COMPLETED' | 'FAILED' | 'UNKNOWN' | 'CANCELLED';
export interface WorkflowCommand { commandId: string; action: WorkflowAction; stageId?: string; approved?: boolean; version?: number }
export interface WorkflowAllowedAction { action: WorkflowAction; stageId?: string }
export interface WorkflowStage {
  id: string; adapterId: string; revision: string; dependencies: string[]; failureRoutes: Record<string, string>; humanGate: boolean;
}
export interface WorkflowStageEntry {
  state: WorkflowStageState; operationId: string | null; approved: boolean;
  handle: { adapterId: string; revision: string; id: string } | null;
  observation: { operationId: string; handle: WorkflowStageEntry['handle']; state: string; allStopped: boolean; failure: { code: string; messageCode: string; retryable: boolean } | null } | null;
}
export interface WorkflowSnapshot {
  schema: 1; id: string; ownerId: string; taskId: string; nativeRunId: string; version: number; cancelRequested: boolean;
  planId: string; planSha256: string; definitionSha256: string; status: 'ACTIVE' | 'COMPLETED' | 'CANCELLED';
  definition: { id: string; revision: string; stages: WorkflowStage[] };
  stages: Record<string, WorkflowStageEntry>;
}
export type WorkflowView = { available: false } | { available: true; workflow: WorkflowSnapshot; allowedActions: WorkflowAllowedAction[] };
export interface WorkflowApi {
  get(taskId: string, signal?: AbortSignal): Promise<unknown>;
  commandStatus(taskId: string, commandId: string, signal?: AbortSignal): Promise<unknown>;
  command(taskId: string, command: WorkflowCommand): Promise<unknown>;
}
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const identifier = (value: unknown): value is string => typeof value === 'string' && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$/.test(value);
const states: WorkflowStageState[] = ['PENDING', 'HUMAN_WAIT', 'SKIPPED', 'RUNNING', 'WAITING', 'COMPLETED', 'FAILED', 'UNKNOWN', 'CANCELLED'];
const actions: WorkflowAction[] = ['reconcile', 'decide', 'resume', 'cancel'];
const invalid = () => { throw new Error('工作流记录无法核对，请重新读取原任务。'); };
export const workflowStateLabel: Record<WorkflowStageState, string> = { PENDING: '尚未开始', HUMAN_WAIT: '等待人工决定', SKIPPED: '已跳过', RUNNING: '执行中', WAITING: '等待外部事件', COMPLETED: '执行完成', FAILED: '执行失败', UNKNOWN: '结果待核对', CANCELLED: '已取消' };
export function workflowSnapshot(raw: unknown, ownerId: string, taskId: string): WorkflowSnapshot {
  if (!object(raw) || raw.schema !== 1 || !identifier(raw.id) || raw.ownerId !== ownerId || raw.taskId !== taskId
    || !identifier(raw.nativeRunId) || !identifier(raw.planId) || !/^[a-f0-9]{64}$/.test(String(raw.planSha256)) || !/^[a-f0-9]{64}$/.test(String(raw.definitionSha256))
    || !['ACTIVE', 'COMPLETED', 'CANCELLED'].includes(String(raw.status)) || !Number.isSafeInteger(raw.version) || Number(raw.version) < 0 || typeof raw.cancelRequested !== 'boolean'
    || !object(raw.definition) || !identifier(raw.definition.id) || !identifier(raw.definition.revision)
    || !Array.isArray(raw.definition.stages) || !raw.definition.stages.length || raw.definition.stages.length > 16 || !object(raw.stages)) invalid();
  const value = raw as unknown as WorkflowSnapshot;
  const ids = value.definition.stages.map(stage => stage.id);
  if (new Set(ids).size !== ids.length || Object.keys(value.stages).length !== ids.length || Object.keys(value.stages).some(id => !ids.includes(id))) invalid();
  for (const stage of value.definition.stages) {
    if (!object(stage) || !identifier(stage.id) || !identifier(stage.adapterId) || !identifier(stage.revision) || typeof stage.humanGate !== 'boolean'
      || !Array.isArray(stage.dependencies) || stage.dependencies.length > 16 || stage.dependencies.some(id => !ids.includes(id) || id === stage.id)
      || !object(stage.failureRoutes) || Object.keys(stage.failureRoutes).length > 16 || Object.entries(stage.failureRoutes).some(([code, id]) => !identifier(code) || !ids.includes(id) || id === stage.id)) invalid();
    const entry = value.stages[stage.id];
    if (!object(entry) || !states.includes(entry.state) || typeof entry.approved !== 'boolean' || !(entry.operationId === null || identifier(entry.operationId))) invalid();
    if (entry.handle !== null && (!object(entry.handle) || entry.handle.adapterId !== stage.adapterId || entry.handle.revision !== stage.revision || !identifier(entry.handle.id))) invalid();
    const observation = entry.observation;
    if (observation !== null) {
      if (!object(observation) || observation.state !== entry.state || !['RUNNING', 'WAITING', 'COMPLETED', 'FAILED', 'UNKNOWN', 'CANCELLED'].includes(observation.state)
        || typeof observation.allStopped !== 'boolean' || observation.allStopped !== ['COMPLETED', 'FAILED', 'CANCELLED'].includes(observation.state)
        || !entry.operationId || observation.operationId !== entry.operationId || !sameHandle(observation.handle, entry.handle)) invalid();
      if (observation.state === 'FAILED') {
        if (!object(observation.failure) || !identifier(observation.failure.code) || !identifier(observation.failure.messageCode) || typeof observation.failure.retryable !== 'boolean') invalid();
      } else if (observation.failure !== null) invalid();
    }
  }
  return structuredClone(value);
}
function sameHandle(left: unknown, right: WorkflowStageEntry['handle']): boolean {
  return right === null ? left === null : object(left) && left.id === right.id && left.adapterId === right.adapterId && left.revision === right.revision;
}
export function workflowView(raw: unknown, ownerId: string, taskId: string): WorkflowView {
  if (!object(raw)) invalid();
  const value = raw as Record<string, unknown>;
  if (value.available === false) return { available: false };
  if (value.available !== true || !Array.isArray(value.allowedActions) || value.allowedActions.length > 50) invalid();
  const workflow = workflowSnapshot(value.workflow, ownerId, taskId);
  const allowed = value.allowedActions as WorkflowAllowedAction[];
  for (const item of allowed) {
    if (!object(item) || !actions.includes(item.action) || Object.keys(item).some(key => !['action', 'stageId'].includes(key))) invalid();
    if (item.stageId !== undefined && !Object.hasOwn(workflow.stages, item.stageId)) invalid();
    if (item.action !== 'cancel' && !item.stageId || item.action === 'cancel' && item.stageId !== undefined) invalid();
    if (item.action === 'decide' && workflow.stages[item.stageId!].state !== 'HUMAN_WAIT') invalid();
    if (item.action === 'resume' && workflow.stages[item.stageId!].state !== 'PENDING') invalid();
  }
  if (new Set(allowed.map(item => `${item.action}:${item.stageId ?? ''}`)).size !== allowed.length) invalid();
  return { available: true, workflow, allowedActions: structuredClone(allowed) };
}
export function workflowCommand(raw: unknown): WorkflowCommand {
  if (!object(raw) || typeof raw.commandId !== 'string' || !/^[a-zA-Z0-9_.:-]{8,100}$/.test(raw.commandId) || !actions.includes(raw.action as WorkflowAction)
    || Object.keys(raw).some(key => !['commandId', 'action', 'stageId', 'approved', 'version'].includes(key))) invalid();
  const value = raw as unknown as WorkflowCommand;
  if (value.stageId !== undefined && !identifier(value.stageId)) invalid();
  if (value.action !== 'cancel' && !identifier(value.stageId) || value.action === 'cancel' && (value.stageId !== undefined || value.version !== undefined)) invalid();
  if (['decide', 'resume', 'reconcile'].includes(value.action) && (!Number.isSafeInteger(value.version) || Number(value.version) < 0)) invalid();
  if (value.action === 'decide' ? typeof value.approved !== 'boolean' : value.approved !== undefined) invalid();
  return structuredClone(value);
}
export function workflowCommandReceipt(raw: unknown, ownerId: string, taskId: string, command: WorkflowCommand): { status: 'completed' | 'unknown' | 'recorded' | 'rejected'; workflow?: WorkflowSnapshot } {
  if (!object(raw) || raw.commandId !== command.commandId || !['completed', 'unknown', 'recorded', 'rejected'].includes(String(raw.status))) invalid();
  const value = raw as Record<string, unknown>;
  return { status: value.status as 'completed' | 'unknown' | 'recorded' | 'rejected', ...(value.workflow === undefined ? {} : { workflow: workflowSnapshot(value.workflow, ownerId, taskId) }) };
}
export function workflowCommandSettled(status: string): boolean { return status === 'completed' || status === 'rejected'; }
export function sameWorkflowLineage(previous: WorkflowSnapshot, next: WorkflowSnapshot): boolean {
  if (next.id !== previous.id || next.nativeRunId !== previous.nativeRunId || next.taskId !== previous.taskId || next.ownerId !== previous.ownerId
    || next.planId !== previous.planId || next.planSha256 !== previous.planSha256 || next.definitionSha256 !== previous.definitionSha256 || next.version < previous.version) return false;
  return Object.entries(previous.stages).every(([id, entry]) => Object.hasOwn(next.stages, id)
    && (entry.operationId === null || next.stages[id].operationId === entry.operationId)
    && (entry.handle === null || sameHandle(next.stages[id].handle, entry.handle)));
}
/** A durable command receipt may contain an older snapshot. Validate its
 * original lineage without rolling the displayed execution back in time. */
export function currentWorkflowAfterReceipt(current: WorkflowSnapshot | undefined, receipt: WorkflowSnapshot): WorkflowSnapshot {
  if (!current) return receipt;
  const older = receipt.version < current.version;
  if (!(older ? sameWorkflowLineage(receipt, current) : sameWorkflowLineage(current, receipt))) invalid();
  return older ? current : receipt;
}
export function workflowPointer(text: string | null): WorkflowCommand | undefined {
  try { if (!text || text.length > 2048) return undefined; return workflowCommand(JSON.parse(text)); } catch { return undefined; }
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
