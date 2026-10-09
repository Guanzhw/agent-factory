import { ApiError, factoryRequest } from './api.js';

export interface OwnerModel {
  reference: string; revision: string; connectionRef: string; ownerId: string;
  provider: 'openai' | 'openai-compatible'; baseURL: string; model: string;
  credentialRef: string; credentialRevision: string; updatedAt: string;
  status: 'configured' | 'credential_unavailable' | 'revoked'; available: boolean; isDefault: boolean;
}
export interface ModelCapabilities { enabled: boolean; providers: string[]; liveCompatibilityVerified: boolean }
export interface ModelConfiguration {
  provider: OwnerModel['provider']; baseURL: string; model: string;
  credentialRef: string; credentialRevision: string; requestId: string;
}
export class ModelRequestError extends Error {
  constructor(public readonly status: number, public readonly code?: string) {
    super(status === 403 ? '当前账号没有此操作权限。' : status === 401 ? '登录已过期，请重新登录后核对原请求。'
      : status === 422 ? '配置未被接受，请检查提供方、端点和模型名称。' : '请求尚未确认，请核对原操作。');
  }
}
// Neither secret inputs nor raw server/provider error text reach the UI.
async function safe<T>(path: string, method = 'GET', body?: unknown, signal?: AbortSignal): Promise<T> {
  try { return await factoryRequest<T>(path, method, body, signal); }
  catch (error) { throw new ModelRequestError(error instanceof ApiError ? error.status : 0, error instanceof ApiError ? error.code : undefined); }
}
export function ownerModel(value: unknown, owner: string): OwnerModel {
  const m = value as OwnerModel;
  const fields = new Set(['reference', 'revision', 'connectionRef', 'ownerId', 'provider', 'baseURL', 'model', 'credentialRef', 'credentialRevision', 'updatedAt', 'status', 'available', 'isDefault', 'hardExternalBudgetEnforced']);
  if (!m || typeof m !== 'object' || Array.isArray(m) || Object.keys(m).some(key => !fields.has(key))
      || m.ownerId !== owner || !['openai', 'openai-compatible'].includes(m.provider)
      || !['reference', 'revision', 'connectionRef', 'credentialRef', 'credentialRevision'].every(key => typeof m[key as keyof OwnerModel] === 'string' && /^[A-Za-z0-9_.:-]{1,200}$/.test(String(m[key as keyof OwnerModel])))
      || typeof m.baseURL !== 'string' || typeof m.model !== 'string' || !m.model || m.model.length > 120
      || !['configured', 'credential_unavailable', 'revoked'].includes(m.status)
      || typeof m.isDefault !== 'boolean' || typeof m.available !== 'boolean' || m.available !== (m.status === 'configured')) {
    throw new ModelRequestError(200, 'INVALID_RESPONSE');
  }
  try {
    const url = new URL(m.baseURL);
    if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash || url.pathname !== '/v1') throw new Error();
  } catch { throw new ModelRequestError(200, 'INVALID_RESPONSE'); }
  return m;
}
const ref = encodeURIComponent;
export const ownerModelApi = {
  capabilities: async (signal?: AbortSignal) => {
    const value = await safe<ModelCapabilities>('/personal-models/capabilities', 'GET', undefined, signal);
    if (!value || typeof value.enabled !== 'boolean' || typeof value.liveCompatibilityVerified !== 'boolean' || !Array.isArray(value.providers) || value.providers.some(p => !['openai', 'openai-compatible'].includes(p))) throw new ModelRequestError(200, 'INVALID_RESPONSE');
    return value;
  },
  list: async (owner: string, signal?: AbortSignal) => {
    const values = await safe<unknown>('/personal-models', 'GET', undefined, signal);
    if (!Array.isArray(values) || values.length > 100) throw new ModelRequestError(200, 'INVALID_RESPONSE');
    return values.map(value => ownerModel(value, owner));
  },
  configure: async (owner: string, body: ModelConfiguration, reference?: string) => ownerModel(await safe(`/personal-models${reference ? `/${ref(reference)}/configure` : ''}`, 'POST', body), owner),
  default: async (owner: string, reference: string, requestId: string) => ownerModel(await safe(`/personal-models/${ref(reference)}/default`, 'POST', { requestId }), owner),
  revoke: async (owner: string, reference: string, requestId: string) => ownerModel(await safe(`/personal-models/${ref(reference)}/revoke`, 'POST', { requestId }), owner),
  rotateCredential: (reference: string, credentialRevision: string, password: string, requestId: string) => safe<{ credentialRef: string; credentialRevision: string; status: string; providerId: string; destination: string }>(`/personal-credentials/${ref(reference)}/rotate`, 'POST', { credentialRevision, username: 'api-key', password, requestId }),
};
