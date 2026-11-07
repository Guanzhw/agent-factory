import { ApiError, factoryRequest } from './api.js';
export interface PersonalCredential { credentialRef: string; credentialRevision: string; providerId: string; destination: string; status: string; }
export interface CredentialInput { providerId: string; destination: string; username: string; password: string; requestId: string; }
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
  credentialAvailability: (signal?: AbortSignal) => safe<{ enabled: boolean; providerIds: string[] }>('/personal-credentials/capabilities', 'GET', undefined, signal),
  credentials: (signal?: AbortSignal, expectedOwner?: string) => safe<PersonalCredential[]>('/personal-credentials', 'GET', undefined, signal, expectedOwner),
  saveCredential: (input: CredentialInput, expectedOwner?: string) => safe<PersonalCredential>('/personal-credentials', 'POST', input, undefined, expectedOwner),
  recoverCredential: (requestId: string, expectedOwner?: string) => safe<PersonalCredential>(`/personal-credentials/requests/${ref(requestId)}`, 'GET', undefined, undefined, expectedOwner),
  rotateCredential: (credential: PersonalCredential, username: string, password: string, requestId: string, expectedOwner: string) => safe<PersonalCredential>(`/personal-credentials/${ref(credential.credentialRef)}/rotate`, 'POST', { credentialRevision: credential.credentialRevision, username, password, requestId }, undefined, expectedOwner),
  revokeCredential: (credential: PersonalCredential, requestId: string, expectedOwner?: string) => safe<PersonalCredential>(`/personal-credentials/${ref(credential.credentialRef)}/revoke`, 'POST', { credentialRevision: credential.credentialRevision, requestId }, undefined, expectedOwner),
};
