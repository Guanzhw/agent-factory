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
  };
  budget: { rounds: number; toolCalls: number; tokenLimit: number | null; amountMicros: number | null; currency: 'USD' | 'EUR' | 'CNY' | null };
}
export interface ResearchGoal {
  version: number;
  agreement: ResearchAgreement;
  createdAt: string;
  confirmedAt: string | null;
}
export interface ResearchProjectSummary {
  id: string;
  ownerId: string;
  title: string;
  assistantId: string | null;
  state: 'draft' | 'ready' | 'ended';
  currentGoalVersion: number;
  createdAt: string;
  ending: null | { outcome: 'not_met' | 'cancelled'; reason: string; endedAt: string; goalVersion: number; resourceCleanup: 'not_observed' };
  execution: { available: boolean; reason: string | null };
}
export interface ResearchProject extends ResearchProjectSummary { goals: ResearchGoal[] }
export interface Page<T> { items: T[]; nextCursor: string | null }
export interface AssistantSummary { id: string; ownerId: string; name: string; enabled: boolean }
