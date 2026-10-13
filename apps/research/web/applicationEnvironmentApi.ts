import { factoryRequest } from '../../../web/api.js';

export const SSH_ORX_PROVIDER = 'ssh-openresearch-session-v1';
export interface OwnedServer { reference: string; name: string; defaultDirectory: string; }
export const PLATFORM_ORX_PROVIDER = 'platform-openresearch-session-v1';
export interface ApplicationEnvironment {
  id: string; applicationId: string; location: 'platform' | 'ssh'; state: string; serverRef?: string; remoteDirectory?: string;
  packageVersion: string; projectId: string; connectionRef: string | null;
  modelReference: string; modelRevision: string; dataRetained: true; researchSubmitted: false;
  originalModelReference?: string; originalModelRevision?: string; credentialBindingFingerprint?: string;
  lastOperation?: { requestId: string; action: 'prepare' | 'stop'; state: string } | null;
  runtimeLimits?: { leaseSeconds: number; maxActiveSeconds: number; workExtendsLease: true;
    automaticWorkReplay: false; interruptedWorkRecovery: false; externalToolNetwork: false };
}
export interface EnvironmentRequest {
  requestId: string; action: 'prepare' | 'stop'; state: string;
  diagnostic: string | null; environment: ApplicationEnvironment;
}
export interface EnvironmentContinuation {
  environmentId: string; projectId: string; dataRetained: true; classification: 'can-continue' | 'needs-new-run' | 'results-only';
  canRebind: boolean; requiresCredentialRebind: boolean; sessionRebindRequired: boolean; previewHash?: string;
  originalWorkReplay: false; researchSubmitted: false; nativeCheckpointContinuationVerified: false;
  reason: string; nextAction: string; message: string;
  currentModelChoice?: { reference: string; revision: string; name: string; provider: string; endpoint: string };
}
export interface EnvironmentBindingReceipt {
  requestId: string; state: 'committed'; environment: ApplicationEnvironment; researchSubmitted: false; runtimePrepared: false;
}
export const applicationEnvironmentApi = {
  inspect: (owner: string, id: string, signal?: AbortSignal) => factoryRequest<ApplicationEnvironment>(`/application-environments/${encodeURIComponent(id)}`, 'GET', undefined, signal, owner),
  list: (owner: string, signal?: AbortSignal) => factoryRequest<ApplicationEnvironment[]>('/application-environments', 'GET', undefined, signal, owner),
  continuation: (owner: string, id: string, signal?: AbortSignal) => factoryRequest<EnvironmentContinuation>(`/application-environments/${encodeURIComponent(id)}/continuation`, 'GET', undefined, signal, owner),
  rebind: (owner: string, id: string, requestId: string, previewHash: string) => factoryRequest<EnvironmentBindingReceipt>(`/application-environments/${encodeURIComponent(id)}/rebind`, 'POST', { requestId, previewHash, approved: true }, undefined, owner),
  bindingRequest: (owner: string, requestId: string, signal?: AbortSignal) => factoryRequest<EnvironmentBindingReceipt>(`/application-environments/binding-requests/${encodeURIComponent(requestId)}`, 'GET', undefined, signal, owner),
  capabilities: (signal?: AbortSignal) => factoryRequest<{ locations: string[]; applications: string[]; selfServiceSSH?: boolean }>('/application-environments/capabilities', 'GET', undefined, signal),
  servers: (signal?: AbortSignal) => factoryRequest<OwnedServer[]>('/application-environments/servers', 'GET', undefined, signal),
  prepare: (owner: string, requestId: string, selection: { location: 'platform' | 'ssh'; serverRef?: string; directory?: string; newEnvironment?: boolean; environmentId?: string } = { location: 'platform' }) => factoryRequest<EnvironmentRequest>('/application-environments/prepare', 'POST', { requestId, applicationId: 'openresearch', ...selection }, undefined, owner),
  recover: (requestId: string, signal?: AbortSignal) => factoryRequest<EnvironmentRequest>(`/application-environments/requests/${encodeURIComponent(requestId)}`, 'GET', undefined, signal),
  stop: (owner: string, id: string, requestId: string) => factoryRequest<EnvironmentRequest>(`/application-environments/${encodeURIComponent(id)}/stop`, 'POST', { requestId }, undefined, owner),
};
