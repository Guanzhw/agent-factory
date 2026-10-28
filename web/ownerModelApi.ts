import { ApiError, factoryRequest } from './api.js';
import { modelEndpoint } from './modelEndpoint.js';
import { validModelProtocol, validThinkingMetadata, type ModelProtocol } from './modelProviderConfig.js';
export { validThinkingMetadata } from './modelProviderConfig.js';

interface ModelMetadata {
  reference: string; revision: string; connectionRef?: string; ownerId: string;
  visibility: 'personal' | 'team';
  provider: 'openai' | 'openai-compatible'; baseURL: string; model: string;
  protocol?: ModelProtocol;
  updatedAt: string;
  thinkingMode?: 'disabled';
  maxOutputTokens?: number;
  status: 'configured' | 'credential_unavailable' | 'revoked'; available: boolean; isDefault: boolean;
}
export type OwnerModel = ModelMetadata & ({ isOwner: true; credentialRef: string | null; credentialRevision: string | null }
  | { isOwner: false; credentialRef?: never; credentialRevision?: never });
export interface ModelCapabilities { enabled: boolean; credentialsEnabled?: boolean; providers: string[]; liveCompatibilityVerified: boolean; protocols?: ModelProtocol[] }
export interface ModelConfiguration {
  provider: OwnerModel['provider']; baseURL: string; model: string;
  credentialRef?: string; credentialRevision?: string; requestId: string;
  protocol?: ModelProtocol;
  thinkingMode?: 'default' | 'disabled';
  maxOutputTokens?: number;
}
export interface OwnerModelReceipt {
  ownerId: string; requestId: string; action: 'model.configure' | 'model.default' | 'model.revoke' | 'model.sharing';
  result: OwnerModel; completedAt: string;
}
export class ModelRequestError extends Error {
  constructor(public readonly status: number, public readonly code?: string) {
    super(status === 403 ? '当前账号没有此操作权限。' : status === 401 ? '登录已过期，请重新登录后核对原请求。'
      : status === 422 ? '配置未被接受，请检查提供方、端点、模型名称和输出上限。' : '请求尚未确认，请核对原操作。');
  }
}
// Neither secret inputs nor raw server/provider error text reach the UI.
async function safe<T>(path: string, method = 'GET', body?: unknown, signal?: AbortSignal, expectedOwner?: string): Promise<T> {
  try { return await factoryRequest<T>(path, method, body, signal, expectedOwner); }
  catch (error) { throw new ModelRequestError(error instanceof ApiError ? error.status : 0, error instanceof ApiError ? error.code : undefined); }
}
export function validOutputTokens(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value > 0;
}
export function ownerModel(value: unknown, owner: string): OwnerModel {
  const m = value as Record<string, unknown>;
  if (!m || typeof m !== 'object' || Array.isArray(m)
      || typeof m.ownerId !== 'string' || m.isOwner !== (m.ownerId === owner)
      || !['personal', 'team'].includes(String(m.visibility)) || !m.isOwner && m.visibility !== 'team'
      || !['openai', 'openai-compatible'].includes(String(m.provider))
      || !['reference', 'revision'].every(key => typeof m[key] === 'string' && /^[A-Za-z0-9_.:-]{1,200}$/.test(String(m[key])))
      || (m.isOwner ? !(m.credentialRef === null && m.credentialRevision === null || ['credentialRef', 'credentialRevision'].every(key => typeof m[key] === 'string' && /^[A-Za-z0-9_.:-]{1,200}$/.test(String(m[key]))))
        : 'credentialRef' in m || 'credentialRevision' in m)
      || m.isOwner && typeof m.connectionRef !== 'string'
      || 'connectionRef' in m && (typeof m.connectionRef !== 'string' || !/^[A-Za-z0-9_.:-]{1,200}$/.test(m.connectionRef))
      || typeof m.baseURL !== 'string' || typeof m.model !== 'string' || !m.model || m.model.length > 120
      || typeof m.updatedAt !== 'string' || !Number.isFinite(Date.parse(m.updatedAt))
      || Object.prototype.hasOwnProperty.call(m, 'protocol') && !validModelProtocol(m.protocol)
      || !validThinkingMetadata(m as { baseURL: string; model: string; thinkingMode?: unknown })
      || Object.prototype.hasOwnProperty.call(m, 'maxOutputTokens') && !validOutputTokens(m.maxOutputTokens)
      || !['configured', 'credential_unavailable', 'revoked'].includes(String(m.status))
      || typeof m.isDefault !== 'boolean' || typeof m.available !== 'boolean' || m.available !== (m.status === 'configured')) {
    throw new ModelRequestError(200, 'INVALID_RESPONSE');
  }
  try {
    if (modelEndpoint(m.baseURL) !== m.baseURL) throw new Error();
  } catch { throw new ModelRequestError(200, 'INVALID_RESPONSE'); }
  return {
    reference: m.reference as string, revision: m.revision as string,
    visibility: m.visibility as OwnerModel['visibility'], isOwner: m.isOwner as boolean,
    ...('connectionRef' in m ? { connectionRef: m.connectionRef as string } : {}),
    ownerId: m.ownerId as string, provider: m.provider as OwnerModel['provider'], baseURL: m.baseURL as string,
    model: m.model as string, ...(m.isOwner ? { credentialRef: m.credentialRef as string | null, credentialRevision: m.credentialRevision as string | null } : {}),
    updatedAt: m.updatedAt as string, ...(Object.prototype.hasOwnProperty.call(m, 'protocol') ? { protocol: m.protocol as ModelProtocol } : {}),
    ...(Object.prototype.hasOwnProperty.call(m, 'thinkingMode') ? { thinkingMode: m.thinkingMode as 'disabled' } : {}),
    ...(Object.prototype.hasOwnProperty.call(m, 'maxOutputTokens') ? { maxOutputTokens: m.maxOutputTokens as number } : {}),
    status: m.status as OwnerModel['status'], available: m.available as boolean, isDefault: m.isDefault as boolean,
  } as OwnerModel;
}
const ref = encodeURIComponent;
export const ownerModelApi = {
  capabilities: async (signal?: AbortSignal) => {
    const value = await safe<ModelCapabilities>('/personal-models/capabilities', 'GET', undefined, signal);
    if (!value || typeof value.enabled !== 'boolean' || typeof value.liveCompatibilityVerified !== 'boolean' || !Array.isArray(value.providers) || value.providers.some(p => !['openai', 'openai-compatible'].includes(String(p)))
        || Object.prototype.hasOwnProperty.call(value, 'protocols') && (!Array.isArray(value.protocols) || value.protocols.some(p => !validModelProtocol(p)))) throw new ModelRequestError(200, 'INVALID_RESPONSE');
    return { enabled: value.enabled, ...(value.credentialsEnabled !== undefined ? { credentialsEnabled: value.credentialsEnabled } : {}), providers: [...value.providers], liveCompatibilityVerified: value.liveCompatibilityVerified,
      ...(value.protocols ? { protocols: [...value.protocols] } : {}) };
  },
  list: async (owner: string, signal?: AbortSignal) => {
    const values = await safe<unknown>('/personal-models', 'GET', undefined, signal, owner);
    if (!Array.isArray(values) || values.length > 100) throw new ModelRequestError(200, 'INVALID_RESPONSE');
    return values.map(value => ownerModel(value, owner));
  },
  recover: async (owner: string, requestId: string): Promise<OwnerModelReceipt> => {
    const raw = await safe<unknown>(`/personal-models/requests/${ref(requestId)}`, 'GET', undefined, undefined, owner);
    const receipt = raw as Record<string, unknown>;
    if (!receipt || typeof receipt !== 'object' || Array.isArray(receipt) || receipt.ownerId !== owner || receipt.requestId !== requestId
        || !['model.configure', 'model.default', 'model.revoke', 'model.sharing'].includes(String(receipt.action))
        || typeof receipt.completedAt !== 'string' || !Number.isFinite(Date.parse(receipt.completedAt))) throw new ModelRequestError(200, 'INVALID_RESPONSE');
    return { ownerId: owner, requestId, action: receipt.action as OwnerModelReceipt['action'], result: ownerModel(receipt.result, owner), completedAt: receipt.completedAt };
  },
  configure: async (owner: string, body: ModelConfiguration, reference?: string) => ownerModel(await safe(`/personal-models${reference ? `/${ref(reference)}/configure` : ''}`, 'POST', body, undefined, owner), owner),
  default: async (owner: string, reference: string, requestId: string) => ownerModel(await safe(`/personal-models/${ref(reference)}/default`, 'POST', { requestId }, undefined, owner), owner),
  revoke: async (owner: string, reference: string, requestId: string) => ownerModel(await safe(`/personal-models/${ref(reference)}/revoke`, 'POST', { requestId }, undefined, owner), owner),
  sharing: async (owner: string, reference: string, visibility: 'personal' | 'team', requestId: string) => ownerModel(await safe(`/personal-models/${ref(reference)}/sharing`, 'POST', { visibility, requestId }, undefined, owner), owner),
};
