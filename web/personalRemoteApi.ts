import type { UserConnection } from './models.js';
import { ApiError, factoryRequest } from './api.js';
export interface RemoteProvider { providerId: string; kind: string; capabilities: string[]; namespace?: 'opencode' | 'native-openresearch'; authModes?: ('bearer' | 'basic-proxy')[]; sessionTemplateSupported?: boolean; projectCreationSupported?: boolean; }
export interface PersonalRemote { registrationRef: string; providerId: string; configRevision: string; revision: string; status: string; available: boolean; origin: string; projectId: string; capabilities: string[]; expiresAt: string | null; allowedActions: string[]; }
export interface PersonalCredential { credentialRef: string; credentialRevision: string; providerId: string; destination: string; status: string; }
export interface CredentialInput { providerId: string; destination: string; username: string; password: string; requestId: string; }
export interface RemoteConfiguration { providerId: string; origin: string; projectId?: string; projectCreation?: true; credentialRef: string; credentialRevision: string; requestId: string; authMode?: 'bearer' | 'basic-proxy'; sessionTemplateId?: string; }
export function definitivelyRejected(status: number): boolean { return [400, 401, 403, 404, 405, 413, 415, 422].includes(status); }
export class RemoteRequestError extends Error {
  constructor(public readonly rejected: boolean, public readonly code?: string) { super(rejected ? '请求已被拒绝，请检查输入和权限后重试。' : '请求结果尚未确认，请核对原请求。'); }
}
// No upstream text, request payload or raw transport error crosses this boundary.
async function safe<T>(path: string, method = 'GET', body?: unknown, signal?: AbortSignal, expectedOwner?: string): Promise<T> {
  try { return await factoryRequest<T>(path, method, body, signal, expectedOwner); }
  catch (error) { throw new RemoteRequestError(error instanceof ApiError && definitivelyRejected(error.status), error instanceof ApiError ? error.code : undefined); }
}
const ref = encodeURIComponent;
export const personalRemoteApi = {
  providers: (signal?: AbortSignal) => safe<RemoteProvider[]>('/personal-remotes/providers', 'GET', undefined, signal),
  list: (signal?: AbortSignal) => safe<PersonalRemote[]>('/personal-remotes', 'GET', undefined, signal),
  credentialAvailability: (signal?: AbortSignal) => safe<{ enabled: boolean; providerIds: string[] }>('/personal-credentials/capabilities', 'GET', undefined, signal),
  credentials: (signal?: AbortSignal, expectedOwner?: string) => safe<PersonalCredential[]>('/personal-credentials', 'GET', undefined, signal, expectedOwner),
  recoverBinding: (requestId: string) => safe<{ requestId: string; action: string; connection: UserConnection }>(`/user-connections/requests/${ref(requestId)}`),
  saveCredential: (input: CredentialInput, expectedOwner?: string) => safe<PersonalCredential>('/personal-credentials', 'POST', input, undefined, expectedOwner),
  recoverCredential: (requestId: string, expectedOwner?: string) => safe<PersonalCredential>(`/personal-credentials/requests/${ref(requestId)}`, 'GET', undefined, undefined, expectedOwner),
  rotateCredential: (credential: PersonalCredential, username: string, password: string, requestId: string, expectedOwner: string) => safe<PersonalCredential>(`/personal-credentials/${ref(credential.credentialRef)}/rotate`, 'POST', { credentialRevision: credential.credentialRevision, username, password, requestId }, undefined, expectedOwner),
  revokeCredential: (credential: PersonalCredential, requestId: string, expectedOwner?: string) => safe<PersonalCredential>(`/personal-credentials/${ref(credential.credentialRef)}/revoke`, 'POST', { credentialRevision: credential.credentialRevision, requestId }, undefined, expectedOwner),
  recover: (requestId: string) => safe<{ requestId: string; action: string; remote: PersonalRemote }>(`/personal-remotes/requests/${ref(requestId)}`),
  configure: (input: RemoteConfiguration, reference?: string) => safe<PersonalRemote>(`/personal-remotes${reference ? `/${ref(reference)}/configure` : ''}`, 'POST', input),
  command: (remote: PersonalRemote, action: 'verify' | 'revoke', requestId: string) => safe<PersonalRemote>(`/personal-remotes/${ref(remote.registrationRef)}/${action}`, 'POST', { requestId }),
};
export function remoteCanBind(remote: PersonalRemote, at = Date.now()): boolean {
  return remote.available && remote.status === 'verified' && remote.allowedActions.includes('bind') && !!remote.expiresAt && Number.isFinite(Date.parse(remote.expiresAt)) && Date.parse(remote.expiresAt) > at;
}
