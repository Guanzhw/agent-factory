import { factoryRequest } from './api.js';
import type { FactoryJob, Plan, PlanAuthorization, UserConnection } from './models.js';
export const PERSONAL_PROVIDER = 'opencode-personal-session-v1';
export const ORX_PERSONAL_PROVIDER = 'openresearch-personal-session-v1';
export type PersonalNamespace = 'opencode' | 'native-openresearch';
export const PERSONAL_CONTRACT = 'personal-external-v1';
export type PersonalAction = 'create' | 'prompt' | 'interrupt';
export interface PersonalProject { namespace: PersonalNamespace; executionContract: typeof PERSONAL_CONTRACT; nativeProjectId: string; connectionPin: { ref: string; [key: string]: unknown }; upstreamOrxProjectId: string | null; budgetEnforcement: 'advisory'; modelCredentialCustody: 'remote'; stopGuarantee: 'unverified'; sessionCreationSupported?: boolean }
export interface PersonalMessage { id: string; role: 'user' | 'assistant'; completed: boolean; events: ({ type: 'text'; text: string } | { type: 'tool'; tool: string; status: string; output: string })[]; usage?: { cost?: number; tokens?: Record<string, number> }; correlationSource?: string; usageProvenance: 'remote-reported' | 'unavailable' }
export interface PersonalSession { connectionPin?: UserConnection; bindingStatus?: string; bindingHistory?: import('./personalRebindApi.js').BindingHistoryEntry[]; id: string; namespace: PersonalNamespace; executionContract: typeof PERSONAL_CONTRACT; connectionRef: string; nativeProjectId: string; nativeSessionId: string | null; activeRequestId?: string | null; state: string; upstreamOrxProjectId: string | null; factoryIdentity: { planId: string; taskId: string; nativeRunId: string; executionContract: typeof PERSONAL_CONTRACT } | null; observation: { correlationSource?: string; exactTurnVerified?: false; usageStatus?: string; messages: PersonalMessage[]; observedAt: string; provenance: 'remote-reported'; trustedMetering: false; sessionId: string; projectId: string } | null; modelCredentialCustody: 'remote'; budgetEnforcement: 'advisory'; stopVerified: false; liveEndToEndVerified: false }
export type PersonalIntent = { requestId: string; action: 'create'; connectionRef: string; nativeProjectId: string; title: string } | { requestId: string; action: 'prompt'; sessionId: string; text: string } | { requestId: string; action: 'interrupt'; sessionId: string };
export interface PersonalPrepared { executionContract: typeof PERSONAL_CONTRACT; plan: Plan; authorization: PlanAuthorization; commandSuccessMeans: 'remote-command-acceptance-only'; remoteStopVerified: false; remoteBudgetEnforcement: 'advisory' }
export interface PersonalReceipt { requestId: string; action: PersonalAction; state: 'ack_unknown' | 'acknowledged' | 'result_observed'; session: PersonalSession; factoryIdentity: NonNullable<PersonalSession['factoryIdentity']> }
export interface PersonalRecovery { requestId: string; plan: Plan; authorization: PlanAuthorization; job: FactoryJob | null; nativeRunId: string | null; receipt: PersonalReceipt | null }
export interface NativePersonalSession { nativeSessionId: string; nativeProjectId: string; namespace?: PersonalNamespace; title?: string }
export interface NativePersonalSessions { nativeProjectId: string; namespace: PersonalNamespace; executionContract: typeof PERSONAL_CONTRACT; connectionPin: { ref: string }; sessions: NativePersonalSession[] }
export interface PersonalAttachment { requestId: string; connectionRef: string; nativeProjectId: string; nativeSessionId: string }
export interface AttachmentReceipt { requestId: string; action: 'attach'; state: 'acknowledged'; factoryIdentity: null; result: { nativeProjectId: string; nativeSessionId: string; status: 'attached_read_only' }; session: PersonalSession }
export function samePersonalPin(left: UserConnection, right: UserConnection): boolean {
  return ['ref', 'fingerprint', 'ownerId', 'kind', 'version', 'revision', 'taskId', 'registrationRef'].every(key => left[key as keyof UserConnection] === right[key as keyof UserConnection]) && Array.isArray(left.capabilities) && Array.isArray(right.capabilities) && [...left.capabilities].sort().join('\u0000') === [...right.capabilities].sort().join('\u0000');
}
export function historicalConnectionMatches(session: PersonalSession, expected: { ref: string; fingerprint?: string; capabilities?: string[] }): boolean {
  if (session.connectionRef === expected.ref && (!expected.fingerprint || session.connectionPin?.fingerprint === expected.fingerprint)) return !expected.capabilities || !!session.connectionPin && [...session.connectionPin.capabilities].sort().join('\u0000') === [...expected.capabilities].sort().join('\u0000');
  const history = session.bindingHistory; const current = session.connectionPin;
  if (!Array.isArray(history) || !current || current.kind !== (session.namespace === 'opencode' ? 'environment' : 'orx')) return false;
  const start = history.findIndex(entry => entry.oldConnectionPin?.ref === expected.ref && (!expected.fingerprint || entry.oldConnectionPin.fingerprint === expected.fingerprint));
  if (start < 0) return false;
  let cursor: { ref: string; fingerprint?: string; capabilities?: string[] } = expected; let previous: UserConnection | undefined; const seen = new Set([cursor.ref]);
  for (const entry of history.slice(start)) {
    const old = entry.oldConnectionPin; const next = entry.newConnectionPin;
    if (!entry.requestId || !old || !next || previous && !samePersonalPin(old, previous) || cursor.capabilities && (!Array.isArray(old.capabilities) || [...old.capabilities].sort().join('\u0000') !== [...cursor.capabilities].sort().join('\u0000')) || old.ref !== cursor.ref || cursor.fingerprint && old.fingerprint !== cursor.fingerprint || old.ownerId !== current.ownerId || next.ownerId !== current.ownerId || old.kind !== current.kind || next.kind !== current.kind || old.taskId !== current.taskId || next.taskId !== current.taskId || !Array.isArray(old.capabilities) || !Array.isArray(next.capabilities) || next.capabilities.some(cap => !old.capabilities.includes(cap)) || !/^[a-f0-9]{64}$/.test(old.fingerprint) || !/^[a-f0-9]{64}$/.test(next.fingerprint) || seen.has(next.ref)) return false;
    seen.add(next.ref); cursor = next; previous = next;
  }
  return cursor.ref === session.connectionRef && cursor.ref === current.ref && cursor.fingerprint === current.fingerprint;
}
export function checkAttachment(value: AttachmentReceipt, expected: PersonalAttachment, namespace: PersonalNamespace): AttachmentReceipt {
  if (!value || value.requestId !== expected.requestId || value.action !== 'attach' || value.state !== 'acknowledged' || value.factoryIdentity !== null || value.result?.status !== 'attached_read_only' || value.result.nativeProjectId !== expected.nativeProjectId || value.result.nativeSessionId !== expected.nativeSessionId) invalid();
  const session = checkSession(value.session);
  if (session.namespace !== namespace || !historicalConnectionMatches(session, { ref: expected.connectionRef }) || session.nativeProjectId !== expected.nativeProjectId || session.nativeSessionId !== expected.nativeSessionId) invalid();
  return value;
}
function invalid(): never { throw new Error('个人会话回执无法核对。'); }
export function checkSession(value: PersonalSession): PersonalSession {
  if (!value || !['opencode', 'native-openresearch'].includes(value.namespace) || value.executionContract !== PERSONAL_CONTRACT || value.upstreamOrxProjectId !== (value.namespace === 'opencode' ? null : value.nativeProjectId) || value.modelCredentialCustody !== 'remote' || value.budgetEnforcement !== 'advisory' || value.stopVerified !== false || value.liveEndToEndVerified !== false || typeof value.id !== 'string' || typeof value.connectionRef !== 'string' || typeof value.nativeProjectId !== 'string' || !(value.nativeSessionId === null || typeof value.nativeSessionId === 'string') || value.factoryIdentity !== null && value.factoryIdentity?.executionContract !== PERSONAL_CONTRACT) invalid();
  if (value.observation && (value.observation.trustedMetering !== false || value.observation.provenance !== 'remote-reported' || value.observation.sessionId !== value.nativeSessionId || value.observation.projectId !== value.nativeProjectId || !Array.isArray(value.observation.messages))) invalid();
  return value;
}
export function checkPrepared(value: PersonalPrepared): PersonalPrepared {
  if (!value || value.executionContract !== PERSONAL_CONTRACT || value.commandSuccessMeans !== 'remote-command-acceptance-only' || value.remoteStopVerified !== false || value.remoteBudgetEnforcement !== 'advisory' || !value.plan?.id || !value.plan.fingerprint) invalid();
  return value;
}
export function checkPersonalRecovery(r: PersonalRecovery, requestId: string, planId?: string, startPlanId?: string): PersonalRecovery {
  if (!r || r.requestId !== requestId || !r.plan?.id || !r.plan.fingerprint || planId && r.plan.id !== planId || startPlanId && r.plan.id !== startPlanId) invalid();
  if (r.job && r.job.planId !== r.plan.id) invalid();
  if (r.receipt) {
    const receipt = r.receipt; const values = r.plan.inputValues;
    if (!r.job || !r.nativeRunId || receipt.requestId !== requestId || receipt.factoryIdentity?.executionContract !== PERSONAL_CONTRACT || receipt.factoryIdentity.planId !== r.plan.id || receipt.factoryIdentity.taskId !== r.job.id || receipt.factoryIdentity.nativeRunId !== r.nativeRunId || !values || values.executionContract !== PERSONAL_CONTRACT || receipt.action !== values.action || !['create', 'prompt', 'interrupt'].includes(receipt.action) || !['ack_unknown', 'acknowledged', 'result_observed'].includes(receipt.state)) invalid();
    const session = checkSession(receipt.session);
    let pin: { ref?: unknown; fingerprint?: unknown; capabilities?: string[] };
    try { pin = JSON.parse(String(values.connectionPin)); } catch { invalid(); }
    if (!pin || typeof pin.ref !== 'string' || !historicalConnectionMatches(session, { ref: pin.ref, ...(typeof pin.fingerprint === 'string' ? { fingerprint: pin.fingerprint } : {}), ...(Array.isArray(pin.capabilities) ? { capabilities: pin.capabilities } : {}) }) || session.nativeProjectId !== values.nativeProjectId) invalid();
    if (receipt.action !== 'create' && (session.id !== values.factorySessionId || session.nativeSessionId !== values.nativeSessionId)) invalid();
    if (receipt.action === 'create' && (session.factoryIdentity?.planId !== receipt.factoryIdentity.planId || session.factoryIdentity?.taskId !== receipt.factoryIdentity.taskId || session.factoryIdentity?.nativeRunId !== receipt.factoryIdentity.nativeRunId)) invalid();
  }
  return r;
}
const path = '/personal-agent'; const ref = encodeURIComponent;
export const personalAgentApi = {
  capabilities: (signal?: AbortSignal) => factoryRequest<{ executionContract: string; nativeQueue: boolean; ownerSubmit?: string; modelConfiguration?: string; factoryBYOKForwarded?: false }>(`${path}/capabilities`, 'GET', undefined, signal),
  project: async (connectionRef: string, signal?: AbortSignal) => {
    const p = await factoryRequest<PersonalProject>(`${path}/projects?connectionRef=${ref(connectionRef)}`, 'GET', undefined, signal);
    if (p.executionContract !== PERSONAL_CONTRACT || !['opencode', 'native-openresearch'].includes(p.namespace) || p.connectionPin?.ref !== connectionRef || !p.nativeProjectId || p.upstreamOrxProjectId !== (p.namespace === 'opencode' ? null : p.nativeProjectId) || p.budgetEnforcement !== 'advisory' || p.modelCredentialCustody !== 'remote') invalid();
    return p;
  },
  sessions: async (connectionRef?: string, signal?: AbortSignal) => (await factoryRequest<PersonalSession[]>(`${path}/sessions${connectionRef ? `?connectionRef=${ref(connectionRef)}` : ''}`, 'GET', undefined, signal)).map(checkSession),
  session: async (id: string, signal?: AbortSignal) => {
    const s = checkSession(await factoryRequest<PersonalSession>(`${path}/sessions/${ref(id)}?refresh=true`, 'GET', undefined, signal)); if (s.id !== id) invalid(); return s;
  },
  nativeSessions: async (connectionRef: string, signal?: AbortSignal) => {
    const value = await factoryRequest<NativePersonalSessions>(`${path}/native-sessions?connectionRef=${ref(connectionRef)}`, 'GET', undefined, signal);
    if (!value || !['opencode', 'native-openresearch'].includes(value.namespace) || value.executionContract !== PERSONAL_CONTRACT || value.connectionPin?.ref !== connectionRef || !value.nativeProjectId || !Array.isArray(value.sessions) || value.sessions.some(s => !s.nativeSessionId || s.nativeProjectId !== value.nativeProjectId || s.namespace && s.namespace !== value.namespace || s.title !== undefined && typeof s.title !== 'string')) invalid();
    return value;
  },
  attach: (input: PersonalAttachment) => factoryRequest<AttachmentReceipt>(`${path}/sessions/attach`, 'POST', input),
  recoverAttachment: (requestId: string) => factoryRequest<AttachmentReceipt>(`${path}/requests/${ref(requestId)}`),
  prepare: async (intent: PersonalIntent) => checkPrepared(await factoryRequest<PersonalPrepared>(`${path}/commands/prepare`, 'POST', intent)),
  submit: async (intent: PersonalIntent) => { const job = await factoryRequest<FactoryJob>(`${path}/commands/submit`, 'POST', intent); if (!job?.id || !job.planId) invalid(); return job; },
  start: async (planId: string) => { const job = await factoryRequest<FactoryJob>(`${path}/commands/start`, 'POST', { planId }); if (!job?.id || job.planId !== planId) invalid(); return job; },
  recover: async (requestId: string, signal?: AbortSignal) => {
    const r = await factoryRequest<PersonalRecovery>(`${path}/commands/requests/${ref(requestId)}`, 'GET', undefined, signal);
    return checkPersonalRecovery(r, requestId);
  },
};
