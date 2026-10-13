import { ApiError, factoryRequest } from './api.js';
import type { FactoryApplication, FactoryMaterial } from './models.js';

const invalid = () => new ApiError('发布回执与当前成员或所选版本不一致，请核对原请求。', 200, 'INVALID_RESPONSE');
const hash = (value: unknown) => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);

/** Shared definitions are published explicitly; each request retains its owner and idempotency key. */
export const publicationApi = {
  async publishApplication(ownerId: string, id: string, version: number, requestId: string): Promise<FactoryApplication> {
    const saved = await factoryRequest<FactoryApplication>(`/applications/${encodeURIComponent(id)}/versions/${version}/publish`, 'POST', { requestId }, undefined, ownerId);
    if (saved?.id !== id || saved.version !== version || !hash(saved.sha256)) throw invalid();
    return saved;
  },
  async publishMaterial(ownerId: string, id: string, version: number, requestId: string): Promise<FactoryMaterial> {
    const saved = await factoryRequest<FactoryMaterial>(`/material-governance/versions/${encodeURIComponent(id)}/${version}/publish`, 'POST', { requestId }, undefined, ownerId);
    if (saved?.id !== id || saved.version !== version || !hash(saved.sha256) || saved.published !== true) throw invalid();
    return saved;
  },
};
