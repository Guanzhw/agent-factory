import { factoryRequest } from '../../api.js';
import type { AssistantSummary, Page, ResearchAgreement, ResearchProject, ResearchProjectSummary } from './types.js';
const projectPath = (id: string) => `/research/projects/${encodeURIComponent(id)}`;
export const researchApi = {
  projects: (owner: string, after = '', signal?: AbortSignal) => factoryRequest<Page<ResearchProjectSummary>>(`/research/projects?limit=20&after=${encodeURIComponent(after)}`, 'GET', undefined, signal, owner),
  project: (owner: string, id: string, signal?: AbortSignal) => factoryRequest<ResearchProject>(projectPath(id), 'GET', undefined, signal, owner),
  assistants: (owner: string, after = '', signal?: AbortSignal) => factoryRequest<Page<AssistantSummary>>(`/assistants?limit=50&after=${encodeURIComponent(after)}`, 'GET', undefined, signal, owner),
  create: (owner: string, body: { requestId: string; title: string; assistantId: string | null }) => factoryRequest<ResearchProject>('/research/projects', 'POST', body, undefined, owner),
  goal: (owner: string, id: string, body: { requestId: string; expectedVersion: number; agreement: ResearchAgreement }) => factoryRequest<ResearchProject>(`${projectPath(id)}/goals`, 'POST', body, undefined, owner),
  confirm: (owner: string, id: string, body: { requestId: string; expectedVersion: number }) => factoryRequest<ResearchProject>(`${projectPath(id)}/confirm`, 'POST', body, undefined, owner),
  start: (owner: string, id: string, body: { requestId: string; expectedVersion: number }) => factoryRequest(`${projectPath(id)}/start`, 'POST', body, undefined, owner),
  end: (owner: string, id: string, body: { requestId: string; expectedVersion: number; outcome: 'not_met' | 'cancelled'; reason: string }) => factoryRequest<ResearchProject>(`${projectPath(id)}/end`, 'POST', body, undefined, owner),
};

export type ProjectCommand =
  | { action: 'create'; body: Parameters<typeof researchApi.create>[1] }
  | { action: 'goal'; body: Parameters<typeof researchApi.goal>[2] }
  | { action: 'confirm'; body: Parameters<typeof researchApi.confirm>[2] }
  | { action: 'start'; body: Parameters<typeof researchApi.start>[2] }
  | { action: 'end'; body: Parameters<typeof researchApi.end>[2] };

export async function sendProjectCommand(owner: string, projectId: string | undefined, command: ProjectCommand) {
  switch (command.action) {
    case 'create': return researchApi.create(owner, command.body);
    case 'goal': return researchApi.goal(owner, projectId!, command.body);
    case 'confirm': return researchApi.confirm(owner, projectId!, command.body);
    case 'start':
      await researchApi.start(owner, projectId!, command.body);
      try { return await researchApi.project(owner, projectId!); }
      catch (cause) {
        const detail = cause instanceof Error ? cause.message : '项目读取失败';
        throw new Error(`启动请求已响应，但项目状态尚未核对。请保留原请求并核对原运行。${detail}`, { cause });
      }
    case 'end': return researchApi.end(owner, projectId!, command.body);
  }
}
