import type { EventPage, MaterialGovernancePolicy, MaterialReview, ExecutionTarget, PlanAuthorization, PlanReview, ChildReceipt, DelegationGroup, Connection, FactoryJob, FactoryMaterial, FactoryStatus, JobDetail, MaterialDraft, Plan, User } from './models.js';

export class ApiError extends Error {
  constructor(message: string, public readonly status: number, public readonly code?: string) { super(message); }
}
const base = '/api/factory';
async function request<T>(path: string, method = 'GET', body?: unknown, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${base}${path}`, {
      method, credentials: 'same-origin', signal,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') throw error;
    throw new ApiError('无法连接服务。检查网络后重试；创建请求会沿用原请求标识。', 0, 'OFFLINE');
  }
  const text = await response.text();
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
export const api = {
  events,
  session: (signal?: AbortSignal) => request<User>('/session', 'GET', undefined, signal),
  login: (persona: 'manager' | 'alice' | 'bob') => request<User>('/demo/login', 'POST', { persona }),
  logout: () => request<void>('/logout', 'POST'),
  status: (signal?: AbortSignal) => request<FactoryStatus>('/status', 'GET', undefined, signal),
  materials: (signal?: AbortSignal) => request<FactoryMaterial[]>('/materials', 'GET', undefined, signal),
  connections: (signal?: AbortSignal) => request<Connection[]>('/connections', 'GET', undefined, signal),
  createMaterial: (draft: MaterialDraft & { requestId: string }) => request<FactoryMaterial>('/materials', 'POST', draft),
  publish: (material: FactoryMaterial, requestId: string) => request<MaterialReview>(`/materials/${segment(material.id)}/${material.version}/publish`, 'POST', { requestId }),
  plan: (topic: string, mode: 'literature' | 'experiment', requestId: string) => request<Plan>('/plans', 'POST', { topic, mode, requestId }),
  instantiate,
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
  planReviews: (allOwners = false, signal?: AbortSignal) => request<PlanReview[]>(`/plan-reviews?allOwners=${allOwners}`, 'GET', undefined, signal),
  decidePlanReview: (id: string, approved: boolean, requestId: string) => request<PlanReview>(`/plan-reviews/${segment(id)}/decision`, 'POST', { approved, requestId }),
  jobs: (signal?: AbortSignal) => request<FactoryJob[]>('/jobs', 'GET', undefined, signal),
  detail: (id: string, signal?: AbortSignal) => request<JobDetail>(`/jobs/${segment(id)}`, 'GET', undefined, signal),
  cancel: (id: string) => request<FactoryJob>(`/jobs/${segment(id)}/cancel`, 'POST'),
  createChild: (id: string, goal: string, mode: 'literature' | 'experiment', requestId: string) => request<ChildReceipt>(`/jobs/${segment(id)}/children`, 'POST', { goal, mode, requestId }),
  group: (id: string) => request<DelegationGroup>(`/jobs/${segment(id)}/group`),
  answer: (id: string, questionId: string, version: number, answer: string) => request<FactoryJob>(`/jobs/${segment(id)}/answer`, 'POST', { questionId, version, answer }),
  approve: (id: string, requirementId: string, version: number, approved: boolean) => request<FactoryJob>(`/jobs/${segment(id)}/approve`, 'POST', { requirementId, version, approved }),
  reconcile: (id: string) => request<FactoryJob>(`/jobs/${segment(id)}/reconcile`, 'POST'),
  artifactUrl: (jobId: string, artifactId: string) => `${base}/jobs/${segment(jobId)}/artifacts/${segment(artifactId)}`,
};
