import { factoryRequest } from '../../api.js';
import type { Page, ResearchProject, ResearchProjectSummary } from './types.js';
const projectPath = (id: string) => `/research/projects/${encodeURIComponent(id)}`;
export const researchApi = {
  projects: (owner: string, after = '', signal?: AbortSignal) => factoryRequest<Page<ResearchProjectSummary>>(`/research/projects?limit=20&after=${encodeURIComponent(after)}`, 'GET', undefined, signal, owner),
  project: (owner: string, id: string, signal?: AbortSignal) => factoryRequest<ResearchProject>(projectPath(id), 'GET', undefined, signal, owner),
};
