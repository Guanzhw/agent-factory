import { factoryRequest } from './api.js';
import type { UserConnection } from './models.js';
import { checkSession, samePersonalPin, historicalConnectionMatches, type PersonalNamespace, type PersonalSession } from './personalAgentApi.js';
export interface BindingHistoryEntry { requestId: string; oldConnectionPin: UserConnection; newConnectionPin: UserConnection; changedAt: string }
export interface RebindPreview { sessionId: string; oldConnectionPin: UserConnection; newConnectionPin: UserConnection; nativeProjectId: string; nativeSessionId: string; namespace: PersonalNamespace; activeRequestId: string | null; canRebind: boolean; blocker: string | null; blockers?: { requestId: string; action: 'interrupt' | 'prompt'; state: string; source: 'durable-command-ledger' | 'active-request' }[]; observation?: PersonalSession['observation']; bindingHistory: BindingHistoryEntry[] }
export interface RebindRecovery { requestId: string; sessionId: string; connectionRef: string; oldConnectionRef: string; expectedOldFingerprint: string; expectedNewFingerprint: string; nativeProjectId: string; nativeSessionId: string; originalPlanId?: string; originalTaskId?: string; originalRunId?: string }
export interface RebindReceipt { requestId: string; action: 'rebind'; state: 'acknowledged'; factoryIdentity: null; result: { status: 'rebound'; oldConnectionPin: UserConnection; newConnectionPin: UserConnection }; session: PersonalSession }
function invalid(): never { throw new Error('续接范围无法核对。原请求与原会话保持不变。'); }
const hash = (value: unknown) => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
function checkPins(old: UserConnection, next: UserConnection, ownerId: string, namespace: PersonalNamespace) {
  if (!old || !next || old.ownerId !== ownerId || next.ownerId !== ownerId || old.kind !== (namespace === 'opencode' ? 'environment' : 'orx') || next.kind !== old.kind || old.taskId !== next.taskId || next.taskId !== null || old.ref === next.ref || !hash(old.fingerprint) || !hash(next.fingerprint) || !Array.isArray(old.capabilities) || !Array.isArray(next.capabilities) || next.capabilities.some(cap => !old.capabilities.includes(cap)) || !next.capabilities.includes('session:read') || next.status !== 'active' || next.available !== true) invalid();
}
export function checkRebindPreview(value: RebindPreview, session: PersonalSession, candidate: UserConnection, ownerId: string): RebindPreview {
  if (!value || value.sessionId !== session.id || value.namespace !== session.namespace || value.nativeProjectId !== session.nativeProjectId || value.nativeSessionId !== session.nativeSessionId || value.oldConnectionPin?.ref !== session.connectionRef || value.oldConnectionPin.fingerprint !== session.connectionPin?.fingerprint || value.newConnectionPin?.ref !== candidate.ref || value.newConnectionPin.fingerprint !== candidate.fingerprint || !Array.isArray(value.bindingHistory) || typeof value.canRebind !== 'boolean' || !(value.activeRequestId === null || typeof value.activeRequestId === 'string') || (value.canRebind ? value.blocker !== null || value.activeRequestId !== null : !value.blocker)) invalid();
  if (value.blockers && (!Array.isArray(value.blockers) || value.canRebind && value.blockers.length > 0 || value.blockers.some(item => typeof item.requestId !== 'string' || !/^[a-zA-Z0-9_.:-]{1,200}$/.test(item.requestId) || !['interrupt', 'prompt'].includes(item.action) || typeof item.state !== 'string' || !['durable-command-ledger', 'active-request'].includes(item.source)))) invalid();
  checkPins(value.oldConnectionPin, value.newConnectionPin, ownerId, session.namespace);
  if (!session.connectionPin || !samePersonalPin(value.oldConnectionPin, session.connectionPin) || !samePersonalPin(value.newConnectionPin, candidate)) invalid();
  return value;
}
export function rebindRecovery(preview: RebindPreview, session: PersonalSession, requestId: string): RebindRecovery {
  return { requestId, sessionId: session.id, connectionRef: preview.newConnectionPin.ref, oldConnectionRef: preview.oldConnectionPin.ref, expectedOldFingerprint: preview.oldConnectionPin.fingerprint, expectedNewFingerprint: preview.newConnectionPin.fingerprint, nativeProjectId: session.nativeProjectId, nativeSessionId: session.nativeSessionId!, ...(session.factoryIdentity ? { originalPlanId: session.factoryIdentity.planId, originalTaskId: session.factoryIdentity.taskId, originalRunId: session.factoryIdentity.nativeRunId } : {}) };
}
export function checkedRebindRecovery(value: unknown): RebindRecovery | null {
  if (!value || typeof value !== 'object') return null;
  const input = value as Record<string, unknown>; const fields = ['requestId', 'sessionId', 'connectionRef', 'oldConnectionRef', 'nativeProjectId', 'nativeSessionId'];
  if (fields.some(key => typeof input[key] !== 'string' || !/^[a-zA-Z0-9_.:-]{1,200}$/.test(input[key] as string)) || !hash(input.expectedOldFingerprint) || !hash(input.expectedNewFingerprint)) return null;
  const optional = ['originalPlanId', 'originalTaskId', 'originalRunId'];
  if (optional.some(key => input[key] !== undefined) && optional.some(key => typeof input[key] !== 'string' || !/^[a-zA-Z0-9_.:-]{1,200}$/.test(input[key] as string))) return null;
  return Object.fromEntries([...fields, 'expectedOldFingerprint', 'expectedNewFingerprint', ...optional].filter(key => input[key] !== undefined).map(key => [key, input[key]])) as unknown as RebindRecovery;
}
export function checkRebindReceipt(value: RebindReceipt, pending: RebindRecovery, ownerId: string, namespace: PersonalNamespace): RebindReceipt {
  if (!value || value.requestId !== pending.requestId || value.action !== 'rebind' || value.state !== 'acknowledged' || value.factoryIdentity !== null || value.result?.status !== 'rebound') invalid();
  const old = value.result.oldConnectionPin; const next = value.result.newConnectionPin;
  checkPins(old, next, ownerId, namespace);
  if (old.ref !== pending.oldConnectionRef || old.fingerprint !== pending.expectedOldFingerprint || next.ref !== pending.connectionRef || next.fingerprint !== pending.expectedNewFingerprint) invalid();
  const session = checkSession(value.session);
  if (session.id !== pending.sessionId || session.namespace !== namespace || session.nativeProjectId !== pending.nativeProjectId || session.nativeSessionId !== pending.nativeSessionId || !historicalConnectionMatches(session, next) || (pending.originalPlanId ? session.factoryIdentity?.planId !== pending.originalPlanId || session.factoryIdentity.taskId !== pending.originalTaskId || session.factoryIdentity.nativeRunId !== pending.originalRunId : session.factoryIdentity !== null)) invalid();
  if (!session.bindingHistory?.some(entry => entry.requestId === pending.requestId && samePersonalPin(entry.oldConnectionPin, old) && samePersonalPin(entry.newConnectionPin, next))) invalid();
  return value;
}
const base = '/personal-agent'; const ref = encodeURIComponent;
export const personalRebindApi = {
  preview: (sessionId: string, connectionRef: string, expectedOldFingerprint: string) => factoryRequest<RebindPreview>(`${base}/sessions/${ref(sessionId)}/rebind-preview?connectionRef=${ref(connectionRef)}&expectedOldFingerprint=${ref(expectedOldFingerprint)}`),
  commit: (pending: RebindRecovery) => factoryRequest<RebindReceipt>(`${base}/sessions/${ref(pending.sessionId)}/rebind`, 'POST', { requestId: pending.requestId, connectionRef: pending.connectionRef, expectedOldFingerprint: pending.expectedOldFingerprint, expectedNewFingerprint: pending.expectedNewFingerprint }),
  recover: (requestId: string) => factoryRequest<RebindReceipt>(`${base}/requests/${ref(requestId)}`),
};
