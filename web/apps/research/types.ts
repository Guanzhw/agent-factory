export interface ResearchAgreement {
  objective: string;
  evaluation: string;
  stopConditions: string;
  resourceRefs: Record<string, string>;
  execution?: {
    applicationRef: { id: string; version: number; sha256: string };
    mode: string;
    materialChoices: Record<string, { id: string; version: number; sha256: string }>;
    connectionRefs: Record<string, string>;
    deadline: number;
    perRoundCaps: ResearchAgreement['budget'];
  } | null;
  evidence?: { kind?: 'cli' | 'ssh-process'; toolMaterial: { id: string; version: number; sha256: string }; fields: Partial<Record<'metrics' | 'source' | 'run_recipe', string>> } | null;
  budget: { rounds: number; toolCalls: number; tokenLimit: number | null; amountMicros: number | null; currency: 'USD' | 'EUR' | 'CNY' | null };
}
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
  execution: { available: boolean; reason: string | null };
}
export interface ResearchProject extends ResearchProjectSummary { goals: ResearchGoal[] }
export interface Page<T> { items: T[]; nextCursor: string | null }
