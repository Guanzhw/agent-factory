import { factoryRequest } from './api.js';

export const SSH_ORX_PROVIDER = 'ssh-openresearch-session-v1';
export interface OwnedServer { reference: string; name: string; defaultDirectory: string; }
export const PLATFORM_ORX_PROVIDER = 'platform-openresearch-session-v1';
export interface ApplicationEnvironment {
  id: string; applicationId: string; location: 'platform' | 'ssh'; state: string; serverRef?: string; remoteDirectory?: string;
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
  capabilities: (signal?: AbortSignal) => factoryRequest<{ locations: string[]; applications: string[]; selfServiceSSH?: boolean }>('/application-environments/capabilities', 'GET', undefined, signal),
  servers: (signal?: AbortSignal) => factoryRequest<OwnedServer[]>('/application-environments/servers', 'GET', undefined, signal),
  prepare: (owner: string, requestId: string, selection: { location: 'platform' | 'ssh'; serverRef?: string; directory?: string } = { location: 'platform' }) => factoryRequest<EnvironmentRequest>('/application-environments/prepare', 'POST', { requestId, applicationId: 'openresearch', ...selection }, undefined, owner),
  recover: (requestId: string, signal?: AbortSignal) => factoryRequest<EnvironmentRequest>(`/application-environments/requests/${encodeURIComponent(requestId)}`, 'GET', undefined, signal),
  stop: (owner: string, id: string, requestId: string) => factoryRequest<EnvironmentRequest>(`/application-environments/${encodeURIComponent(id)}/stop`, 'POST', { requestId }, undefined, owner),
};
