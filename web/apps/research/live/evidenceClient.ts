import { ApiError, factoryRequest } from '../../../api.js';
import { assertAuthEpoch, authEpoch, expireBrowserSession } from '../../../browserAuth.js';
import type { Page } from '../types.js';
export interface EvidenceEntry { id: string; ownerId: string; createdAt: string }
export interface ResearchAssociation extends EvidenceEntry {
  sourceIds: string[]; inputContentIds: string[];
  analysis: { answer: string; citations: string[]; evidenceLevel: 'agent_analysis'; relation: string };
}
export interface ResearchDelivery extends EvidenceEntry {
  schema: number; kind: 'research.delivery'; projectId: string; goalVersion: number;
  sourceIds: string[]; recordIds: string[]; records: Record<string, unknown>[];
  missingEvidence: string[]; verificationStatus: 'unverified';
  remainingQuestions: { status: 'not_provided' }; evidenceFormat: string; continuation: string;
  ending?: { ownerId: string; sourceIds: string[]; outcome: 'met' | 'not_met' | 'cancelled'; reason: string;
    goalVersion: number; endedAt: string; resourceCleanup: string; verificationStatus?: string } | null;
}
const path = '/research';
export const evidenceApi = {
  associations: (owner: string, after: string, signal?: AbortSignal) => factoryRequest<Page<ResearchAssociation>>(`${path}/associations?limit=20&after=${encodeURIComponent(after)}`, 'GET', undefined, signal, owner),
  association: (owner: string, id: string, signal?: AbortSignal) => factoryRequest<ResearchAssociation>(`${path}/associations/${encodeURIComponent(id)}`, 'GET', undefined, signal, owner),
  deliveries: (owner: string, after: string, signal?: AbortSignal) => factoryRequest<Page<EvidenceEntry>>(`${path}/deliveries?limit=20&after=${encodeURIComponent(after)}`, 'GET', undefined, signal, owner),
  delivery: (owner: string, id: string, signal?: AbortSignal) => factoryRequest<ResearchDelivery>(`${path}/deliveries/${encodeURIComponent(id)}`, 'GET', undefined, signal, owner),
  create: (owner: string, project: string, body: { requestId: string; expectedVersion: number }) => factoryRequest<ResearchDelivery>(`${path}/projects/${encodeURIComponent(project)}/deliveries`, 'POST', body, undefined, owner),
};
export async function downloadResearchDelivery(owner: string, id: string, signal: AbortSignal): Promise<Blob> {
  const epoch = authEpoch();
  const response = await fetch(`/api/factory/research/deliveries/${encodeURIComponent(id)}/download`, { credentials: 'same-origin', redirect: 'error', cache: 'no-store', signal, headers: { 'X-Factory-Expected-Owner': owner } });
  assertAuthEpoch(epoch);
  if (response.status === 401) expireBrowserSession();
  if (!response.ok) throw new ApiError(`成果下载返回 ${response.status}，未保存文件；请核对当前来源权限。`, response.status);
  if (response.headers.get('Content-Type')?.split(';')[0] !== 'application/zip') throw new ApiError('成果响应不是ZIP，未保存文件。', 200, 'INVALID_RESPONSE');
  const blob = await response.blob();
  assertAuthEpoch(epoch); signal.throwIfAborted();
  return blob;
}
