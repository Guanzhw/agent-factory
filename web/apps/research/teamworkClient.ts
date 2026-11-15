import { factoryRequest } from '../../api.js';
import type { ResearchQuestion } from './live/assistantClient.js';

export interface TeamEntry {
  id: string; kind: 'request' | 'contribution' | 'synthesis'; memberId: string; text: string;
  evidenceIds: string[]; createdAt: string; questionId?: string; recipientId?: string;
  reply?: ResearchQuestion['reply']; delivery?: ResearchQuestion['delivery'];
  origin?: { sessionId?: string; turnId?: string; taskId?: string; runId?: string; projectId?: string };
}
export interface TeamWorkRecord {
  id: string; title: string; goal: string; leadId: string; createdAt: string; updatedAt: string;
  projectId?: string; sessionId?: string; entries: TeamEntry[]; synthesis?: TeamEntry;
}
const base = '/research/team-work';
export const teamworkApi = {
  list: (owner: string, signal?: AbortSignal) => factoryRequest<{ items: TeamWorkRecord[] }>(base, 'GET', undefined, signal, owner),
  read: (owner: string, id: string, signal?: AbortSignal) => factoryRequest<TeamWorkRecord>(`${base}/${encodeURIComponent(id)}`, 'GET', undefined, signal, owner),
  create: (owner: string, body: { requestId: string; title: string; goal: string; sessionId?: string; projectId?: string }) => factoryRequest<TeamWorkRecord>(base, 'POST', body, undefined, owner),
  request: (owner: string, id: string, body: { requestId: string; assistantId: string; text: string; sessionId: string }) => factoryRequest<TeamWorkRecord>(`${base}/${encodeURIComponent(id)}/requests`, 'POST', body, undefined, owner),
  contribute: (owner: string, id: string, body: { requestId: string; text: string; evidenceIds: string[]; sessionId?: string }) => factoryRequest<TeamWorkRecord>(`${base}/${encodeURIComponent(id)}/contributions`, 'POST', body, undefined, owner),
  synthesize: (owner: string, id: string, body: { requestId: string; text: string; evidenceIds: string[] }) => factoryRequest<TeamWorkRecord>(`${base}/${encodeURIComponent(id)}/synthesis`, 'POST', body, undefined, owner),
};
