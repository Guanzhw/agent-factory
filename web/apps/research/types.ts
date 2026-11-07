export interface ResearchAgreement { objective: string; evaluation: string; stopConditions: string }
export interface VisibleResearchGoal {
  sourceUnavailable?: false;
  version: number;
  agreement: ResearchAgreement;
  createdAt: string;
  confirmedAt: string | null;
}
export type ResearchGoal = VisibleResearchGoal | { version: number; confirmedAt: string | null; sourceUnavailable: true };
export interface ResearchProjectSummary {
  sourceUnavailable?: boolean;
  id: string;
  ownerId: string;
  title: string;
  assistantId: string | null;
  researchAssistantId?: string | null;
  state: 'draft' | 'ready' | 'ended';
  currentGoalVersion: number;
  createdAt: string;
  ending: null | { state: 'ended' } | { outcome: 'met' | 'not_met' | 'cancelled'; reason: string; endedAt: string; goalVersion: number; resourceCleanup: 'not_observed' | 'stopped'; verificationStatus?: 'agent_analysis' };
}
export interface ResearchProject extends ResearchProjectSummary { goals: ResearchGoal[] }
export interface Page<T> { items: T[]; nextCursor: string | null }
