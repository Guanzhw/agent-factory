import { factoryRequest } from '../../../api.js';
import type { Page } from '../types.js';
export interface EvidenceEntry { id: string; ownerId: string; createdAt: string }
export interface ResearchAssociation extends EvidenceEntry {
  sourceIds: string[]; inputContentIds: string[];
  analysis: { answer: string; citations: string[]; evidenceLevel: 'agent_analysis'; relation: string };
}
const path = '/research';
export const evidenceApi = {
  associations: (owner: string, after: string, signal?: AbortSignal) => factoryRequest<Page<ResearchAssociation>>(`${path}/associations?limit=20&after=${encodeURIComponent(after)}`, 'GET', undefined, signal, owner),
  association: (owner: string, id: string, signal?: AbortSignal) => factoryRequest<ResearchAssociation>(`${path}/associations/${encodeURIComponent(id)}`, 'GET', undefined, signal, owner),
};
