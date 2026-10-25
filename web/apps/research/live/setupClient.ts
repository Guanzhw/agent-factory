import { factoryRequest } from '../../../api.js';
import type { MaterialReference } from '../../../models.js';
import type { ResearchAgreement } from '../types.js';
export interface SetupConnection { ref: string; registrationRef: string; kind: string; capabilities: string[]; available: boolean }
export interface SetupRequirement { name: string; kind: string; requiredCapabilities: string[] }
export interface SetupCandidates {
  workflowPin: { kind: 'workflow'; id: string; revision: string; sha256: string };
  models: { reference: string; provider: string; model: string; available: boolean; connectionRef?: string }[];
  connections: SetupConnection[];
  environments: { adapterId: string; revision: string; connectionKind: string | null; requiredCapabilities: string[] }[];
  experimentMaterials: (MaterialReference & { name: string; available: boolean; unavailableReason?: string; connectionRequirements: SetupRequirement[] })[];
}
export interface SetupIntent {
  name: string; modelConnectionRef: string;
  environment: { adapterId: string; revision: string; connectionRef?: string };
  experimentMaterialRefs: MaterialReference[]; connectionRefs: Record<string, string>;
  budget: { toolCalls: number; maxDepth: number; maxChildren: number; operationSeconds: number; outputBytes: number };
}
export interface ResearchSetup {
  id: string; state: 'draft' | 'published'; applicationRef: MaterialReference | null;
  connectionRefs: Record<string, string>; materialRefs: MaterialReference[];
  preview: SetupIntent & { workflowPin: SetupCandidates['workflowPin'] };
}
export type ExecutionSelection = Pick<NonNullable<ResearchAgreement['execution']>, 'applicationRef' | 'mode' | 'connectionRefs'>;
const path = '/research/setup';
export const setupApi = {
  candidates: (owner: string, signal?: AbortSignal) => factoryRequest<SetupCandidates>(path, 'GET', undefined, signal, owner),
  read: (owner: string, id: string, signal?: AbortSignal) => factoryRequest<ResearchSetup>(`${path}/${encodeURIComponent(id)}`, 'GET', undefined, signal, owner),
  draft: (owner: string, body: SetupIntent & { requestId: string }) => factoryRequest<ResearchSetup>(`${path}/drafts`, 'POST', body, undefined, owner),
  publish: (owner: string, id: string, body: { requestId: string }) => factoryRequest<ResearchSetup>(`${path}/${encodeURIComponent(id)}/publish`, 'POST', body, undefined, owner),
};
export type SetupCommand = { action: 'draft'; body: SetupIntent & { requestId: string } } | { action: 'publish'; body: { requestId: string } };
