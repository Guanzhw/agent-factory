import type { ChildReceipt, DelegationGroup, Connection, FactoryJob, FactoryMaterial, FactoryStatus, JobDetail, MaterialDraft, Plan, User } from './models.js';

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
async function instantiate(planId: string, requestId: string): Promise<FactoryJob> {
  try {
    const job = await request<FactoryJob>('/instances', 'POST', { planId, requestId });
    if (typeof job?.id !== 'string' || job.planId !== planId) throw new ApiError('创建回执不完整，请核对原请求。', 202, 'INVALID_RESPONSE');
    return job;
  } catch (error) {
    const ambiguous = error instanceof TypeError || error instanceof ApiError &&
      (error.status === 0 || error.status === 408 || error.status >= 500 || error.code === 'INVALID_RESPONSE');
    if (ambiguous) {
      try {
        const receipt = await request<{ requestId: string; planId: string; taskId: string }>(`/requests/${segment(requestId)}`);
        if (receipt.requestId !== requestId || receipt.planId !== planId || typeof receipt.taskId !== 'string') throw error;
        const detail = await request<JobDetail>(`/jobs/${segment(receipt.taskId)}`);
        if (detail.job.id !== receipt.taskId || detail.job.planId !== planId) throw error;
        return detail.job;
      } catch { /* Keep the original uncertainty; never issue a second POST. */ }
    }
    throw error;
  }
}
export const api = {
  session: (signal?: AbortSignal) => request<User>('/session', 'GET', undefined, signal),
  login: (persona: 'manager' | 'alice' | 'bob') => request<User>('/demo/login', 'POST', { persona }),
  logout: () => request<void>('/logout', 'POST'),
  status: (signal?: AbortSignal) => request<FactoryStatus>('/status', 'GET', undefined, signal),
  materials: (signal?: AbortSignal) => request<FactoryMaterial[]>('/materials', 'GET', undefined, signal),
  connections: (signal?: AbortSignal) => request<Connection[]>('/connections', 'GET', undefined, signal),
  createMaterial: (draft: MaterialDraft) => request<FactoryMaterial>('/materials', 'POST', draft),
  publish: (material: FactoryMaterial) => request<FactoryMaterial>(`/materials/${segment(material.id)}/${material.version}/publish`, 'POST'),
  plan: (topic: string, mode: 'literature' | 'experiment', requestId: string) => request<Plan>('/plans', 'POST', { topic, mode, requestId }),
  instantiate,
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
