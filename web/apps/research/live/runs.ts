import { factoryRequest } from '../../../api.js';
export interface RoundDecision { sourceAssessments?: { contentId: string; disposition: 'use' | 'reproduce' | 'not_applicable'; reason: string }[]; action: 'continue' | 'stop'; outcome: 'met' | 'not_met' | null; reason: string; evidenceIds: string[] }
export interface VisibleResearchRound {
  sourceUnavailable?: false;
  id: string; goalVersion: number; taskId: string | null; terminalRecordId: string | null;
  decision: RoundDecision | null;
  terminal: null | { verificationStatus: 'unverified'; runtime: { taskId: string; runId: string | null; status: string }[]; continuationBlocked: string | null; sharing: string };
}
export type ResearchRound = VisibleResearchRound | { id: string; goalVersion: number; taskId: string | null; terminalRecordId: string | null; sourceUnavailable: true; decision: null; terminal: null | { state: 'ended' } };
interface OriginalOperation { id: string; closed: boolean; observation: { state: string; output?: { artifacts?: { id?: string; name?: string }[] } | null } | null }
interface ExperimentBase { id: string; projectId: string; goalVersion: number; hypothesis: string; conditions: Record<string, unknown> }
type VisibleResearchExperiment = ExperimentBase & { sourceUnavailable?: false } & (
  { attempts: { id: string; operationId: string | null; operation: OriginalOperation | null }[] }
  | { attempt: { id: string; requestId: string; execution: { taskId: string | null; runId?: string | null; status?: string } | null } }
);
export type ResearchExperiment = VisibleResearchExperiment | { id: string; projectId: string; goalVersion: number; sourceUnavailable: true; attempts: { id: string; operationId: string | null }[] };
export interface ResearchRuns { items: ResearchExperiment[]; rounds?: ResearchRound[] }
export const readResearchRuns = (ownerId: string, projectId: string, signal?: AbortSignal) => factoryRequest<ResearchRuns>(`/research/projects/${encodeURIComponent(projectId)}/experiments`, 'GET', undefined, signal, ownerId);
