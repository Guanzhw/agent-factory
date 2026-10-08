import { sameSourceSnapshot, sourceSnapshotReference } from './sourcePlanState.js';
import { applicationInputSchema, applicationInputValues, sameApplicationInputs } from './applicationInputState.js';
import { workflowCommand as validateWorkflowCommand, type WorkflowCommand } from './workflowState.js';
import type { SynthesisCreate } from './synthesisJourneyState.js';
import { authEpoch, assertAuthEpoch, browserCsrf, BrowserAuthError, expireBrowserSession } from './browserAuth.js';
import { storageSummary, retentionReceipt, type StorageSummary, type RetentionReceipt } from './storageState.js';
import { decisionFingerprint, type ControlIntent } from "./controlCommandStorage.js";
import { remoteHandoffState } from './remoteHandoffState.js';
import type { ControlReceipt, UserConnection, ConnectionRegistration, FactoryApplication, ApplicationVersion, ApplicationReview, CompositionInput, AssemblyProposal, EventPage, MaterialGovernancePolicy, MaterialReview, ExecutionTarget, PlanAuthorization, PlanReview, ChildReceipt, DelegationGroup, FactoryJob, FactoryMaterial, FactoryStatus, JobDetail, MaterialDraft, Plan, User } from './models.js';

export class ApiError extends Error {
  constructor(message: string, public readonly status: number, public readonly code?: string) { super(message); }
}
const base = '/api/factory';
async function request<T>(path: string, method = 'GET', body?: unknown, signal?: AbortSignal): Promise<T> {
  const started = authEpoch();
  let response: Response;
  try {
    const csrf = ['GET', 'HEAD', 'OPTIONS'].includes(method) ? undefined : await browserCsrf();
    assertAuthEpoch(started);
    response = await fetch(`${base}${path}`, {
      method, credentials: 'same-origin', cache: 'no-store', redirect: 'error', signal,
      headers: { ...(body === undefined ? {} : { 'Content-Type': 'application/json' }), ...(csrf ? { 'X-Factory-CSRF': csrf } : {}) },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') throw error;
    if (error instanceof BrowserAuthError) throw new ApiError(error.message, error.status, 'BROWSER_AUTH');
    throw new ApiError('无法连接服务。检查网络后重试；创建请求会沿用原请求标识。', 0, 'OFFLINE');
  }
  const text = await response.text();
  assertAuthEpoch(started);
  if (response.status === 401) expireBrowserSession();
  let data: unknown;
  try { data = text ? JSON.parse(text) : undefined; } catch { data = undefined; }
  if (!response.ok) {
    const value = data && typeof data === 'object' ? data as Record<string, unknown> : {};
    const nested = value.error && typeof value.error === 'object' ? value.error as Record<string, unknown> : {};
    const detail = value.detail && typeof value.detail === 'object' ? value.detail as Record<string, unknown> : {};
    const message = value.message ?? nested.message ?? detail.message ?? (typeof value.detail === 'string' ? value.detail : undefined) ?? value.error;
    const code = value.code ?? nested.code ?? detail.code;
    throw new ApiError(typeof message === 'string' ? message : `服务返回 ${response.status}，操作未确认。`, response.status, typeof code === 'string' ? code : undefined);
  }
  if (response.status === 204) return undefined as T;
  if (data === undefined) throw new ApiError('服务未返回可识别的数据，请重试。', response.status, 'INVALID_RESPONSE');
  return data as T;
}
const segment = encodeURIComponent;
export function validateControlReceipt(value: unknown, owner: string, task?: string, commandId?: string): ControlReceipt {
  if (!value || typeof value !== 'object') throw new ApiError('命令回执无效，请核对原请求。', 200, 'INVALID_RESPONSE');
  const r = value as ControlReceipt;
  const valid = r.ownerId === owner && typeof r.taskId === 'string' && (!task || r.taskId === task)
    && typeof r.commandId === 'string' && /^[a-zA-Z0-9_.:-]{8,100}$/.test(r.commandId) && (!commandId || r.commandId === commandId)
    && ['answer', 'approve', 'cancel', 'resume_approved'].includes(r.action) && /^[a-f0-9]{64}$/.test(r.fingerprint) && /^[a-f0-9]{64}$/.test(r.decisionSha256)
    && ['INTENT_RECORDED', 'UNKNOWN', 'REJECTED', 'DECISION_RECORDED', 'EXECUTION_CONTINUING', 'STOP_CONFIRMED'].includes(r.state)
    && r.intentRecorded === true && ['decisionRecorded', 'executionContinuing', 'stopConfirmed', 'canDispatch', 'acknowledged'].every(k => typeof (r as unknown as Record<string, unknown>)[k] === 'boolean')
    && !!r.binding && r.binding.ownerId === owner && r.binding.taskId === r.taskId.split('~')[0]
    && r.canDispatch === (r.state === 'INTENT_RECORDED')
    && r.stopConfirmed === (r.state === 'STOP_CONFIRMED') && (!r.stopConfirmed || r.action === 'cancel' && r.decisionRecorded)
    && r.executionContinuing === (r.state === 'EXECUTION_CONTINUING') && (!r.executionContinuing || r.decisionRecorded)
    && r.decisionRecorded === ['DECISION_RECORDED', 'EXECUTION_CONTINUING', 'STOP_CONFIRMED'].includes(r.state)
    && typeof r.createdAt === 'string' && typeof r.updatedAt === 'string';
  if (!valid) throw new ApiError('回执身份、任务或决定状态不匹配，请核对原请求。', 200, 'INVALID_RESPONSE');
  return r;
}
async function controlReceipt(owner: string, task: string, commandId: string, signal?: AbortSignal): Promise<ControlReceipt> {
  return validateControlReceipt(await request(`/jobs/${segment(task)}/commands/${segment(commandId)}`, 'GET', undefined, signal), owner, task, commandId);
}
async function submitControl(owner: string, task: string, command: ControlIntent): Promise<ControlReceipt> {
  const { commandId: submittedId, ...decision } = command;
  const expectedHash = await decisionFingerprint(decision);
  const checked = (receipt: ControlReceipt) => {
    if (receipt.decisionSha256 !== expectedHash || receipt.commandId !== submittedId) throw new ApiError('回执内容与原决定指纹不符。', 200, 'INVALID_RESPONSE');
    return receipt;
  };
  try {
    const receipt = validateControlReceipt(await request(`/jobs/${segment(task)}/commands`, 'POST', command), owner, task, command.commandId);
    if (receipt.action !== command.action || (receipt.requirementId ?? undefined) !== command.requirementId
        || (receipt.version ?? undefined) !== command.version || (receipt.approved ?? undefined) !== command.approved) throw new ApiError('回执决定与原命令不符。', 200, 'INVALID_RESPONSE');
    return checked(receipt);
  } catch (error) {
    if (error instanceof ApiError && (error.status === 0 || error.status === 408 || error.status >= 500 || error.code === 'INVALID_RESPONSE')) {
      // Only GET after a lost reply. The service alone can prove acceptance;
      // neither a changed job status nor an empty network response permits POST.
      try { return checked(await controlReceipt(owner, task, command.commandId)); } catch { /* Retain original durable pointer and uncertainty. */ }
    }
    throw error;
  }
}
async function controlCommands(owner: string, task?: string, after?: string, signal?: AbortSignal): Promise<{ items: ControlReceipt[]; nextCursor: string | null }> {
  const params = new URLSearchParams({ limit: '50', outstanding: 'true' });
  if (task) params.set('taskId', task);
  if (after) params.set('after', after);
  const value = await request<{ items: unknown[]; nextCursor: string | null }>(`/commands?${params}`, 'GET', undefined, signal);
  if (!Array.isArray(value?.items) || value.items.length > 50 || value.nextCursor !== null && typeof value.nextCursor !== 'string') throw new ApiError('待核对命令列表无效。', 200, 'INVALID_RESPONSE');
  return { items: value.items.map(item => validateControlReceipt(item, owner, task)), nextCursor: value.nextCursor };
}

async function instantiate(planId: string, requestId: string, executionTargetRef?: string): Promise<FactoryJob> {
  try {
    const job = await request<FactoryJob>('/instances', 'POST', { planId, requestId, ...(executionTargetRef ? { executionTargetRef } : {}) });
    if (typeof job?.id !== 'string' || job.planId !== planId || (job.executionPlacement?.targetRef ?? undefined) !== executionTargetRef) throw new ApiError('创建回执不完整，请核对原请求。', 202, 'INVALID_RESPONSE');
    return job;
  } catch (error) {
    const ambiguous = error instanceof TypeError || error instanceof ApiError &&
      (error.status === 0 || error.status === 408 || error.status >= 500 || error.code === 'INVALID_RESPONSE');
    if (ambiguous) {
      try {
        const receipt = await request<{ requestId: string; planId: string; taskId: string; executionTargetRef?: string | null }>(`/requests/${segment(requestId)}`);
        if (receipt.requestId !== requestId || receipt.planId !== planId || typeof receipt.taskId !== 'string' || (receipt.executionTargetRef ?? undefined) !== executionTargetRef) throw error;
        const detail = await request<JobDetail>(`/jobs/${segment(receipt.taskId)}`);
        if (detail.job.id !== receipt.taskId || detail.job.planId !== planId || (detail.job.executionPlacement?.targetRef ?? undefined) !== executionTargetRef) throw error;
        return detail.job;
      } catch { /* Keep the original uncertainty; never issue a second POST. */ }
    }
    throw error;
  }
}
async function resumeRemote(detail: JobDetail): Promise<FactoryJob> {
  const state = remoteHandoffState(detail);
  if (state.kind !== 'pending' || !detail.job.planId || !detail.job.executionPlacement || !detail.job.allowedActions?.includes('resume_remote')) {
    throw new ApiError('当前远端准入凭据或继续权限未确认。请核对状态。', 409, 'REMOTE_REVIEW_UNVERIFIED');
  }
  const job = await instantiate(detail.job.planId, state.evidence.requestId, detail.job.executionPlacement.targetRef);
  if (job.id !== detail.job.id || job.ownerId !== detail.job.ownerId) throw new ApiError('远端确认不是原任务；请保留原请求并核对。', 202, 'REMOTE_RECEIPT_MISMATCH');
  return job;
}
async function events(id: string, cursor?: string, signal?: AbortSignal): Promise<EventPage> {
  const query = new URLSearchParams({ limit: '100' });
  if (cursor !== undefined) query.set('cursor', cursor);
  const value = await request<EventPage>(`/jobs/${segment(id)}/events?${query}`, 'GET', undefined, signal);
  const integer = (item: unknown): item is number => typeof item === 'number' && Number.isSafeInteger(item) && item >= 0;
  const hash = (item: unknown) => typeof item === 'string' && /^[a-f0-9]{64}$/.test(item);
  if (!value || value.schema !== 1 || value.nativeCursor !== false || !['factory-af_events', 'factory-remote-af_events'].includes(value.source)
      || typeof value.streamId !== 'string' || !/^[a-f0-9-]{36}$/.test(value.streamId)
      || typeof value.nextCursor !== 'string' || value.nextCursor.length < 1 || value.nextCursor.length > 4096
      || typeof value.hasMore !== 'boolean' || !integer(value.highWatermark) || !integer(value.highWatermarkSequence)
      || !integer(value.afterSequence) || value.afterSequence > value.highWatermarkSequence || !hash(value.payloadSha256)
      || !Array.isArray(value.events) || value.events.length > 100 || !integer(value.payloadBytes)) {
    throw new ApiError('事件分页响应无法核对，请重试原分页。', 200, 'INVALID_RESPONSE');
  }
  for (const [index, event] of value.events.entries()) {
    if (!event || event.jobId !== id || !integer(event.id) || event.id < 1 || event.id > value.highWatermark
        || event.sequence !== value.afterSequence + index + 1 || !hash(event.payloadSha256)
        || typeof event.type !== 'string' || typeof event.message !== 'string' || typeof event.createdAt !== 'string') {
      throw new ApiError('事件记录与当前任务或分页位置不一致。', 200, 'INVALID_RESPONSE');
    }
  }
  if (value.startSequence !== (value.events[0]?.sequence ?? null)
      || value.endSequence !== (value.events.at(-1)?.sequence ?? null)
      || (value.endSequence ?? value.afterSequence) > value.highWatermarkSequence
      || value.hasMore !== ((value.endSequence ?? value.afterSequence) < value.highWatermarkSequence)) {
    throw new ApiError('事件分页边界不一致，请重试原分页。', 200, 'INVALID_RESPONSE');
  }
  return value;
}

const invalid = (message: string) => new ApiError(message, 200, 'INVALID_RESPONSE');
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const strings = (value: unknown): value is string[] => Array.isArray(value) && value.every(item => typeof item === 'string');
const reference = (value: unknown): value is Record<string, unknown> & { id: string; version: number; sha256: string } => record(value) && typeof value.id === 'string' && Number.isSafeInteger(value.version) && Number(value.version) > 0 && typeof value.sha256 === 'string' && /^[a-f0-9]{64}$/.test(value.sha256);
const kinds = ['model', 'tool', 'knowledge', 'environment', 'orx'];
function connection(value: unknown, ref?: string): UserConnection {
  if (!record(value) || typeof value.ref !== 'string' || ref !== undefined && value.ref !== ref || typeof value.ownerId !== 'string'
      || value.version !== 1 || typeof value.fingerprint !== 'string' || !/^[a-f0-9]{64}$/.test(value.fingerprint)
      || !kinds.includes(String(value.kind)) || typeof value.registrationRef !== 'string' || typeof value.revision !== 'string'
      || !strings(value.capabilities) || !(value.taskId === null || typeof value.taskId === 'string')
      || !['active', 'unavailable', 'expired', 'revoked', 'changed', 'missing', 'task_ended'].includes(String(value.status))
      || value.available !== (value.status === 'active') || !strings(value.allowedActions)
      || !value.allowedActions.every(item => ['inspect', 'revoke'].includes(item))
      || typeof value.createdAt !== 'string' || !(value.expiresAt === null || typeof value.expiresAt === 'string')
      || !(value.revokedAt === null || typeof value.revokedAt === 'string')) throw invalid('连接响应无法核对；当前操作未确认。');
  return value as unknown as UserConnection;
}
async function userConnections(signal?: AbortSignal): Promise<UserConnection[]> {
  const value = await request<unknown>('/user-connections', 'GET', undefined, signal);
  if (!Array.isArray(value)) throw invalid('连接列表无法核对。');
  return value.map(item => connection(item));
}
async function connectionRegistrations(signal?: AbortSignal): Promise<ConnectionRegistration[]> {
  const value = await request<unknown>('/user-connections/registrations', 'GET', undefined, signal);
  if (!Array.isArray(value) || value.some(item => !record(item) || typeof item.registrationRef !== 'string' || !kinds.includes(String(item.kind))
      || typeof item.revision !== 'string' || !strings(item.capabilities) || typeof item.available !== 'boolean'
      || !['available', 'unavailable', 'expired', 'changed'].includes(String(item.status))
      || item.available !== (item.status === 'available') || !(item.expiresAt === null || typeof item.expiresAt === 'string')
      || !strings(item.allowedActions) || !item.allowedActions.every(action => ['inspect', 'bind'].includes(action)))) throw invalid('可信登记列表无法核对。');
  return value as ConnectionRegistration[];
}
async function bindConnection(registrationRef: string, requestId: string, capabilities?: string[], taskId?: string): Promise<UserConnection> {
  const value = connection(await request('/user-connections', 'POST', { registrationRef, requestId, ...(capabilities === undefined ? {} : { capabilities }), ...(taskId ? { taskId } : {}) }));
  if (value.registrationRef !== registrationRef || value.taskId !== (taskId ?? null) || capabilities !== undefined && (value.capabilities.length !== capabilities.length || capabilities.some(item => !value.capabilities.includes(item)))) throw invalid('连接确认与原登记或绑定范围不一致。');
  return value;
}
async function revokeConnection(ref: string, requestId: string): Promise<UserConnection> {
  const value = connection(await request(`/user-connections/${segment(ref)}/revoke`, 'POST', { requestId }), ref);
  if (value.status !== 'revoked' || value.available) throw invalid('连接撤销尚未确认。');
  return value;
}
async function inspectUserConnection(ref: string, signal?: AbortSignal): Promise<UserConnection> {
  return connection(await request(`/user-connections/${segment(ref)}`, 'GET', undefined, signal), ref);
}


function application(value: unknown): FactoryApplication {
  if (!record(value) || !reference(value) || typeof value.name !== 'string' || typeof value.description !== 'string'
      || !strings(value.discoveryKeywords) || typeof value.defaultForDiscovery !== 'boolean' || typeof value.defaultMode !== 'string'
      || !record(value.modes) || !Object.hasOwn(value.modes, value.defaultMode) || !Object.keys(value.modes).length) throw invalid('应用定义无法核对；暂时禁用装配。');
  for (const mode of Object.values(value.modes)) {
    if (!record(mode) || !Array.isArray(mode.materialRefs) || !mode.materialRefs.every(reference) || !record(mode.materialChoices)
        || !strings(mode.capabilities) || !record(mode.budget) || Object.values(mode.budget).some(item => typeof item !== 'number' || !Number.isFinite(item) || item < 0)
        || !record(mode.config) || !strings(mode.toolOrder) || !Array.isArray(mode.connectionRequirements)) throw invalid('应用装配范围无法核对。');
    if (mode.inputSchema !== undefined) applicationInputSchema(mode.inputSchema);
    for (const slot of Object.values(mode.materialChoices)) if (!record(slot) || !['skill', 'tool', 'prompt', 'knowledge', 'model', 'environment'].includes(String(slot.kind))
        || !reference(slot.defaultRef) || !Array.isArray(slot.allowedRefs) || !slot.allowedRefs.every(reference)) throw invalid('应用材料选项无法核对。');
    for (const requirement of mode.connectionRequirements) if (!record(requirement) || typeof requirement.name !== 'string'
        || !kinds.includes(String(requirement.kind)) || !strings(requirement.requiredCapabilities) || typeof requirement.required !== 'boolean') throw invalid('应用连接范围无法核对。');
  }
  return value as unknown as FactoryApplication;
}
function applicationVersion(value: unknown): ApplicationVersion {
  if (!record(value) || !record(value.governance) || typeof value.governance.author_id !== 'string'
      || !['draft', 'published', 'withdrawn', 'archived'].includes(String(value.governance.state)) || value.immutableBodyPreserved !== true) throw invalid('应用版本状态无法核对。');
  application(value.application); return value as unknown as ApplicationVersion;
}
function applicationReview(value: unknown): ApplicationReview {
  if (!record(value) || typeof value.id !== 'string' || !reference(value.applicationRef) || typeof value.authorId !== 'string'
      || !['pending', 'approved', 'denied'].includes(String(value.decision)) || !['draft', 'published', 'withdrawn', 'archived'].includes(String(value.state))
      || value.separateAdministratorRequired !== true || value.taskApprovalSeparate !== true) throw invalid('应用审查凭据无法核对。');
  const body = application(value.application);
  if (body.id !== value.applicationRef.id || body.version !== value.applicationRef.version || body.sha256 !== value.applicationRef.sha256) throw invalid('审查范围与不可变应用版本不一致。');
  return value as unknown as ApplicationReview;
}
function proposal(value: unknown, ownerId?: string): AssemblyProposal {
  if (!record(value) || typeof value.id !== 'string' || typeof value.ownerId !== 'string' || ownerId !== undefined && value.ownerId !== ownerId
      || !record(value.input) || !record(value.candidate) || !record(value.selection) || !strings(value.allowedActions)
      || !['pending', 'revised', 'rejected', 'accepted'].includes(String(value.state)) || typeof value.fingerprint !== 'string'
      || !value.allowedActions.every(item => ['revise', 'reject', 'accept'].includes(item))) throw invalid('装配提案无法核对。');
  const c = value.candidate;
  if (c.inputSchema !== undefined) {
    const schema = applicationInputSchema(c.inputSchema);
    applicationInputValues(schema, c.inputValues);
    if (!sameApplicationInputs(c.inputValues, value.input.inputValues ?? {})) throw invalid('应用输入与提案固定范围不一致。');
  } else if (c.inputValues !== undefined || value.input.inputValues !== undefined) throw invalid('提案输入缺少固定定义。');
  const snapshot = value.input.sourceSnapshotRef;
  if (snapshot !== undefined && (!sourceSnapshotReference(snapshot) || !sourceSnapshotReference(c.sourceSnapshotRef) || !record(c.bindingManifest)
      || !sourceSnapshotReference(c.bindingManifest.sourceSnapshotRef) || !sameSourceSnapshot(snapshot, c.sourceSnapshotRef)
      || !sameSourceSnapshot(snapshot, c.bindingManifest.sourceSnapshotRef))) throw invalid('来源快照与提案固定范围不一致。');
  if (snapshot === undefined && (c.sourceSnapshotRef !== undefined || record(c.bindingManifest) && c.bindingManifest.sourceSnapshotRef !== undefined)) throw invalid('提案增加了未选择的来源。');
  if (!reference(c.applicationRef) || typeof c.application !== 'string' || c.application !== c.applicationRef.id || typeof c.mode !== 'string'
      || typeof c.normalizedGoal !== 'string' || !Array.isArray(c.materialRefs) || !c.materialRefs.every(reference)
      || !Array.isArray(c.materials) || !strings(c.tools) || !strings(c.capabilities) || !record(c.budget) || !strings(c.missing)
      || !['ready', 'blocked'].includes(String(c.status)) || typeof c.syntheticFixture !== 'boolean'
      || !(c.executionBindings === null || record(c.executionBindings)) || !record(c.bindingManifest)) throw invalid('装配提案的预检范围不完整。');
  const materialBodies = c.materials;
  if (c.materialRefs.some(ref => !materialBodies.some((item: unknown) => record(item) && reference(item) && item.id === ref.id && item.version === ref.version && item.sha256 === ref.sha256))) throw invalid('装配材料与固定版本凭据不一致。');
  return value as unknown as AssemblyProposal;
}
function sealedPlan(value: unknown): Plan {
  if (!record(value) || typeof value.id !== 'string' || typeof value.fingerprint !== 'string' || typeof value.normalizedGoal !== 'string'
      || !reference(value.applicationRef) || !Array.isArray(value.materialRefs) || !value.materialRefs.every(reference)
      || !strings(value.capabilities) || !strings(value.missing) || !['ready', 'blocked'].includes(String(value.status))) throw invalid('最终方案无法核对；暂时不能创建任务。');
  if (value.inputSchema !== undefined) applicationInputValues(applicationInputSchema(value.inputSchema), value.inputValues);
  else if (value.inputValues !== undefined) throw invalid('方案输入缺少固定定义。');
  if (value.sourceSnapshotRef !== undefined && (!sourceSnapshotReference(value.sourceSnapshotRef) || !record(value.bindingManifest)
      || !sameSourceSnapshot(value.sourceSnapshotRef, value.bindingManifest.sourceSnapshotRef))) throw invalid('方案来源快照绑定无法核对。');
  if (value.sourceSnapshotRef === undefined && record(value.bindingManifest) && value.bindingManifest.sourceSnapshotRef !== undefined) throw invalid('方案来源快照绑定缺失。');
  return value as unknown as Plan;
}
async function applications(signal?: AbortSignal): Promise<FactoryApplication[]> {
  const values = await request<unknown>('/applications', 'GET', undefined, signal);
  if (!Array.isArray(values)) throw invalid('可用应用列表无法核对。'); return values.map(application);
}
async function applicationVersions(allAuthors = false, signal?: AbortSignal): Promise<ApplicationVersion[]> {
  const values = await request<unknown>(`/applications/definitions?allAuthors=${allAuthors}`, 'GET', undefined, signal);
  if (!Array.isArray(values)) throw invalid('应用版本列表无法核对。'); return values.map(applicationVersion);
}
async function applicationReviews(allAuthors = false, signal?: AbortSignal): Promise<ApplicationReview[]> {
  const values = await request<unknown>(`/applications/reviews?allAuthors=${allAuthors}`, 'GET', undefined, signal);
  if (!Array.isArray(values)) throw invalid('应用审查列表无法核对。'); return values.map(applicationReview);
}
const versionPath = (id: string, version: number) => `/applications/${segment(id)}/versions/${version}`;
async function propose(input: CompositionInput, requestId: string): Promise<AssemblyProposal> {
  return proposal(await request('/compositions/proposals', 'POST', { ...input, requestId }));
}
async function reviseProposal(id: string, input: CompositionInput, requestId: string): Promise<AssemblyProposal> {
  return proposal(await request(`/compositions/proposals/${segment(id)}/revise`, 'POST', { ...input, requestId }));
}
async function inspectProposal(id: string, signal?: AbortSignal): Promise<AssemblyProposal> {
  const value = proposal(await request(`/compositions/proposals/${segment(id)}`, 'GET', undefined, signal));
  if (value.id !== id) throw invalid('装配提案标识不一致。'); return value;
}

async function recoverProposal(id: string, signal?: AbortSignal): Promise<{ proposal: AssemblyProposal; plan: Plan | null }> {
  const raw = await request<unknown>(`/compositions/proposals/${segment(id)}/recovery`, 'GET', undefined, signal);
  if (!raw || typeof raw !== 'object' || !('proposal' in raw) || !('plan' in raw)
      || !('historical' in raw) || raw.historical !== true || !('executionAuthorized' in raw) || raw.executionAuthorized !== false) throw invalid('历史方案恢复凭据无法核对。');
  const item = proposal(raw.proposal), plan = raw.plan === null ? null : sealedPlan(raw.plan);
  if (item.id !== id || (item.state === 'accepted') !== (plan !== null)
      || plan && (plan.id !== item.planId || !('ownerId' in plan) || plan.ownerId !== item.ownerId || plan.normalizedGoal !== item.candidate.normalizedGoal
        || !sameApplicationInputs(plan.inputSchema, item.candidate.inputSchema) || !sameApplicationInputs(plan.inputValues, item.candidate.inputValues))) throw invalid('原提案与方案范围不一致。');
  return { proposal: item, plan };
}

export const api = {
  workflows: {
    get: (taskId: string, signal?: AbortSignal) => request<unknown>(`/workflows/${segment(taskId)}`, 'GET', undefined, signal),
    commandStatus: (taskId: string, commandId: string, signal?: AbortSignal) => request<unknown>(`/workflows/${segment(taskId)}/commands/${segment(commandId)}`, 'GET', undefined, signal),
    command: (taskId: string, command: WorkflowCommand) => request<unknown>(`/workflows/${segment(taskId)}/commands`, 'POST', validateWorkflowCommand(command)),
  },
  autoresearch: {
    presets: (signal?: AbortSignal) => request<unknown>('/autoresearch/presets', 'GET', undefined, signal),
    start: (input: { presetId: string; goal?: string; requestId: string }, signal?: AbortSignal) => request<unknown>('/autoresearch/runs', 'POST', input, signal),
    get: (id: string, signal?: AbortSignal) => request<unknown>(`/autoresearch/runs/${segment(id)}`, 'GET', undefined, signal),
    recover: (id: string, signal?: AbortSignal) => request<unknown>(`/autoresearch/requests/${segment(id)}`, 'GET', undefined, signal),
    cancel: (id: string, input: { requestId: string }, signal?: AbortSignal) => request<unknown>(`/autoresearch/runs/${segment(id)}/cancel`, 'POST', input, signal),
  },
  scheduleDiagnostics: {
    list: (after?: string, signal?: AbortSignal) => request<unknown>(`/schedule-management/diagnostic-schedules${after ? `?after=${encodeURIComponent(after)}` : ''}`, 'GET', undefined, signal),
    page: (id: string, after?: string, signal?: AbortSignal) => request<unknown>(`/schedule-management/${encodeURIComponent(id)}/diagnostics${after ? `?after=${encodeURIComponent(after)}` : ''}`, 'GET', undefined, signal),
  },
  schedules: {
    recover: (requestId: string, signal?: AbortSignal) => request<unknown>(`/schedule-management/commands/${encodeURIComponent(requestId)}`, 'GET', undefined, signal),
    metadata: (signal?: AbortSignal) => request<unknown>('/schedule-management/metadata', 'GET', undefined, signal),
    list: (after?: string, signal?: AbortSignal) => request<unknown>(`/schedule-management${after ? `?after=${encodeURIComponent(after)}` : ''}`, 'GET', undefined, signal),
    inspect: (id: string, signal?: AbortSignal) => request<unknown>(`/schedule-management/${encodeURIComponent(id)}`, 'GET', undefined, signal),
    preview: (input: { cron: string; timezone: string }, signal?: AbortSignal) => request<unknown>('/schedule-management/preview', 'POST', input, signal),
    create: (input: { planId: string; name: string; cron: string; timezone: string; requestId: string }) => request<unknown>('/schedule-management', 'POST', input),
    update: (id: string, input: { cron: string; timezone: string; requestId: string; expectedDefinitionFingerprint: string }) => request<unknown>(`/schedule-management/${encodeURIComponent(id)}`, 'PATCH', input),
    setEnabled: (id: string, input: { enabled: boolean; requestId: string; expectedDefinitionFingerprint: string }) => request<unknown>(`/schedule-management/${encodeURIComponent(id)}/enabled`, 'POST', input),
    occurrences: (id: string, after?: string, signal?: AbortSignal) => request<unknown>(`/schedule-management/${encodeURIComponent(id)}/occurrences${after ? `?after=${encodeURIComponent(after)}` : ''}`, 'GET', undefined, signal),
  },
  comparisons: { catalog: (signal?: AbortSignal) => request<unknown>('/comparisons/catalog', 'GET', undefined, signal) },
  synthesis: {
    preview: (taskId: string, signal?: AbortSignal) => request<unknown>(`/synthesis/sources/${segment(taskId)}`, 'GET', undefined, signal),
    list: (taskId: string, after?: string, signal?: AbortSignal) => request<unknown>(`/synthesis/snapshots?${new URLSearchParams({ sourceTaskId: taskId, limit: '20', ...(after ? { after } : {}) })}`, 'GET', undefined, signal),
    inspect: (id: string, signal?: AbortSignal) => request<unknown>(`/synthesis/snapshots/${segment(id)}`, 'GET', undefined, signal),
    current: (id: string, signal?: AbortSignal) => request<unknown>(`/synthesis/snapshots/${segment(id)}/current`, 'GET', undefined, signal),
    create: (input: SynthesisCreate) => request<unknown>('/synthesis/snapshots', 'POST', input),
  },
  storage: async (owner: string, signal?: AbortSignal) => storageSummary(await request<StorageSummary>('/storage', 'GET', undefined, signal), owner),
  retentionPlan: async (owner: string, objectId: string, requestId: string) => retentionReceipt(await request<RetentionReceipt>('/storage/retention/plans', 'POST', { objectId, requestId }), owner),
  retention: async (owner: string, id: string) => retentionReceipt(await request<RetentionReceipt>(`/storage/retention/plans/${segment(id)}`), owner, id),
  retentionAction: async (owner: string, id: string, action: 'quarantine' | 'restore' | 'purge') => retentionReceipt(await request<RetentionReceipt>(`/storage/retention/plans/${segment(id)}/${action}`, 'POST'), owner, id),
  submitControl, controlReceipt, controlCommands,
  dispatchControl: async (owner: string, task: string, commandId: string) => validateControlReceipt(await request(`/jobs/${segment(task)}/commands/${segment(commandId)}/dispatch`, 'POST'), owner, task, commandId),
  acknowledgeControl: async (owner: string, task: string, commandId: string) => validateControlReceipt(await request(`/jobs/${segment(task)}/commands/${segment(commandId)}/acknowledge`, 'POST'), owner, task, commandId),
  applications, applicationVersions, applicationReviews, propose, reviseProposal, inspectProposal, recoverProposal,
  proposalInbox: (after?: string, signal?: AbortSignal) => request<unknown>(`/compositions/proposals${after ? `?after=${encodeURIComponent(after)}` : ''}`, 'GET', undefined, signal),
  draftApplication: async (definition: Record<string, unknown>, requestId: string) => application(await request('/applications/drafts', 'POST', { definition, requestId })),
  reviseApplication: async (id: string, version: number, definition: Record<string, unknown>, requestId: string) => application(await request(`${versionPath(id, version)}/revise`, 'POST', { definition, requestId })),
  requestApplicationPublication: async (id: string, version: number, requestId: string) => applicationReview(await request(`${versionPath(id, version)}/review`, 'POST', { requestId })),
  decideApplicationReview: async (id: string, approved: boolean, requestId: string) => applicationReview(await request(`/applications/reviews/${segment(id)}/decision`, 'POST', { approved, requestId })),
  archiveApplication: (id: string, version: number, reason: string, requestId: string) => request(`${versionPath(id, version)}/archive`, 'POST', { reason, requestId }),
  withdrawApplication: (id: string, version: number, reason: string, requestId: string) => request(`${versionPath(id, version)}/withdraw`, 'POST', { reason, requestId }),
  rejectProposal: async (id: string, requestId: string) => proposal(await request(`/compositions/proposals/${segment(id)}/reject`, 'POST', { requestId })),
  acceptProposal: async (id: string, requestId: string) => sealedPlan(await request(`/compositions/proposals/${segment(id)}/accept`, 'POST', { requestId })),
  userConnections, connectionRegistrations, bindConnection, revokeConnection, inspectUserConnection,
  events,
  resourceLeases: (after?: string, signal?: AbortSignal) => request<{ leases: unknown[]; nextCursor: string | null }>('/resources/leases' + (after ? '?after=' + encodeURIComponent(after) : ''), 'GET', undefined, signal),
  session: (signal?: AbortSignal) => request<User>('/session', 'GET', undefined, signal),
  login: (persona: 'manager' | 'alice' | 'bob') => request<User>('/demo/login', 'POST', { persona }),
  logout: () => request<void>('/logout', 'POST'),
  status: (signal?: AbortSignal) => request<FactoryStatus>('/status', 'GET', undefined, signal),
  materials: (signal?: AbortSignal) => request<FactoryMaterial[]>('/materials', 'GET', undefined, signal),
  connections: userConnections,
  createMaterial: (draft: MaterialDraft & { requestId: string }) => request<FactoryMaterial>('/materials', 'POST', draft),
  publish: (material: FactoryMaterial, requestId: string) => request<MaterialReview>(`/materials/${segment(material.id)}/${material.version}/publish`, 'POST', { requestId }),
  plan: (topic: string, mode: 'literature' | 'experiment', requestId: string) => request<Plan>('/plans', 'POST', { topic, mode, requestId }),
  instantiate, resumeRemote,
  governanceDraft: (definition: Record<string, unknown>, requestId: string) => request<FactoryMaterial>('/material-governance/drafts', 'POST', { definition, requestId }),
  importMaterials: (definitions: Record<string, unknown>[], requestId: string) => request<{ materials: FactoryMaterial[]; outcomeSource: string; executesCode: boolean }>('/material-governance/imports', 'POST', { definitions, requestId }),
  materialPolicy: (signal?: AbortSignal) => request<MaterialGovernancePolicy>('/material-governance/policy', 'GET', undefined, signal),
  requestMaterialPublication: (materialId: string, version: number, requestId: string) => request<MaterialReview>('/material-governance/reviews', 'POST', { materialId, version, requestId }),
  materialReviews: (allAuthors = false, signal?: AbortSignal) => request<MaterialReview[]>(`/material-governance/reviews?allAuthors=${allAuthors}`, 'GET', undefined, signal),
  decideMaterialReview: (id: string, approved: boolean, requestId: string) => request<MaterialReview>(`/material-governance/reviews/${segment(id)}/decision`, 'POST', { approved, requestId }),
  archiveMaterial: (id: string, version: number, reason: string, requestId: string) => request(`/material-governance/versions/${segment(id)}/${version}/archive`, 'POST', { reason, requestId }),
  withdrawMaterial: (id: string, version: number, reason: string, requestId: string) => request(`/material-governance/versions/${segment(id)}/${version}/withdraw`, 'POST', { reason, requestId }),
  executionTargets: (signal?: AbortSignal) => request<ExecutionTarget[]>('/execution-targets', 'GET', undefined, signal),
  planAuthorization: (id: string, signal?: AbortSignal) => request<PlanAuthorization>(`/plans/${segment(id)}/authorization`, 'GET', undefined, signal),
  inspectPlanReview: (id: string, signal?: AbortSignal) => request<PlanReview>(`/plan-reviews/${segment(id)}`, 'GET', undefined, signal),
  requestPlanReview: (planId: string, requestId: string) => request<PlanReview>('/plan-reviews', 'POST', { planId, requestId }),
  planReviews: (allOwners = false, signal?: AbortSignal, planId?: string) => request<PlanReview[]>(`/plan-reviews?allOwners=${allOwners}${planId ? `&planId=${segment(planId)}` : ''}`, 'GET', undefined, signal),
  decidePlanReview: (id: string, approved: boolean, requestId: string) => request<PlanReview>(`/plan-reviews/${segment(id)}/decision`, 'POST', { approved, requestId }),
  jobs: (signal?: AbortSignal) => request<FactoryJob[]>('/jobs', 'GET', undefined, signal),
  detail: (id: string, signal?: AbortSignal) => request<JobDetail>(`/jobs/${segment(id)}`, 'GET', undefined, signal),
  cancel: (id: string) => request<FactoryJob>(`/jobs/${segment(id)}/cancel`, 'POST'),
  createChild: (id: string, goal: string, mode: string, requestId: string) => request<ChildReceipt>(`/jobs/${segment(id)}/children`, 'POST', { goal, mode, requestId }),
  group: (id: string) => request<DelegationGroup>(`/jobs/${segment(id)}/group`),
  answer: (id: string, questionId: string, version: number, answer: string) => request<FactoryJob>(`/jobs/${segment(id)}/answer`, 'POST', { questionId, version, answer }),
  approve: (id: string, requirementId: string, version: number, approved: boolean) => request<FactoryJob>(`/jobs/${segment(id)}/approve`, 'POST', { requirementId, version, approved }),
  reconcile: (id: string) => request<FactoryJob>(`/jobs/${segment(id)}/reconcile`, 'POST'),
  artifactUrl: (jobId: string, artifactId: string) => `${base}/jobs/${segment(jobId)}/artifacts/${segment(artifactId)}`,
};
