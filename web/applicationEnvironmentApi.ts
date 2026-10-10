import { factoryRequest } from './api.js';

export const PLATFORM_ORX_PROVIDER = 'platform-openresearch-session-v1';
export interface ApplicationEnvironment {
  id: string; applicationId: string; location: 'platform'; state: string;
  packageVersion: string; projectId: string; connectionRef: string | null;
  modelReference: string; modelRevision: string; dataRetained: true; researchSubmitted: false;
  runtimeLimits?: { leaseSeconds: number; maxActiveSeconds: number; workExtendsLease: true;
    automaticWorkReplay: false; interruptedWorkRecovery: false; externalToolNetwork: false };
}
export interface EnvironmentRequest {
  requestId: string; action: 'prepare' | 'stop'; state: string;
  diagnostic: string | null; environment: ApplicationEnvironment;
}
export const applicationEnvironmentApi = {
  capabilities: (signal?: AbortSignal) => factoryRequest<{ locations: string[]; applications: string[] }>('/application-environments/capabilities', 'GET', undefined, signal),
  prepare: (owner: string, requestId: string) => factoryRequest<EnvironmentRequest>('/application-environments/prepare', 'POST', { requestId, applicationId: 'openresearch', location: 'platform' }, undefined, owner),
  recover: (requestId: string, signal?: AbortSignal) => factoryRequest<EnvironmentRequest>(`/application-environments/requests/${encodeURIComponent(requestId)}`, 'GET', undefined, signal),
  stop: (owner: string, id: string, requestId: string) => factoryRequest<EnvironmentRequest>(`/application-environments/${encodeURIComponent(id)}/stop`, 'POST', { requestId }, undefined, owner),
};
