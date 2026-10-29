import { factoryRequest } from '../../../api.js';
import type { MaterialReference } from '../../../models.js';
import type { ResearchAgreement, Page } from '../types.js';
import type { SetupIntent } from './setupClient.js';

export type QuestionBudget = { caps: ResearchAgreement['budget']; perQuestionCaps: ResearchAgreement['budget']; deadline: number };
export interface AssistantConfiguration { associations?: { enabled: boolean; maxRecipients: number } | null; applicationRef: MaterialReference; connectionRefs: Record<string, string>; budget: QuestionBudget }
export interface ResearchAssistant {
  id: string; ownerId: string; configurationRevision: number;
  qa: { state: 'unconfigured' } | (AssistantConfiguration & { state: 'configured'; endpointId: string; scopeId: string; available: boolean; unavailableCode?: string; accounting: { mode: 'operational_limits_only'; tokenMetered: false; costMetered: false; notice: string } });
}
export interface ResearchPeer { id: string; ownerId: string; displayName: string; qaAvailable: boolean }
export interface QASetup { id: string; state: 'draft' | 'published'; applicationRef: MaterialReference | null; connectionRefs: Record<string, string>; preview: { mode: 'qa'; name: string; modelConnectionRef: string; budget: SetupIntent['budget'] } }
export interface ResearchQuestion {
  id: string; senderId: string; recipientId: string; endpointId: string; text: string; createdAt: string;
  delivery: { state: string; taskId: string | null; runId: string | null };
  reply: null | { state: 'source_unavailable' } | { state: 'available'; text: string; contentIds: string[]; createdAt: string };
  allowedActions?: 'recover'[]; recoveryCode?: string | null;
  sessionId?: string; requestId?: string; assistantId?: string;
  origin?: 'manual' | 'agent';
  collaboration?: {
    originTurnId: string; state: 'waiting' | 'pending' | 'included' | 'blocked' | 'stopped';
    code?: string; includedTurnId?: string; continuedTurnId?: string;
  };
}
export interface ResearchSource { id: string; ownerId: string; source: Record<string, unknown>; content: Record<string, unknown>; verificationStatus: string; createdAt: string }
const base = '/research';
export const assistantApi = {
  me: (owner: string, signal?: AbortSignal) => factoryRequest<{ assistant: ResearchAssistant | null }>(`${base}/assistants/me`, 'GET', undefined, signal, owner),
  create: (owner: string, body: { requestId: string }) => factoryRequest<ResearchAssistant>(`${base}/assistants`, 'POST', body, undefined, owner),
  configure: (owner: string, body: AssistantConfiguration & { requestId: string; expectedRevision: number }) => factoryRequest<ResearchAssistant>(`${base}/assistants/me/configurations`, 'POST', body, undefined, owner),
  directory: (owner: string, after: string, signal?: AbortSignal) => factoryRequest<Page<ResearchPeer>>(`${base}/assistants?limit=20&after=${encodeURIComponent(after)}`, 'GET', undefined, signal, owner),
  draft: (owner: string, body: { requestId: string; name: string; modelConnectionRef: string; budget: SetupIntent['budget'] }) => factoryRequest<QASetup>(`${base}/setup/qa/drafts`, 'POST', body, undefined, owner),
  setup: (owner: string, id: string, signal?: AbortSignal) => factoryRequest<QASetup>(`${base}/setup/${encodeURIComponent(id)}`, 'GET', undefined, signal, owner),
  publish: (owner: string, id: string, body: { requestId: string }) => factoryRequest<QASetup>(`${base}/setup/${encodeURIComponent(id)}/publish`, 'POST', body, undefined, owner),
  ask: (owner: string, peer: string, body: { requestId: string; text: string }) => factoryRequest<ResearchQuestion>(`${base}/assistants/${encodeURIComponent(peer)}/questions`, 'POST', body, undefined, owner),
  question: (owner: string, id: string, signal?: AbortSignal) => factoryRequest<ResearchQuestion>(`${base}/assistant-questions/${encodeURIComponent(id)}`, 'GET', undefined, signal, owner),
  inbox: (owner: string, after = '', signal?: AbortSignal) => factoryRequest<Page<ResearchQuestion>>(`${base}/assistant-inbox?limit=20&after=${encodeURIComponent(after)}`, 'GET', undefined, signal, owner),
  recover: (owner: string, id: string) => factoryRequest<ResearchQuestion>(`${base}/assistant-questions/${encodeURIComponent(id)}/recover`, 'POST', undefined, undefined, owner),
  source: (owner: string, id: string, signal?: AbortSignal) => factoryRequest<ResearchSource>(`/application-content/${encodeURIComponent(id)}`, 'GET', undefined, signal, owner),
};
